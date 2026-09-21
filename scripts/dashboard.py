"""Local, read-only dashboard over the journal.

  .venv/bin/python scripts/dashboard.py            # http://127.0.0.1:8765 (opens your browser)
  .venv/bin/python scripts/dashboard.py --port 9000 --no-browser

Binds to 127.0.0.1 only. Reads data/journal.sqlite; never talks to IBKR or places orders.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from guardrail_trader import dashboard_data
from guardrail_trader.config import PROJECT_ROOT
from guardrail_trader.journal import Journal
from guardrail_trader.risk import load_risk_config

HTML = (PROJECT_ROOT / "guardrail_trader" / "web" / "dashboard.html")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj) -> None:
        self._send(200, json.dumps(obj, default=str).encode(), "application/json")

    def do_GET(self):  # noqa: N802
        try:
            if self.path in ("/", "/index.html"):
                return self._send(200, HTML.read_bytes(), "text/html; charset=utf-8")
            if self.path == "/api/data":
                j = Journal()
                try:
                    return self._json(dashboard_data.build(j, load_risk_config()))
                finally:
                    j.close()
            m = re.fullmatch(r"/api/transcript/(\d+)", self.path)
            if m:
                return self._json(dashboard_data.transcript(int(m.group(1))))
            self._send(404, b"not found", "text/plain")
        except Exception as e:  # show errors in the page instead of a dead socket
            self._send(500, json.dumps({"error": repr(e)}).encode(), "application/json")

    def log_message(self, fmt, *args):  # quiet
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"guardrail-trader dashboard on {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
