"""Agentic Wallet pre-trade gate. Rules quote binance-skills-hub/skills/binance-web3/binance-agentic-wallet:
- SKILL.md "Fail-closed: If the security check API is unreachable, inform the user and require acknowledgment"
- SKILL.md "No address hallucination: Never fabricate a contract address"
- SKILL.md "do not default to Ondo. Ask the user which provider they mean"
- references/wallet-setting.md `quotaLeft`, `tradeAllTokens`, `abnormalTxnHandling: AutoReject | NeedConfirmation`
- references/market-order.md `baw market-order quote|swap --fromTokenQty --fromToken --toToken --binanceChainId ... --json`
"""
import json, os

from stockguard.adapters.agentic_wallet import USDT_BSC, commands, parse_wallet_settings
from stockguard.adapters.mapping import to_snapshot
from stockguard.application.service import Guard
from stockguard.application.wallet_gate import gate_swap
from stockguard.domain.guard import ALLOW, BLOCK, WARN, Verdict
from stockguard.domain.wallet_gate import ASK, CONFIRM, PROCEED, REFUSE, WalletSettings, decide
from tests_support import FakeClient
from test_issuers import ThreeIssuers, NFLX_ON


def v(level, reasons=("r",), risk=0):
    return Verdict(level, list(reasons), risk=risk)


def test_block_is_refused_like_autoreject():
    d = decide(v(BLOCK, ["Paused for a stock split"], 100), 500.0)
    assert d.action == REFUSE and d.approved_usd == 0 and "Paused for a stock split" in d.reasons


def test_warn_needs_explicit_confirmation_even_if_user_skipped_confirmations():
    d = decide(v(WARN, ["Earnings release"], 45), 500.0)
    assert d.action == CONFIRM and d.confirmation_required and d.approved_usd == 500.0


def test_allow_proceeds_with_the_skills_normal_confirmation():
    d = decide(v(ALLOW), 500.0)
    assert d.action == PROCEED and d.approved_usd == 500.0


def test_order_above_daily_quota_is_reduced_to_quota():
    d = decide(v(ALLOW), 500.0, WalletSettings(quota_left=120.0))
    assert d.action == CONFIRM and d.approved_usd == 120.0 and any("daily limit" in r for r in d.reasons)


def test_quota_used_up_is_refused():
    d = decide(v(ALLOW), 50.0, WalletSettings(quota_left=0.0))
    assert d.action == REFUSE and d.approved_usd == 0


def test_allow_list_only_wallet_gets_a_note():
    d = decide(v(ALLOW), 50.0, WalletSettings(trade_all_tokens=False))
    assert any("allowed list" in n for n in d.notes)


def test_parse_real_wallet_settings_shape():
    raw = {"success": True, "data": {"dailyLimit": 50000, "quotaLeft": 49880, "abnormalTxnHandling": "AutoReject",
                                     "tradeAllTokens": False}}
    s = parse_wallet_settings(raw)
    assert s.quota_left == 49880 and s.trade_all_tokens is False and s.abnormal_handling == "AutoReject"


def test_gate_end_to_end_emits_exact_baw_commands_for_a_buy():
    out = gate_swap(Guard(FakeClient(), to_snapshot), "NFLXon", 100.0)
    assert out["action"] == PROCEED and any("Heads-up" in n for n in out["notes"])   # weekend, risk 30 < 40
    cmds = commands(out)
    assert cmds[0] == (f"baw market-order quote --fromTokenQty 100.00 --fromToken {USDT_BSC} --toToken {NFLX_ON} "
                       f"--binanceChainId 56 --json")
    assert cmds[1].startswith("baw market-order swap --fromTokenQty 100.00") and cmds[1].endswith("--json")
    assert cmds[2].startswith("baw market-order list --orderId")


def test_refused_trade_emits_no_swap_command():
    assert commands({"action": REFUSE, "side": "BUY", "approved_usd": 0}) == []


def test_bare_ticker_with_several_issuers_asks_which_token():
    out = gate_swap(Guard(ThreeIssuers(), to_snapshot), "NFLX", 100.0)
    assert out["action"] == ASK and {c["symbol"] for c in out["choices"]} == {"NFLXon", "NFLXx", "NFLXB"}
    assert commands(out) == []


def test_unreachable_market_data_fails_closed():
    class Down(FakeClient):
        def dynamic(self, address, chain_id="56"):
            raise RuntimeError("timeout")
    out = gate_swap(Guard(Down(), to_snapshot), "NFLXon", 100.0)
    assert out["action"] == REFUSE and any("fail-closed" in r.lower() for r in out["reasons"])


def test_contract_address_not_in_the_official_list_is_refused():
    out = gate_swap(Guard(FakeClient(), to_snapshot), "0x000000000000000000000000000000000000dead", 100.0)
    assert out["action"] == REFUSE and any("not in the RWA token list" in r for r in out["reasons"])


def test_sell_swaps_token_into_usdt_by_token_quantity():
    out = gate_swap(Guard(FakeClient(), to_snapshot), "NFLXon", 100.0, side="SELL")
    swap = commands(out)[1]
    assert f"--fromToken {NFLX_ON} --toToken {USDT_BSC}" in swap and "--fromTokenQty 0.149114" in swap   # rounded down: never sell more than requested


def test_low_risk_warn_proceeds_with_heads_up_notes_not_confirm_fatigue():
    d = decide(v(WARN, ["US market is closed"], 15), 500.0)
    assert d.action == PROCEED and any("US market is closed" in n for n in d.notes)


def test_tiny_order_is_refused_and_quota_rounds_down():
    assert decide(v(ALLOW), 0.001).action == REFUSE
    assert decide(v(ALLOW), 500.0, WalletSettings(quota_left=120.009)).approved_usd == 120.0


def test_token_list_down_also_fails_closed():
    class ListDown(FakeClient):
        def list_tokens(self, chain_id="56"):
            raise RuntimeError("503")
    out = gate_swap(Guard(ListDown(), to_snapshot), "NFLXon", 100.0)
    assert out["action"] == REFUSE and any("fail-closed" in r for r in out["reasons"])


def test_mcp_gate_survives_upstream_failure():
    import io
    from stockguard.adapters.mcp_stdio import run
    class ListDown(FakeClient):
        def list_tokens(self, chain_id="56"):
            raise RuntimeError("503")
    fin = io.StringIO(json.dumps({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {
        "name": "guard_agentic_wallet_swap", "arguments": {"ticker": "NFLXon", "usd_amount": 10}}}) + "\n")
    fout = io.StringIO()
    run(Guard(ListDown(), to_snapshot), fin, fout)
    res = json.loads(fout.getvalue())
    assert json.loads(res["result"]["content"][0]["text"])["action"] == REFUSE
