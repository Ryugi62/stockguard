"""Tiny web adapter: static page + JSON API. Standard library only."""
import json
import os
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from stockguard.application.service import TickerNotFound

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "web"))
CACHE_TTL = 30.0


def make_handler(guard):
    cache = {}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            q = dict(urllib.parse.parse_qsl(u.query))
            if u.path == "/api/check":
                key = (q.get("ticker", "").upper(), q.get("side", "BUY").upper(), q.get("qty", "1"))
                hit = cache.get(key)
                if hit and time.time() - hit[0] < CACHE_TTL:
                    return self._json(200, hit[1])
                try:
                    r = guard.check(key[0], key[1], float(key[2]))
                except TickerNotFound:
                    return self._json(404, {"error": f"No tokenized stock found for '{key[0]}'"})
                except ValueError as e:
                    return self._json(400, {"error": str(e)})
                except Exception as e:
                    return self._json(502, {"error": "Upstream data unavailable", "detail": str(e)[:200]})
                cache[key] = (time.time(), r)
                return self._json(200, r)
            if u.path == "/api/tickers":
                return self._json(200, sorted({t.get("ticker") for t in guard.tokens() if t.get("ticker")}))
            path = "index.html" if u.path in ("/", "") else u.path.lstrip("/")
            full = os.path.abspath(os.path.join(ROOT, path))
            if not full.startswith(ROOT) or not os.path.isfile(full):
                self.send_response(404); self.end_headers(); return
            ctype = "text/html; charset=utf-8" if full.endswith(".html") else "application/octet-stream"
            data = open(full, "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return H


def serve(guard, port=8787):
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(guard))
    print(f"StockGuard on http://127.0.0.1:{port}")
    srv.serve_forever()
