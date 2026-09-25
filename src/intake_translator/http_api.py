"""Loopback-only HTTP adapter for synthetic intake demonstrations.

Not an internet service: it deliberately has no authentication or TLS. Bind only
127.0.0.1, and do not tunnel this service to other networks.
"""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from socket import gethostbyname
from typing import Any

from .core import IntakeError
from .store import process_once

MAX_BODY_BYTES = 16 * 1024


class IntakeServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], db_path: str):
        super().__init__(address, IntakeHandler)
        self.db_path = db_path


class IntakeHandler(BaseHTTPRequestHandler):
    server: IntakeServer

    def _respond(self, status: int, data: dict[str, Any]) -> None:
        body = json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._respond(200, {"status": "ok", "service": "intake-translator"})
        else:
            self._respond(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path != "/intakes":
            self._respond(404, {"error": "not_found"})
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            self._respond(415, {"error": "unsupported_media_type"})
            return
        length = self.headers.get("Content-Length")
        if length is None or not length.isdecimal():
            self._respond(411, {"error": "content_length_required"})
            return
        size = int(length)
        if size > MAX_BODY_BYTES:
            self._respond(413, {"error": "payload_too_large"})
            return
        if size == 0:
            self._respond(400, {"error": "invalid_json"})
            return
        try:
            data = json.loads(self.rfile.read(size))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._respond(400, {"error": "invalid_json"})
            return
        try:
            packet, replayed = process_once(self.server.db_path, data)
        except IntakeError as exc:
            self._respond(409 if exc.code == "event_id_reused" else 422,
                          {"error": exc.code, "detail": exc.detail})
            return
        # A new resource gets 201. Idempotent replay returns 200 with the same packet.
        self._respond(200 if replayed else 201, {**packet, "replayed": replayed})

    def log_message(self, format: str, *args: object) -> None:
        # Do not echo incoming payloads, which could contain private data.
        return


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="intake-events.sqlite3")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be 1-65535")
    with IntakeServer(("127.0.0.1", args.port), args.db) as server:
        print(f"Demo listening on http://127.0.0.1:{server.server_port}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
