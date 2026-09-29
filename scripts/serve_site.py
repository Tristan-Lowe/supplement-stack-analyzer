"""Serve site/ locally the way Vercel will: static files, /api/analyze, same headers.

    python scripts/serve_site.py   (after scripts/build_site.py)
"""

from __future__ import annotations

import importlib.util
import json
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "site"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8787

spec = importlib.util.spec_from_file_location("analyze_fn", ROOT / "api" / "analyze.py")
analyze_fn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analyze_fn)

HEADERS = {
    h["key"]: h["value"]
    for h in json.loads((ROOT / "vercel.json").read_text())["headers"][0]["headers"]
    if h["key"] != "Strict-Transport-Security"  # not meaningful on http://localhost
}
HEADERS["Content-Security-Policy"] = HEADERS["Content-Security-Policy"].replace(
    "; upgrade-insecure-requests", ""
)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "public"), **kwargs)

    def end_headers(self):
        for key, value in HEADERS.items():
            self.send_header(key, value)
        super().end_headers()

    def do_POST(self):
        if self.path != "/api/analyze":
            self.send_error(404)
            return
        analyze_fn.handler.do_POST(self)

    def _send(self, status, payload):
        analyze_fn.handler._send(self, status, payload)


if __name__ == "__main__":
    print(f"http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
