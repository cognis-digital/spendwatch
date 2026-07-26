"""Prometheus metrics HTTP endpoint using stdlib ``http.server``.

Serves the exposition text at ``/metrics`` (and a small ``/`` index and
``/healthz``). The report is rebuilt per scrape from a caller-supplied
zero-arg callable so metrics stay live.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .outputs import prometheus, json_out

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def make_handler(report_fn):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, code, body: bytes, content_type: str):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path in ("/metrics", "/"):
                report = report_fn()
                if path == "/":
                    body = (
                        "spendwatch metrics endpoint\n"
                        "GET /metrics  Prometheus exposition\n"
                        "GET /report   JSON report\n"
                        "GET /healthz  liveness\n"
                    ).encode("utf-8")
                    self._send(200, body, "text/plain; charset=utf-8")
                    return
                body = prometheus.render(report).encode("utf-8")
                self._send(200, body, CONTENT_TYPE)
                return
            if path == "/report":
                body = json_out.render(report_fn()).encode("utf-8")
                self._send(200, body, "application/json; charset=utf-8")
                return
            if path == "/healthz":
                self._send(200, b"ok\n", "text/plain; charset=utf-8")
                return
            self._send(404, b"not found\n", "text/plain; charset=utf-8")

        def log_message(self, *args):  # silence default logging
            return

    return Handler


def make_server(report_fn, host: str = "127.0.0.1", port: int = 9109) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(report_fn))


def serve(report_fn, host: str = "127.0.0.1", port: int = 9109):  # pragma: no cover
    server = make_server(report_fn, host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
