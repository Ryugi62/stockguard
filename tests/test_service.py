from stockguard.adapters.mapping import to_snapshot
import json, os
import pytest
from stockguard.application.service import Guard, TickerNotFound

FX = os.path.join(os.path.dirname(__file__), "..", "fixtures")


def load(n):
    with open(os.path.join(FX, n)) as f:
        return json.load(f)["data"]


from tests_support import FakeClient


def test_check_by_ticker_resolves_and_warns():
    r = Guard(FakeClient(), to_snapshot).check("nflx", "buy", 2)
    assert r["symbol"] == "NFLXon" and r["verdict"] == "WARN" and r["share_equivalent"] == 20


def test_unknown_ticker():
    with pytest.raises(TickerNotFound):
        Guard(FakeClient(), to_snapshot).check("ZZZZ")


def test_scan_records_errors_without_stopping():
    out = list(Guard(FakeClient(), to_snapshot).scan(workers=2))
    assert len(out) == 5
    assert sum(1 for r in out if "error" in r) == 4
    nflx = [r for r in out if r.get("symbol") == "NFLXon"][0]
    assert nflx["reference_derived"] is True


def test_unknown_ticker_suggests_close_matches():
    with pytest.raises(TickerNotFound) as e:
        Guard(FakeClient(), to_snapshot).check("NFLY")
    assert "NFLX" in e.value.suggestions


def test_check_includes_issuer_attestation():
    r = Guard(FakeClient(), to_snapshot).check("NFLX")
    assert r["name"] == "Netflix (Ondo)" and r["attestation_daily"].startswith("https://bin.bnbstatic.com/")


class FakeChain:
    def __init__(self, supply):
        self.supply = supply
    def total_supply(self, token):
        return self.supply


def test_onchain_supply_feeds_large_order_note_and_mismatch_note():
    g = Guard(FakeClient(), to_snapshot, onchain=FakeChain(100.0))
    r = g.check("NFLX", "BUY", 5)
    assert r["onchain_supply"] == 100.0 and any("Large order" in x for x in r["notes"])
    assert any("circulatingSupply" in n for n in r["data_notes"])   # fixture says ~220.99


def test_last_trade_age_comes_from_trade_derived_kline_candles():
    from stockguard.adapters.mapping import to_snapshot
    from stockguard.application.service import Guard, last_trade_age_hours
    now_ms = 1791349200000                                  # 2026-10-07 04:20 UTC
    old = [[1790553600000, "77", "77", "71", "71.30", "408.97", 1790639999999]]   # 2026-09-28 candle with volume
    assert abs(last_trade_age_hours(old, now_ms / 1000) - (now_ms - 1790639999999) / 3.6e6) < 1e-6
    assert last_trade_age_hours([[1, "1", "1", "1", "1", "0", 2]], now_ms / 1000) is None    # Ondo: volume always 0
    assert last_trade_age_hours([], now_ms / 1000) is None
    class NoKline(FakeClient):
        def kline(self, *a, **k):
            raise OSError("down")
    s = Guard(NoKline(), to_snapshot).snapshot("NFLXon")
    assert s.last_trade_age_h is None                       # a failed K-line read never fails the check


def test_compare_leaves_a_stale_price_out_of_the_spread():
    from stockguard.adapters.mapping import to_snapshot
    from stockguard.application.service import Guard
    from test_issuers import ThreeIssuers
    class Stale(ThreeIssuers):
        def kline(self, address, interval="1d", limit=10, chain_id="56"):
            if address.lower() == "0xa6a65ac27e76cd53cb790473e4345c46e5ebf961":     # NFLXx: last trade 9 days ago
                return [[0, "1", "1", "1", "71.3", "409", 1790639999999]]
            return []
    rows = Guard(Stale(), to_snapshot, clock=lambda: 1791349200.0).compare("NFLX")
    x = [r for r in rows if r["symbol"] == "NFLXx"][0]
    assert x["stale_price"] is True and x["per_share_spread"] is None and x["verdict"] == "BLOCK"


def test_bstock_without_a_stock_quote_borrows_the_shared_feed():
    from stockguard.adapters.mapping import to_snapshot
    from stockguard.application.service import Guard
    from test_issuers import ThreeIssuers
    r = Guard(ThreeIssuers(), to_snapshot).check("NFLXB", usd_amount=100)
    assert r["reference_source"] in ("NFLXon", "NFLXx") and r["stock_price"] and r["premium"] is not None
    assert any("shared across issuers" in n for n in r["data_notes"] + r["notes"])
