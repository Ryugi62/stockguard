"""Gate depth: token audit (query-token-audit skill), quote check, limit-order trigger in per-token units, slippage,
BNB payment, stale wallet settings. Skill texts:
- security.md §1: audit every non-trusted toToken; "hasResult: false OR isSupported: false" -> "Security audit data is
  not available for this token on this chain." + explicit acknowledgment; API failure -> "Token security audit is
  temporarily unavailable." + acknowledgment. query-token-audit: riskLevel 5 = block, 4 = avoid; tax >10% critical.
- limit-order.md: `--triggerPrice` is the USD price of the TOKEN; SKILL.md step 7: never fall back to a market order.
- SKILL.md step 4: "For trades without explicit slippage, disclose the default ("auto")".
"""
import pytest

from stockguard.adapters.agentic_wallet import BSC_STABLES, commands, parse_wallet_settings
from stockguard.adapters.mapping import to_snapshot
from stockguard.adapters.token_audit import parse_audit
from stockguard.application.service import Guard
from stockguard.application.wallet_gate import gate_swap
from stockguard.domain.guard import ALLOW, Verdict
from stockguard.domain.wallet_gate import (CONFIRM, PROCEED, REFUSE, AuditResult, QuoteCheck, check_quote, decide,
                                           per_token_trigger)
from tests_support import FakeClient
from test_issuers import NFLX_ON


def ok():
    return Verdict(ALLOW, ["fine"])


def test_audit_unavailable_needs_acknowledgment_with_the_skills_words():
    d = decide(ok(), 100, audit=AuditResult(available=False))
    assert d.action == CONFIRM and d.confirmation_required
    assert "Security audit data is not available for this token on this chain." in d.reasons


def test_audit_api_down_needs_acknowledgment():
    d = decide(ok(), 100, audit=AuditResult(available=False, error="timeout"))
    assert d.action == CONFIRM and "Token security audit is temporarily unavailable." in d.reasons


def test_audit_risk_levels_follow_the_skill_table():
    assert decide(ok(), 100, audit=AuditResult(True, risk_level=5)).action == REFUSE
    d4 = decide(ok(), 100, audit=AuditResult(True, risk_level=4, hits=("Honeypot",)))
    assert d4.action == REFUSE and any("Honeypot" in r for r in d4.reasons)       # 4 = "Avoid trading"
    assert decide(ok(), 100, audit=AuditResult(True, risk_level=3)).action == CONFIRM  # 2-3 = "Exercise caution"
    assert decide(ok(), 100, audit=AuditResult(True, risk_level=1)).action == PROCEED


def test_audit_tax_above_10_percent_refuses():
    assert decide(ok(), 100, audit=AuditResult(True, risk_level=2, buy_tax=12.0)).action == REFUSE


def test_parse_real_audit_response_for_a_stock_token():
    raw = {"code": "000000", "data": {"hasResult": False, "isSupported": False, "riskLevel": -1, "riskItems": []}}
    a = parse_audit(raw)
    assert a.available is False and a.risk_level is None


def test_quote_far_above_the_token_price_is_refused():
    # BUY: paid 100 USDT, received 0.1 token -> effective 1000/token vs API token price 670.62
    q = check_quote("BUY", from_amount=100, to_amount=0.1, token_price=670.62)
    assert isinstance(q, QuoteCheck) and q.level == REFUSE and q.gap > 0.4
    assert check_quote("BUY", 100, 100 / 672.0, 670.62).level == PROCEED          # 0.2% worse: fine
    assert check_quote("BUY", 100, 100 / 690.0, 670.62).level == CONFIRM          # 2.9% worse: confirm
    assert check_quote("SELL", from_amount=0.1, to_amount=60.0, token_price=670.62).level == REFUSE  # 10.5% below


def test_limit_trigger_is_converted_from_per_share_to_per_token():
    t = per_token_trigger(share_price=70.0, multiplier=10.0, multiplier_conflict=False)
    assert t == 700.0
    with pytest.raises(ValueError):
        per_token_trigger(70.0, 10.0, multiplier_conflict=True)


def test_gate_limit_order_emits_per_token_trigger_and_no_fallback():
    out = gate_swap(Guard(FakeClient(), to_snapshot), "NFLXon", 100.0, trigger_share_price=60.0)
    cmds = commands(out)
    assert cmds[0].startswith("baw limit-order buy --triggerPrice 600.00 --fromTokenQty 100.00")
    assert any("do not fall back to a market order" in n for n in out["notes"])


