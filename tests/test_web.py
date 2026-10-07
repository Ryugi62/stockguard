import json, threading, urllib.request, urllib.error
from http.server import ThreadingHTTPServer
from stockguard.adapters.mapping import to_snapshot
from stockguard.adapters.web import make_handler
from stockguard.application.service import Guard
from tests_support import FakeClient


def _serve():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(Guard(FakeClient(), to_snapshot)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def test_api_check_usd_and_404_and_page():
    srv, base = _serve()
    try:
        d = json.load(urllib.request.urlopen(base + "/api/check?ticker=NFLX&usd=1000"))
        assert d["verdict"] == "WARN" and abs(d["usd_amount"] - 1000) < 0.01
        try:
            urllib.request.urlopen(base + "/api/check?ticker=ZZZZ")
            assert False
        except urllib.error.HTTPError as e:
            assert e.code == 404
        assert b"Can I trade" in urllib.request.urlopen(base + "/").read()
        assert b"NFLX" in urllib.request.urlopen(base + "/api/tickers").read()
    finally:
        srv.shutdown()


def test_ambiguous_ticker_returns_choices():
    from test_issuers import ThreeIssuers
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(Guard(ThreeIssuers(), to_snapshot)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        try:
            urllib.request.urlopen(base + "/api/check?ticker=NFLX&usd=100")
            assert False
        except urllib.error.HTTPError as e:
            assert e.code == 409
            assert {c["symbol"] for c in json.load(e)["choices"]} == {"NFLXon", "NFLXx", "NFLXB"}
        d = json.load(urllib.request.urlopen(base + "/api/check?ticker=NFLXx&usd=100"))
        assert d["multiplier_conflict"] is True
        assert b"NFLXB" in urllib.request.urlopen(base + "/api/tickers").read()
    finally:
        srv.shutdown()


def test_check_response_non_numeric_amount_is_plain_english():
    from stockguard.adapters.web import check_response
    code, body = check_response(Guard(FakeClient(), to_snapshot), {"ticker": "NFLXon", "usd": "abc"})
    assert code == 400 and "number" in body["error"] and "float" not in body["error"]
