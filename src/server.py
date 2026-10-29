"""Local HTTP server for the EcoShift API, so the dashboard can run against Python.

Each request is turned into the event API Gateway would send and answered by
``src/handler.py``, so responses match the deployed Lambda.

    python -m src.server             # http://localhost:8000
    python -m src.server --port 9000
"""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit

from src.handler import lambda_handler

DEFAULT_PORT = 8000


class _RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self._respond("GET")

    def do_OPTIONS(self) -> None:
        self._respond("OPTIONS")

    def _respond(self, method: str) -> None:
        url = urlsplit(self.path)
        event = {
            "rawPath": url.path,
            "queryStringParameters": dict(parse_qsl(url.query)) or None,
            "requestContext": {"http": {"method": method}},
        }
        response = lambda_handler(event, None)
        body = response["body"].encode()
        self.send_response(response["statusCode"])
        for name, value in response["headers"].items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def make_server(port: int = DEFAULT_PORT, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    """Build the server without starting it. Port 0 picks a free port."""
    return ThreadingHTTPServer((host, port), _RequestHandler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the EcoShift API locally.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    server = make_server(args.port)
    print(f"EcoShift API on http://localhost:{server.server_port} (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
