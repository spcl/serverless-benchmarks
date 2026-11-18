# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
"""API-wrapper MCP tool: query a REST endpoint and reshape the JSON for the model.

This is the most common kind of MCP tool (weather, maps, finance, GitHub...):
the handler mostly waits on the upstream service, then filters and trims the
response. The upstream (see README.md) delays each response by `latency_ms`
and returns about `size` bytes.
"""

import http.client
import json
import socket
from time import perf_counter
from urllib.parse import urlencode, urlsplit

USER_AGENT = "SeBS-MCP/0.1 (https://github.com/spcl/serverless-benchmarks)"

# Kept across warm invocations, like the HTTP client a real MCP server holds.
_connections = {}


def _us(seconds):
    return int(seconds * 1e6)


def http_get(url, reuse_connection=True, timeout=60):
    """GET url over a keep-alive connection; returns (status, body, measurement)."""
    parts = urlsplit(url)
    path = parts.path + ("?" + parts.query if parts.query else "")
    key = (parts.scheme, parts.netloc)
    measurement = {"upstream_connect_us": 0, "upstream_new_connection": False}
    conn = _connections.get(key) if reuse_connection else None

    for reused in (conn is not None, False):
        if conn is None:
            secure = parts.scheme == "https"
            cls = http.client.HTTPSConnection if secure else http.client.HTTPConnection
            conn = cls(parts.netloc, timeout=timeout)
            begin = perf_counter()
            conn.connect()
            conn.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            measurement["upstream_connect_us"] = _us(perf_counter() - begin)
            measurement["upstream_new_connection"] = True
        try:
            begin = perf_counter()
            conn.request("GET", path, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
            response = conn.getresponse()
            body = response.read()
            measurement["upstream_wait_us"] = _us(perf_counter() - begin)
            break
        except (http.client.HTTPException, OSError):
            conn.close()
            conn = None
            _connections.pop(key, None)
            # A reused connection may have been closed by the server while idle: retry once.
            if not reused:
                raise

    if reuse_connection:
        _connections[key] = conn
    else:
        conn.close()
    measurement["upstream_bytes"] = len(body)
    return response.status, body, measurement


def handler(event):
    query = urlencode({
        "latency_ms": event.get("latency_ms", 0),
        "size": event.get("size", 1024),
        "seed": event.get("seed", 0),
    })
    url = "{}/api?{}".format(event["upstream"].rstrip("/"), query)
    status, body, measurement = http_get(url, event.get("reuse_connection", True))
    if status != 200:
        raise RuntimeError("Upstream returned HTTP {}: {}".format(status, body[:200]))

    # Reshape like an API wrapper: keep what the model needs, drop the rest.
    begin = perf_counter()
    data = json.loads(body)
    items = data["items"]
    if event.get("in_stock_only", True):
        items = [item for item in items if item["in_stock"]]
    items.sort(key=lambda item: (-item["rating"], item["price"]))
    limit = event.get("limit", 10)
    result = {
        "total": data["total"],
        "matching": len(items),
        "items": [
            {k: item[k] for k in ("id", "name", "price", "rating")} for item in items[:limit]
        ],
    }
    measurement["process_us"] = _us(perf_counter() - begin)
    return {"result": result, "measurement": measurement}
