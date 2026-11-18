# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
"""Fetch MCP tool: download a web page and convert it to markdown for the model.

Modeled on the reference `fetch` MCP server: drop page boilerplate (scripts,
navigation, headers, footers), convert the article to markdown, and return at
most `max_length` characters starting at `start_index`. The page comes from the
mock upstream service, delayed by `latency_ms` and about `size` bytes large.
The converter uses only the standard library's HTML parser.
"""

import http.client
import socket
from html.parser import HTMLParser
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


class MarkdownConverter(HTMLParser):
    """HTML to markdown, skipping the parts of a page that are not content."""

    SKIP = {
        "head", "title", "script", "style", "noscript",
        "nav", "header", "footer", "aside", "form", "svg",
    }
    BLOCKS = {"p", "div", "article", "main", "section", "ul", "ol", "table", "pre", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.skip_depth = 0
        self.in_pre = False
        self.link = None
        self.row = None
        self.header_row = False
        self.first_row = False

    def _newline(self, count=1):
        text = "".join(self.out[-2:])
        missing = count - (len(text) - len(text.rstrip("\n")))
        if self.out and missing > 0:
            self.out.append("\n" * missing)

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._newline(2)
            self.out.append("#" * int(tag[1]) + " ")
        elif tag == "li":
            self._newline()
            self.out.append("- ")
        elif tag == "br":
            self.out.append("\n")
        elif tag == "a":
            self.link = (dict(attrs).get("href", ""), len(self.out))
        elif tag == "pre":
            self._newline(2)
            self.out.append("```\n")
            self.in_pre = True
        elif tag == "code" and not self.in_pre:
            self.out.append("`")
        elif tag == "table":
            self._newline(2)
            self.first_row = True
        elif tag == "tr":
            self.row = []
            self.header_row = False
        elif tag in ("td", "th") and self.row is not None:
            self.header_row |= tag == "th"
            self.row.append("")
        elif tag in self.BLOCKS:
            self._newline(2)

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth:
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6", "p", "li"):
            self._newline(2 if tag != "li" else 1)
        elif tag == "a" and self.link is not None:
            href, start = self.link
            raw = "".join(self.out[start:])
            del self.out[start:]
            text = raw.strip()
            lead = " " if raw[:1] == " " else ""
            self.out.append(lead + ("[{}]({})".format(text, href) if href else text))
            self.link = None
        elif tag == "pre":
            self._newline()
            self.out.append("```\n\n")
            self.in_pre = False
        elif tag == "code" and not self.in_pre:
            self.out.append("`")
        elif tag == "tr" and self.row is not None:
            self.out.append("| " + " | ".join(c.strip() for c in self.row) + " |\n")
            if self.first_row:
                self.out.append("|" + " --- |" * len(self.row) + "\n")
                self.first_row = False
            self.row = None
        elif tag == "table":
            self._newline(2)

    def handle_data(self, data):
        if self.skip_depth:
            return
        if not self.in_pre:
            data = " ".join(data.split())
            if not data:
                return
            if (self.out and not self.out[-1].endswith((" ", "\n", "(", "[", "`"))
                    and not data.startswith((".", ",", ";", ":", "!", "?", ")"))):
                data = " " + data
        if self.row is not None and self.row:
            self.row[-1] += data
        else:
            self.out.append(data)

    def markdown(self):
        lines = [line.rstrip() for line in "".join(self.out).split("\n")]
        text = "\n".join(lines).strip()
        while "\n\n\n" in text:
            text = text.replace("\n\n\n", "\n\n")
        return text


def handler(event):
    query = urlencode({
        "latency_ms": event.get("latency_ms", 0),
        "size": event.get("size", 100000),
        "seed": event.get("seed", 0),
    })
    url = "{}/page?{}".format(event["upstream"].rstrip("/"), query)
    status, body, measurement = http_get(url, event.get("reuse_connection", True))
    if status != 200:
        raise RuntimeError("Upstream returned HTTP {}: {}".format(status, body[:200]))

    begin = perf_counter()
    converter = MarkdownConverter()
    converter.feed(body.decode("utf-8", errors="replace"))
    converter.close()
    content = converter.markdown()
    start = event.get("start_index", 0)
    max_length = event.get("max_length", 5000)
    chunk = content[start:start + max_length]
    measurement["process_us"] = _us(perf_counter() - begin)
    measurement["markdown_chars"] = len(content)

    result = {"content": chunk, "start_index": start, "total_length": len(content)}
    if start + max_length < len(content):
        result["next_start_index"] = start + max_length
    return {"result": result, "measurement": measurement}
