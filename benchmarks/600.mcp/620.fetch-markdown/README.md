# 620.fetch-markdown - Fetch Markdown

**Type:** MCP tools
**Languages:** Python
**Architecture:** x64, arm64

## Description

A web fetch tool, modeled on the reference `fetch` MCP server. The function downloads an HTML page,
drops the page boilerplate (scripts, navigation, headers, footers), converts the article to markdown
and returns at most `max_length` characters starting at `start_index`, with the index of the next chunk.
It combines a network wait with CPU work that grows with the page size, so its duration depends on the
memory (and therefore CPU) given to the function.

The converter uses only the standard library's HTML parser. The HTTP connection to the upstream is kept across
warm invocations, and the function reports `upstream_connect_us`, `upstream_wait_us`, `upstream_bytes`,
`process_us` (HTML to markdown) and `markdown_chars`.

The tool definition used over MCP is in `mcp.json` (`fetch`).

## Upstream service

The benchmark needs an HTTP service reachable from the function, set through the `SEBS_MOCK_UPSTREAM`
environment variable when generating the input (for example `http://<host>:8080`). It must answer

```
GET /page?latency_ms=<ms>&size=<bytes>&seed=<n>
```

after a delay of `latency_ms` with an HTML page of about `size` bytes whose article starts with the
heading `Benchmark article` (checked by the output validation), surrounded by navigation, scripts and footer.

## Input sizes

| Size | Upstream delay | Page size |
|---|---|---|
| test | 10 ms | 20 KB |
| small | 200 ms | 200 KB |
| large | 1000 ms | 2 MB |
