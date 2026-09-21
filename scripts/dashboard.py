"""Local, read-only dashboard over the journal.

  .venv/bin/python scripts/dashboard.py            # http://127.0.0.1:8765 (opens your browser)
  .venv/bin/python scripts/dashboard.py --port 9000 --no-browser

Binds to 127.0.0.1 only. Reads data/journal.sqlite; never talks to IBKR or places orders.
"""
from __future__ import annotations

import argparse
import json
import os
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


def allowed_hosts(port: int) -> set[str]:
    """Host headers we answer. Anything else is a DNS-rebinding attempt: a web page on another
    domain that re-pointed its DNS to 127.0.0.1 to read this dashboard through your browser.
    Extra names (e.g. a reverse proxy) via DASHBOARD_ALLOWED_HOSTS=host1:port,host2."""
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    if port == 80:
        hosts |= {"127.0.0.1", "localhost"}
    hosts |= {h.strip().lower() for h in os.getenv("DASHBOARD_ALLOWED_HOSTS", "").split(",") if h.strip()}
    return hosts


class Handler(BaseHTTPRequestHandler):
    allowed: set[str] = set()   # set in main()

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj) -> None:
        self._send(200, json.dumps(obj, default=str).encode(), "application/json")

    def do_GET(self):  # noqa: N802
        if (self.headers.get("Host") or "").lower() not in self.allowed:
            return self._send(403, b"forbidden host", "text/plain")
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
        except Exception as e:  # details go to the server log, not the client
            print(f"dashboard error on {self.path}: {e!r}", file=sys.stderr)
            self._send(500, json.dumps({"error": "internal error - see the dashboard log"}).encode(),
                       "application/json")

    def log_message(self, fmt, *args):  # quiet
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind address; use 0.0.0.0 only inside a container whose port is published to 127.0.0.1")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    Handler.allowed = allowed_hosts(args.port)
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
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
