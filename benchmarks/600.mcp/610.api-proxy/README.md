# 610.api-proxy - API Proxy

**Type:** MCP tools
**Languages:** Python
**Architecture:** x64, arm64

## Description

The most common kind of MCP tool: a thin wrapper around a remote REST API (weather, maps, finance, GitHub, ...).
The function sends a GET request to an upstream service, waits for the response, then filters, sorts and trims
the JSON before returning it, as an MCP server does for the model. Most of the execution time is spent waiting
on the upstream, which makes the benchmark useful for studying wall-clock billing and the cost of the network path.

The HTTP connection to the upstream is kept across warm invocations, like the client of a real server, and
the function reports how its time splits: `upstream_connect_us`, `upstream_wait_us`, `upstream_bytes` and `process_us`.
`reuse_connection: false` opens a new connection on every call.

The tool definition used over MCP is in `mcp.json` (`search_products`).

## Upstream service

The benchmark needs an HTTP service reachable from the function, set through the `SEBS_MOCK_UPSTREAM`
environment variable when generating the input (for example `http://<host>:8080`). It must answer

```
GET /api?latency_ms=<ms>&size=<bytes>&seed=<n>
```

after a delay of `latency_ms` with a JSON object `{"total": n, "items": [{"id", "name", "price", "rating", "in_stock", ...}]}`
of about `size` bytes, deterministic for a given `seed`.

## Input sizes

| Size | Upstream delay | Response size |
|---|---|---|
| test | 10 ms | 2 KB |
| small | 200 ms | 16 KB |
| large | 1000 ms | 256 KB |
