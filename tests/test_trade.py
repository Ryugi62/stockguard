"""`stockguard trade`: preflight -> gate -> wallet quote re-check -> explicit yes -> swap -> poll to FINISHED/FAILED.
Fake `baw` runner only — no wallet is touched in tests."""
from stockguard.adapters.agentic_wallet import AgenticWallet, BawRunner
from stockguard.adapters.mapping import to_snapshot
from stockguard.application.service import Guard
from stockguard.application.trade import run_guarded_trade
from tests_support import FakeClient

PRICE = 670.62353   # NFLXon fixture token price


class FakeBaw:
    def __init__(self, status="CONNECTED", quote_tokens=None, final="FINISHED", quota=1000):
        self.calls, self.status, self.final, self.quota = [], status, final, quota
        self.quote_tokens = quote_tokens
        self.polls = 0

    def __call__(self, argv):
        import json
        cmd = " ".join(argv[:2])
        self.calls.append(" ".join(argv))
        if cmd == "wallet status":
            return json.dumps({"success": True, "data": {"status": self.status}})
        if cmd == "wallet settings":
            return json.dumps({"success": True, "data": {"quotaLeft": self.quota, "tradeAllTokens": True,
                                                         "quotaDate": "2026-10-04"}})
        if cmd == "market-order quote":
            qty = float(argv[argv.index("--fromTokenQty") + 1])
            to = self.quote_tokens if self.quote_tokens is not None else qty / PRICE * 0.998
            return json.dumps({"success": True, "data": {"fromCoinAmount": str(qty), "toCoinAmount": str(to)}})
        if cmd == "market-order swap":
            return json.dumps({"success": True, "data": {"orderId": "42"}})
        if cmd == "market-order list":
            self.polls += 1
            st = "PENDING" if self.polls < 2 else self.final
            return json.dumps({"success": True, "data": {"list": [{"orderId": "42", "status": st,
                                                                    "txHash": "0xabc" if st == "FINISHED" else None}]}})
        return json.dumps({"success": False})


def trade(fake, confirm=True, **kw):
    return run_guarded_trade(Guard(FakeClient(), to_snapshot), AgenticWallet(BawRunner(run=fake)), "NFLXon", kw.pop("usd", 5.0),
                             confirm=lambda summary: confirm, sleep=lambda s: None, today="2026-10-04", **kw)


def test_full_path_polls_to_finished_and_returns_tx():
    fake = FakeBaw()
    r = trade(fake)
    assert r["stage"] == "done" and r["status"] == "FINISHED" and r["tx_hash"] == "0xabc"
    order = [c.split(" --")[0] for c in fake.calls]
    assert order[:2] == ["wallet status", "cli-check"] and "wallet settings" in order
    assert order.index("market-order quote") < order.index("market-order swap")
    assert order[-1].startswith("market-order list")


def test_not_signed_in_stops_before_anything():
    fake = FakeBaw(status="UNCONNECTED")
    r = trade(fake)
    assert r["stage"] == "preflight" and len(fake.calls) == 1


def test_bad_quote_stops_before_swap():
    fake = FakeBaw(quote_tokens=5.0 / (PRICE * 1.2))     # 20% worse than the token price
    r = trade(fake)
    assert r["stage"] == "quote" and not any("swap" in c for c in fake.calls)


def test_no_explicit_yes_means_no_swap():
    fake = FakeBaw()
    r = trade(fake, confirm=False)
    assert r["stage"] == "confirm" and not any("market-order swap" in c for c in fake.calls)


def test_failed_order_is_reported_as_failed():
    r = trade(FakeBaw(final="FAILED"))
    assert r["stage"] == "done" and r["status"] == "FAILED" and r["tx_hash"] is None


def test_wallet_quota_from_settings_cuts_the_order():
    fake = FakeBaw(quota=3)
    r = trade(fake, usd=5.0)
    assert r["gate"]["approved_usd"] == 3.0 and any("--fromTokenQty 3.00" in c for c in fake.calls)


class FakeBawLimit(FakeBaw):
    def __init__(self, accept=True, usdt=100.0, token=10.0, **kw):
        super().__init__(**kw); self.accept, self.usdt, self.token = accept, usdt, token

    def __call__(self, argv):
        import json
        cmd = " ".join(argv[:2])
        if cmd in ("limit-order buy", "limit-order sell"):
            self.calls.append(" ".join(argv))
            if self.accept:
                return json.dumps({"success": True, "data": {"strategyId": "77"}})
            return json.dumps({"success": False, "error": {"message": "Ondo-related tokens cannot be traded"}})
        if cmd == "wallet balance":
            self.calls.append(" ".join(argv))
            if "--symbol" in argv:
                return json.dumps({"success": True, "data": [{"symbol": "USDT", "balance": str(self.usdt), "price": "1.0"}]})
            return json.dumps({"success": True, "data": [{"symbol": "NFLXon", "balance": str(self.token), "price": "670"}]})
        if cmd == "cli-check":
            self.calls.append(" ".join(argv))
            return json.dumps({"success": True, "data": {"currentCliVersion": "1.10.0", "needUpdateCli": False}})
        return super().__call__(argv)


def test_rejected_limit_order_stops_without_market_fallback():
    fake = FakeBawLimit(accept=False)
    r = trade(fake, trigger_share_price=60.0)
    assert r["stage"] == "limit" and not any("market-order swap" in c for c in fake.calls)


def test_placed_limit_order_is_reported_as_placed_not_filled():
    r = trade(FakeBawLimit(), trigger_share_price=60.0)
    assert r["status"] == "LIMIT_PLACED" and r["strategy_id"] == "77" and "not filled" in r["result"]


def test_sell_more_than_held_stops():
    r = trade(FakeBawLimit(token=0.001), side="SELL")
    assert r["stage"] == "balance"


def test_buy_without_enough_usdt_stops():
    r = trade(FakeBawLimit(usdt=1.0), usd=5.0)
    assert r["stage"] == "balance" and "USDT" in r["result"]


def test_poll_timeout_is_reported_as_still_processing():
    fake = FakeBaw(final="PENDING")
    r = run_guarded_trade(Guard(FakeClient(), to_snapshot), AgenticWallet(BawRunner(run=fake)), "NFLXon", 5.0,
                          confirm=lambda s: True, sleep=lambda s: None, max_polls=3)
    assert r["stage"] == "pending" and r["status"] == "PENDING" and "still processing" in r["result"]


def test_sell_into_bnb_quote_is_compared_in_dollars():
    import json
    class SellBnb(FakeBawLimit):
        def __call__(self, argv):
            cmd = " ".join(argv[:2])
            if cmd == "wallet balance" and "--symbol" in argv:
                self.calls.append(" ".join(argv))
                return json.dumps({"success": True, "data": [{"symbol": "BNB", "balance": "1", "price": "600"}]})
            if cmd == "market-order quote":
                qty = float(argv[argv.index("--fromTokenQty") + 1])
                return json.dumps({"success": True, "data": {"fromCoinAmount": str(qty),
                                                             "toCoinAmount": str(qty * PRICE / 600 * 0.998)}})
            return super().__call__(argv)
    r = trade(SellBnb(), side="SELL", pay_with="BNB")
    assert r["stage"] == "done", r.get("result")
