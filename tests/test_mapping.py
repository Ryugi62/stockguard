import json, os
from stockguard.adapters.mapping import to_snapshot
from stockguard.adapters.binance_rwa import RwaClient, RwaError
from stockguard.domain.guard import check_trade, WARN
import pytest

FX = os.path.join(os.path.dirname(__file__), "..", "fixtures")


def load(name):
    with open(os.path.join(FX, name)) as f:
        return json.load(f)


def test_weekend_nflx_is_derived_and_x10():
    dyn = load("dynamic_nflx_weekend.json")["data"]
    s = to_snapshot(dyn, load("market_status_weekend.json")["data"])
    assert s.multiplier == 10 and s.reference_derived and s.status == "MARKET_CLOSED"
    v = check_trade(s, "BUY", 1)
    assert v.level == WARN and v.share_equivalent == 10 and v.premium is None


def test_paused_split_from_doc_shape():
    dyn = {"symbol": "XYZon", "ticker": "XYZ", "tokenInfo": {"price": "50", "sharesMultiplier": "1"},
           "stockInfo": {"price": "49.5"}, "statusInfo": {"marketStatus": "regular", "reasonCode": "ASSET_PAUSED",
                                                           "reasonMsg": "stock_split"}}
    assert check_trade(to_snapshot(dyn), "BUY", 1).level == "BLOCK"


def test_client_raises_on_api_error_and_retries_on_network():
    calls = []

    def bad(url):
        calls.append(url)
        raise OSError("boom")
    c = RwaClient(http_get=bad, retries=3, sleep=lambda s: None)
    with pytest.raises(RwaError):
        c.market_status()
    assert len(calls) == 3
    c2 = RwaClient(http_get=lambda u: {"code": "100002", "success": False, "message": "x"}, sleep=lambda s: None)
    with pytest.raises(RwaError):
        c2.market_status()


def test_list_filters_chain():
    c = RwaClient(http_get=lambda u: load("list_sample.json"), sleep=lambda s: None)
    toks = c.list_tokens("56")
    assert {t["symbol"] for t in toks} >= {"NFLXon", "AAPLon"}


def test_near_copy_outside_regular_hours_is_not_an_independent_quote():
    from stockguard.adapters.mapping import to_snapshot
    d = {"tokenInfo": {"price": "692.1988", "sharesMultiplier": "10"}, "stockInfo": {"price": "69.219761"},
         "statusInfo": {"marketStatus": "overnight", "reasonCode": "TRADING"}}
    assert to_snapshot(d).reference_derived is True                    # 1.7e-6 apart, overnight (2026-10-07)
    reg = dict(d, statusInfo={"marketStatus": "regular", "reasonCode": "TRADING"})
    assert to_snapshot(reg).reference_derived is False                 # regular session: a real 0.0002% premium
    far = dict(d, stockInfo={"price": "68.0"})
    assert to_snapshot(far).reference_derived is False                 # 1.8% apart: independent