def test_slippage_is_passed_or_disclosed():
    out = gate_swap(Guard(FakeClient(), to_snapshot), "NFLXon", 100.0, slippage=1.0)
    assert "--slippage 1" in commands(out)[1]
    out2 = gate_swap(Guard(FakeClient(), to_snapshot), "NFLXon", 100.0)    # default: capped at 1%, disclosed
    assert "--slippage 1" in commands(out2)[1] and any('instead of the wallet\'s "auto"' in n for n in out2["notes"])


def test_pay_with_bnb_uses_native_address_and_converts_dollars_to_bnb():
    out = gate_swap(Guard(FakeClient(), to_snapshot), "NFLXon", 100.0, pay_with="BNB", pay_price=600.0)
    assert f"--fromTokenQty 0.166666 --fromToken {BSC_STABLES['BNB']}" in commands(out)[0]
    with pytest.raises(ValueError):          # BNB is not a dollar: its price must be given (wallet balance shows it)
        gate_swap(Guard(FakeClient(), to_snapshot), "NFLXon", 100.0, pay_with="BNB")


def test_stale_wallet_settings_are_flagged():
    s = parse_wallet_settings({"data": {"quotaLeft": 100, "quotaDate": "2026-04-03"}})
    out = gate_swap(Guard(FakeClient(), to_snapshot), "NFLXon", 50.0, settings=s, today="2026-10-04")
    assert any("2026-04-03" in n for n in out["notes"])


def test_gate_with_audit_port_calls_it_with_the_contract():
    seen = []
    class Audit:
        def audit(self, address):
            seen.append(address); return AuditResult(available=False)
    out = gate_swap(Guard(FakeClient(), to_snapshot), "NFLXon", 100.0, auditor=Audit())
    assert seen == [NFLX_ON] and out["audit"]["available"] is False


class _Audit:
    def __init__(self, res):
        self.res, self.calls = res, []
    def audit(self, address):
        self.calls.append(address); return self.res


def test_sell_into_usdt_skips_the_audit_because_the_target_is_trusted():
    a = _Audit(AuditResult(available=False))
    out = gate_swap(Guard(FakeClient(), to_snapshot), "NFLXon", 100.0, side="SELL", auditor=a)
    assert a.calls == [] and out["action"] == PROCEED and any("trusted" in n for n in out["notes"])


def test_skipped_audit_is_disclosed_and_needs_acknowledgment():
    from stockguard.adapters.token_audit import SkippedAudit
    out = gate_swap(Guard(FakeClient(), to_snapshot), "NFLXon", 100.0, auditor=SkippedAudit())
    assert out["action"] == CONFIRM and any("skipped" in r.lower() for r in out["reasons"])


def test_available_audit_carries_the_skills_disclaimer():
    out = gate_swap(Guard(FakeClient(), to_snapshot), "NFLXon", 100.0, auditor=_Audit(AuditResult(True, risk_level=1)))
    assert any('LOW risk does NOT mean "safe."' in n for n in out["notes"])


def test_sell_can_be_sized_in_tokens():
    out = gate_swap(Guard(FakeClient(), to_snapshot), "NFLXon", None, side="SELL", token_qty=0.25)
    # 0.25 tokens of a 10-share token = 2.5 shares, the unit baw 1.10.0 expects for a market SELL (F17)
    assert abs(out["approved_token_qty"] - 0.25) < 1e-12 and "--fromTokenQty 2.500000" in commands(out)[1]


def test_limit_follow_up_uses_strategy_id():
    out = gate_swap(Guard(FakeClient(), to_snapshot), "NFLXon", 100.0, trigger_share_price=60.0)
    assert "baw limit-order list --strategyId <strategyId" in commands(out)[1]


def test_limit_trigger_already_met_is_flagged():
    # NFLXon trades at 670.62 per token. BUY trigger $75/share = $750/token is above it -> fires immediately
    out = gate_swap(Guard(FakeClient(), to_snapshot), "NFLXon", 100.0, trigger_share_price=75.0)
    assert out["action"] == CONFIRM and any("already met" in r for r in out["reasons"])


def test_limit_sell_by_dollars_is_sized_at_the_trigger_price():
    out = gate_swap(Guard(FakeClient(), to_snapshot), "NFLXon", 150.0, side="SELL", trigger_share_price=75.0)
    assert abs(out["approved_token_qty"] - 150.0 / 750.0) < 1e-9


def test_audit_confirm_puts_the_stock_warnings_in_the_reasons():
    out = gate_swap(Guard(FakeClient(), to_snapshot), "NFLXon", 100.0, auditor=_Audit(AuditResult(available=False)))
    assert any("closed" in r for r in out["reasons"]) and AUDIT_UNAVAILABLE_TEXT in out["reasons"]


AUDIT_UNAVAILABLE_TEXT = "Security audit data is not available for this token on this chain."
