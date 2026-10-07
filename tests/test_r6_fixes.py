"""R6 judge findings, as tests."""
import json
import pytest

from stockguard.adapters.agentic_wallet import AgenticWallet, BawRunner, _floor, commands
from stockguard.adapters.mapping import to_snapshot
from stockguard.application.service import Guard
from stockguard.application.trade import run_guarded_trade
from stockguard.application.wallet_gate import gate_swap
from stockguard.domain.guard import Snapshot, check_trade, WARN
from stockguard.domain.wallet_gate import (AUDIT_DISCLAIMER, AUDIT_UNAVAILABLE, CONFIRM, REFUSE, AuditResult,
                                           CONFIRM_AT, decide)
from stockguard.domain.guard import ALLOW, Verdict
from tests_support import FakeClient
from test_trade import FakeBaw, PRICE


def test_trigger_keeps_significant_digits_for_cheap_tokens():
    g = {"action": "PROCEED", "side": "BUY", "pay_with": "USDT", "approved_usd": 10.0, "contract": "0xabc",
         "trigger_token_price": 0.024667, "approved_token_qty": 1.0}
    assert "--triggerPrice 0.024667 " in commands(g)[0]


def test_limit_orders_only_pay_with_usdt_usdc_or_bnb():
    with pytest.raises(ValueError):
        gate_swap(Guard(FakeClient(), to_snapshot), "NFLXon", 100.0, pay_with="U", trigger_share_price=60.0)


def test_floor_does_not_lose_a_unit_to_float_error():
    assert _floor(0.3) == "0.300000"


def test_audit_risk_level_4_refuses_and_tax_5_to_10_confirms():
    assert decide(Verdict(ALLOW, ["ok"]), 100, audit=AuditResult(True, risk_level=4)).action == REFUSE
    assert decide(Verdict(ALLOW, ["ok"]), 100, audit=AuditResult(True, risk_level=1, buy_tax=7.0)).action == CONFIRM


def test_audit_texts_are_verbatim():
    assert AUDIT_DISCLAIMER.startswith('LOW risk does NOT mean "safe." Audit results are point-in-time snapshots.')
    d = decide(Verdict(ALLOW, ["ok"]), 100, audit=AuditResult(False))
    assert any("verify the contract address and chain" in n for n in d.notes)


def test_multiplier_conflict_without_supply_still_needs_confirmation():
    s = Snapshot(symbol="NFLXx", ticker="NFLX", token_price=71.3, stock_price=67.06, multiplier=10.0, session="regular",
                 status="TRADING", list_multiplier=1.0)
    v = check_trade(s, "BUY", 1)
    assert v.level == WARN and v.risk >= CONFIRM_AT


class ErrBaw(FakeBaw):
    def __call__(self, argv):
        if " ".join(argv[:2]) == "market-order swap":
            self.calls.append(" ".join(argv))
            return json.dumps({"success": False, "error": {"code": 1, "name": "INSUFFICIENT", "message": "Insufficient balance"}})
        return super().__call__(argv)


def test_wallet_errors_are_passed_through_verbatim():
    r = run_guarded_trade(Guard(FakeClient(), to_snapshot), AgenticWallet(BawRunner(run=ErrBaw())), "NFLXon", 5.0,
                          confirm=lambda s: True, sleep=lambda s: None)
    assert r["stage"] == "swap" and "Insufficient balance" in r["result"]


def test_trade_without_slippage_caps_the_swap_at_1_percent():
    fake = FakeBaw()
    run_guarded_trade(Guard(FakeClient(), to_snapshot), AgenticWallet(BawRunner(run=fake)), "NFLXon", 5.0,
                      confirm=lambda s: True, sleep=lambda s: None)
    swap = [c for c in fake.calls if c.startswith("market-order swap")][0]
    assert "--slippage 1" in swap


def test_missing_baw_is_a_preflight_message_not_a_traceback():
    def run(argv):
        raise FileNotFoundError("baw CLI not found")
    r = run_guarded_trade(Guard(FakeClient(), to_snapshot), AgenticWallet(BawRunner(run=run)), "NFLXon", 5.0,
                          confirm=lambda s: True, sleep=lambda s: None)
    assert r["stage"] == "preflight" and "baw CLI not found" in r["result"]


def test_trigger_keeps_six_significant_digits_above_one_dollar():
    from stockguard.adapters.agentic_wallet import _price
    assert _price(10.02613) == "10.0261" and _price(750.0) == "750.00" and _price(0.0246667) == "0.0246667"
    assert _price(1234.5678) == "1234.57"
