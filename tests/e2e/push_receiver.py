"""Fake push service for the web-push E2E.

`python -m tests.e2e.push_receiver --port 8843 --out FILE`: every POST is recorded as one JSON
line `{"headers": {...lower-cased...}, "length": n}`; `GET /count` returns the number received.
"""
from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def make_handler(out: Path) -> type[BaseHTTPRequestHandler]:
    lock = threading.Lock()
    state = {"count": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            record = {"headers": {k.lower(): v for k, v in self.headers.items()},
                      "length": len(body)}
            with lock:
                with out.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record) + "\n")
                state["count"] += 1
            self._reply(201, b"")

        def do_GET(self) -> None:
            if self.path.rstrip("/") == "/count":
                with lock:
                    n = state["count"]
                self._reply(200, json.dumps({"count": n}).encode(), "application/json")
            else:
                self._reply(404, b"")

        def _reply(self, status: int, body: bytes, ctype: str = "text/plain") -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8843)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.touch()
    server = ThreadingHTTPServer(("", args.port), make_handler(args.out))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
