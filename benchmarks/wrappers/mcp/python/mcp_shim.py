# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
"""Minimal MCP server shim that exposes a SeBS benchmark as a single MCP tool.

Implements the stateless subset of the MCP Streamable HTTP transport: each
POST carries one JSON-RPC message, and the server answers with a single
application/json response (no SSE, no Mcp-Session-Id). This is the mode
serverless MCP hosts (Lambda, Workers, Vercel) run in.

The shim deliberately uses only the standard library, so wrapping a
benchmark as an MCP tool does not change its package size or import time;
the measured difference to a plain invocation is the protocol itself.

Platform wrappers call `handle(message, call_tool, meta)`, where `call_tool(arguments)`
runs the benchmark and returns `(result, meta)`; `meta` carries the usual SeBS
measurements (begin, end, is_cold, container_id, request_id) and is returned
to the client in the tool result's `_meta.sebs`. The `meta` passed to handle
(is_cold, container_id, ...) goes into `_meta.sebs` of the other results, so a
cold start absorbed by `initialize` or `tools/list` is visible too.
"""

import json
import os

PROTOCOL_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26"]
SERVER_INFO = {"name": "sebs-mcp", "version": "0.1.0"}

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

_tool = None


def tool_definition() -> dict:
    """The tool advertised in tools/list, read once from mcp.json next to the function code."""
    global _tool
    if _tool is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp.json")
        if os.path.exists(path):
            with open(path, "r") as f:
                _tool = json.load(f)
        else:
            _tool = {
                "name": "benchmark",
                "description": "SeBS benchmark function.",
                "inputSchema": {"type": "object"},
            }
    return _tool


def is_mcp_message(body) -> bool:
    return isinstance(body, dict) and body.get("jsonrpc") == "2.0" and "method" in body


def _result(msg_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def handle(message, call_tool, meta=None):
    """Process one JSON-RPC message.

    Returns the response message, or None for notifications and responses
    (the transport then answers with HTTP 202 and no body).
    """
    if not is_mcp_message(message):
        return _error(None, INVALID_REQUEST, "Expected a single JSON-RPC 2.0 request")

    method = message["method"]
    msg_id = message.get("id")
    params = message.get("params") or {}

    # Notifications have no id and get no response.
    if msg_id is None:
        return None

    sebs_meta = {"_meta": {"sebs": meta}} if meta else {}

    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return _result(
            msg_id,
            {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
                **sebs_meta,
            },
        )

    if method == "ping":
        return _result(msg_id, {**sebs_meta})

    if method == "tools/list":
        return _result(msg_id, {"tools": [tool_definition()], **sebs_meta})

    if method == "tools/call":
        name = params.get("name")
        if name != tool_definition()["name"]:
            return _error(msg_id, INVALID_PARAMS, f"Unknown tool: {name}")
        arguments = params.get("arguments") or {}
        try:
            result, meta = call_tool(arguments)
        except Exception as e:
            # Tool failures are reported in the result so the model can see them.
            return _result(
                msg_id,
                {
                    "content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}],
                    "isError": True,
                },
            )
        content = {
            "content": [{"type": "text", "text": json.dumps(result)}],
            "isError": False,
            "_meta": {"sebs": meta},
        }
        if isinstance(result, dict):
            content["structuredContent"] = result
        return _result(msg_id, content)

    return _error(msg_id, METHOD_NOT_FOUND, f"Method not found: {method}")
