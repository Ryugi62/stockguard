import json, os
import pytest
from stockguard.application.service import Guard, TickerNotFound

FX = os.path.join(os.path.dirname(__file__), "..", "fixtures")


def load(n):
    with open(os.path.join(FX, n)) as f:
        return json.load(f)["data"]


from tests_support import FakeClient


def test_check_by_ticker_resolves_and_warns():
    r = Guard(FakeClient()).check("nflx", "buy", 2)
    assert r["symbol"] == "NFLXon" and r["verdict"] == "WARN" and r["share_equivalent"] == 20


def test_unknown_ticker():
    with pytest.raises(TickerNotFound):
        Guard(FakeClient()).check("ZZZZ")


def test_scan_records_errors_without_stopping():
    out = list(Guard(FakeClient()).scan(workers=2))
    assert len(out) == 5
    assert sum(1 for r in out if "error" in r) == 4
    nflx = [r for r in out if r.get("symbol") == "NFLXon"][0]
    assert nflx["reference_derived"] is True
