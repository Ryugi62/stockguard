"""Tiny web adapter: static page + JSON API. Standard library only."""
import json
import os
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from stockguard.application.service import AmbiguousTicker, TickerNotFound

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "web"))   # packaged with stockguard
CACHE_TTL = 30.0
CACHE_MAX = 512


def check_response(guard, q, auditor=None):
    """GET /api/check as a pure function: (HTTP status, JSON body). Shared by the local server and the in-browser build."""
    ticker, side = q.get("ticker", "").upper(), q.get("side", "BUY").upper()
    qty, usd = q.get("qty", ""), q.get("usd", "")
    try:
        qty_n, usd_n = (float(qty) if qty else None), (float(usd) if usd else None)
    except ValueError:
        return 400, {"error": "Enter the amount as a number, for example 100."}
    try:
        r = guard.check(ticker, side, qty_n, usd_amount=usd_n)
    except AmbiguousTicker as e:
        try:
            e.candidates = guard.describe(e.candidates)
        except Exception:
            pass
        return 409, {"error": e.message(), "choices": e.candidates}
    except TickerNotFound as e:
        hint = f" Did you mean {', '.join(e.suggestions)}?" if e.suggestions else ""
        return 404, {"error": f"No tokenized stock found for '{ticker}'.{hint}"}
    except ValueError as e:
        return 400, {"error": str(e)}
    except Exception as e:
        return 502, {"error": "Upstream data unavailable", "detail": str(e)[:200]}
    try:   # what an AI agent would be told for the same order (same words as the gate)
        from stockguard.application.wallet_gate import gate_swap
        if r.get("usd_amount"):
            gt = gate_swap(guard, r["contract"], r["usd_amount"], side=side, auditor=auditor)
            r["agent_gate"] = {"action": gt["action"], "reasons": gt["reasons"][:3]}
    except Exception:
        pass
    return 200, r


def tickers_response(guard):
    names = {t.get("ticker") for t in guard.tokens() if t.get("ticker")}
    names |= {t.get("symbol") for t in guard.tokens() if t.get("symbol")}
    return sorted(names)


def make_handler(guard, auditor=None):
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
                key = (q.get("ticker", "").upper(), q.get("side", "BUY").upper(), q.get("qty", ""), q.get("usd", ""))
                hit = cache.get(key)
                if hit and time.time() - hit[0] < CACHE_TTL:
                    return self._json(200, hit[1])
                code, obj = check_response(guard, q, auditor)
                if code == 200:
                    if len(cache) >= CACHE_MAX:
                        cache.pop(min(cache, key=lambda k: cache[k][0]))
                    cache[key] = (time.time(), obj)
                return self._json(code, obj)
            if u.path == "/api/tickers":
                return self._json(200, tickers_response(guard))
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


def serve(guard, port=8787, auditor=None):
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(guard, auditor))
    print(f"StockGuard on http://127.0.0.1:{port}")
    srv.serve_forever()
