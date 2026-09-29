"""POST /api/analyze — the checker's only endpoint.

Loads the published-graph snapshot into in-memory SQLite once per instance, then
answers each request with ssa.web.handle_analyze. No database credential, no API
key, and no user data is stored or logged here.
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path

_LIB = Path(__file__).resolve().parent / "_lib"
sys.path.insert(0, str(_LIB))

from ssa.web import MAX_BODY_BYTES, RateLimiter, handle_analyze, load_snapshot  # noqa: E402

_SESSION_FACTORY = load_snapshot(_LIB / "graph.json")
_LIMITER = RateLimiter(limit=30, window_seconds=60)
_LOCK = threading.Lock()  # one shared SQLite connection; analysis takes milliseconds


class handler(BaseHTTPRequestHandler):  # noqa: N801 — name required by Vercel
    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        client = (
            self.headers.get("x-real-ip")
            or (self.headers.get("x-forwarded-for") or "").split(",")[0].strip()
            or "unknown"
        )
        if not _LIMITER.allow(client):
            self._send(429, {"error": "Too many checks in a minute. Wait a moment and try again."})
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY_BYTES:
            self._send(413, {"error": "That stack is too long. Keep it under 2,000 characters."})
            return

        body = self.rfile.read(length)
        try:
            with _LOCK, _SESSION_FACTORY() as session:
                status, payload = handle_analyze(
                    session,
                    body,
                    content_type=self.headers.get("Content-Type"),
                    origin=self.headers.get("Origin"),
                    host=self.headers.get("x-forwarded-host") or self.headers.get("Host"),
                )
        except Exception:  # never leak a traceback to the client
            status, payload = 500, {"error": "The check failed on our side. Try again."}
        self._send(status, payload)

    def do_GET(self) -> None:  # noqa: N802
        self._send(405, {"error": "Use POST."})

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return  # request lines can carry client addresses; don't log them
