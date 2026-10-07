"""In-browser adapter (SPEC UC-8): the same package runs in Pyodide on a static page (GitHub Pages).

The page's JavaScript calls `BrowserApp.handle("/api/check?…")` instead of an HTTP server. All network I/O is
injected (`get_json`, `post_json`), so this file has no browser imports and is tested with plain CPython.
`pyodide_io()` builds the two functions from the browser's synchronous XHR when running in Pyodide.

The token-audit endpoint can't be called from a browser (its CORS preflight returns no
Access-Control-Allow-Headers, so `Content-Type: application/json` is refused, and a text/plain body is answered
"illegal parameter"). The page therefore treats the audit as unreachable — the same fail-closed path the CLI takes
when the audit is down (CONFIRM with the skill's own sentence) — and says so on screen.
"""
import json
import urllib.parse
from typing import Callable, Dict, Tuple

from stockguard.adapters.binance_rwa import RwaClient
from stockguard.adapters.bsc_rpc import BscRpc
from stockguard.adapters.mapping import to_snapshot
from stockguard.adapters.web import check_response, tickers_response
from stockguard.application.service import Guard
from stockguard.domain.wallet_gate import AuditResult


class BrowserAudit:
    """The audit API refuses browser requests (CORS) — report it as unreachable, never as 'no risk'."""

    def audit(self, address: str) -> AuditResult:
        return AuditResult(available=False, error="not callable from a browser (CORS)")


class BrowserApp:
    def __init__(self, get_json: Callable[[str], Dict], post_json: Callable[[str, Dict], Dict]):
        self.guard = Guard(RwaClient(http_get=get_json, retries=2, sleep=lambda s: None), to_snapshot,
                           onchain=BscRpc(post=post_json))
        self.auditor = BrowserAudit()

    def route(self, path_and_query: str) -> Tuple[int, object]:
        u = urllib.parse.urlparse(path_and_query)
        q = dict(urllib.parse.parse_qsl(u.query))
        if u.path == "/api/check":
            return check_response(self.guard, q, self.auditor)
        if u.path == "/api/tickers":
            return 200, tickers_response(self.guard)
        return 404, {"error": "not found"}

    def handle(self, path_and_query: str) -> str:
        """JSON string `[status, body]` — one value crosses the JS/Python boundary."""
        return json.dumps(list(self.route(path_and_query)))


def pyodide_io():   # pragma: no cover — runs only inside Pyodide (checked in a real browser, see SPEC UC-8)
    from js import XMLHttpRequest      # noqa: F401  (Pyodide only)

    def _xhr(method: str, url: str, body=None) -> Dict:
        x = XMLHttpRequest.new()
        x.open(method, url, False)     # synchronous: the domain code is synchronous
        if body is not None:
            x.setRequestHeader("Content-Type", "application/json")
        x.send(body)
        if not 200 <= x.status < 300:
            raise OSError(f"HTTP {x.status} from {url}")
        return json.loads(x.responseText)

    return (lambda url: _xhr("GET", url)), (lambda url, payload: _xhr("POST", url, json.dumps(payload)))
