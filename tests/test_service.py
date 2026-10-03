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
