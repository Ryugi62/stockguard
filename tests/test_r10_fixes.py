"""R10 fixes: own User-Agent, a next step after every verdict (web), doc numbers checked against the data,
skill quotes checked against the skill text."""
import json
import os
import re
import subprocess
import sys

from stockguard.adapters.mapping import to_snapshot
from stockguard.adapters.web import check_response
from stockguard.application.service import Guard
from stockguard.domain.next_step import WALLET_URL, next_step
from tests_support import FakeClient

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
NFLXON = "0x7048f5227b032326cc8dbc53cf3fddd947a2c757"


# --- User-Agent: StockGuard says who it is, and still sends the string the skill asks for ----------------------

def test_rwa_and_audit_user_agent_name_stockguard_first():
    from stockguard.adapters import binance_rwa, token_audit
    for ua, skill in ((binance_rwa.HEADERS["User-Agent"], "binance-web3/1.1 (Skill)"),
                      (token_audit.HEADERS["User-Agent"], "binance-web3/1.4 (Skill)")):
        assert ua.startswith("StockGuard/") and "github.com/Ryugi62/stockguard" in ua
        assert ua.endswith(skill)      # SKILL.md: "Include `User-Agent` header with the following string"


def test_no_user_agent_in_the_code_starts_with_another_client_name():
    pat = re.compile(r'"User-Agent"\s*:\s*(?:"([^"]+)"|([A-Za-z_]+))')
    found = []
    for base in ("src", "scripts"):
        for dp, _, fn in os.walk(os.path.join(ROOT, base)):
            for f in fn:
                if f.endswith(".py"):
                    for lit, name in pat.findall(open(os.path.join(dp, f), encoding="utf-8").read()):
                        found.append((f, lit or name))
    assert found
    for f, value in found:
        assert value.startswith("StockGuard/") or value.isidentifier(), (f, value)


# --- the web page: every verdict ends in one next action -----------------------------------------------------

def test_next_step_for_a_warned_buy_says_how_to_buy_this_amount():
    s = next_step("WARN", "NFLXon", "NFLX", NFLXON, "BUY", 100.0, 0.1491, 1.491)
    assert s["kind"] == "buy" and s["button"] == "Buy $100 of NFLXon"
    assert s["wallet_url"] == WALLET_URL and s["copy"] == NFLXON
    text = " ".join(s["steps"])
    assert NFLXON in text and "0.1491 tokens" in text and "1.491 NFLX shares" in text
    assert s["caution"].startswith("Read the warning") and not s["steps"][0].startswith("Read")   # WARN: said once, above the steps
    assert s["agent_command"] == "stockguard trade NFLXon --usd 100"


def test_next_step_for_a_block_is_wait_with_no_buy_button():
    s = next_step("BLOCK", "SPLITDEMOon", "SPLITDEMO", "0xabc", "BUY", 100.0, 1.0, 1.0)
    assert s["kind"] == "wait" and s["button"] is None and s["wallet_url"] is None
    assert "Don't" in s["title"]


def test_next_step_for_an_allowed_sell():
    s = next_step("ALLOW", "NFLXB", "NFLX", "0xdef", "SELL", 50.0, 0.7, 0.7)
    assert s["kind"] == "sell" and s["button"] == "Sell $50 of NFLXB" and s["caution"] is None


def test_check_response_carries_the_next_step():
    code, body = check_response(Guard(FakeClient(), to_snapshot), {"ticker": "NFLXon", "usd": "100"})
    assert code == 200 and body["next_step"]["kind"] == "buy" and body["next_step"]["copy"] == NFLXON


def test_page_renders_the_next_step_button_copy_and_wallet_link():
    html = open(os.path.join(ROOT, "src", "stockguard", "web", "index.html"), encoding="utf-8").read()
    for needle in ('id="next"', "d.next_step", "navigator.clipboard", "Copy contract address", "wallet_url"):
        assert needle in html, needle


# --- doc numbers: README, docs, skill and site page agree with the raw data ----------------------------------

def test_doc_numbers_match_the_raw_data_and_the_test_count():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "check_numbers.py"), "--json"],
                       capture_output=True, text=True, cwd=ROOT)
    out = json.loads(r.stdout)
    assert r.returncode == 0, out["problems"]
    assert out["facts"]["audit_no_data"] == 663 and out["facts"]["audit_total"] == 675
    assert out["facts"]["ondo_pinned"] == 432 and out["facts"]["ondo_total"] == 458


def test_check_numbers_flags_a_file_that_says_something_else(tmp_path):
    bad = tmp_path / "form.md"
    bad.write_text("the audit returned no data for 662 of the 675 stock tokens; 170 tests")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "check_numbers.py"), "--json", str(bad)],
                       capture_output=True, text=True, cwd=ROOT)
    out = json.loads(r.stdout)
    assert r.returncode == 1 and any("662" in p for p in out["problems"]) and any("170" in p for p in out["problems"])


# --- skill quotes: every quoted sentence in the README is found in the skill text it cites -------------------

def test_quote_checker_finds_matches_and_mismatches(tmp_path):
    hub = tmp_path / "hub" / "skills" / "binance-web3" / "binance-agentic-wallet"
    (hub / "references").mkdir(parents=True)
    (hub / "SKILL.md").write_text("Rules:\n- **Fail-closed**: If the security check API is unreachable, inform the user.\n")
    (hub / "references" / "security.md").write_text("Never silently skip.\n")
    readme = tmp_path / "README.md"
    readme.write_text('| "**Fail-closed**: If the security check API is unreachable, inform the user" (SKILL.md) | x |\n'
                      '| "Always skip quietly" (references/security.md) | y |\n')
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "verify_skill_quotes.py"), str(tmp_path / "hub"),
                        "--readme", str(readme), "--json"], capture_output=True, text=True, cwd=ROOT)
    rows = json.loads(r.stdout)
    assert [x["found"] for x in rows] == [True, False] and r.returncode == 1


def test_recorded_quote_check_has_no_mismatch():
    path = os.path.join(ROOT, "docs", "skill-quotes-check.md")
    text = open(path, encoding="utf-8").read()
    assert "9960c675" in text and "| no |" not in text
    assert len(re.findall(r"\| yes \|", text)) >= 12


def test_page_keeps_agent_and_cli_lines_out_of_the_consumer_view():
    html = open(os.path.join(ROOT, "src", "stockguard", "web", "index.html"), encoding="utf-8").read()
    i = html.index("<details class=\"dev\">")
    assert html.index("If an AI agent placed this order") > i and html.index("Agents: <code>stockguard gate") > i
    assert "plain(" in html and "bp\\)" in html          # the bp detail is cut from the reasons a person reads


# --- R10 judge fixes: error handling ----------------------------------------------------------------------------

def test_requote_for_a_different_amount_stops_before_the_swap():
    import json as _j
    from test_trade import FakeBaw, PRICE, MULT
    from stockguard.adapters.agentic_wallet import AgenticWallet, BawRunner
    from stockguard.application.trade import run_guarded_trade

    class TenX(FakeBaw):
        n = 0
        def __call__(self, argv):
            if " ".join(argv[:2]) == "market-order quote":
                TenX.n += 1
                qty = float(argv[argv.index("--fromTokenQty") + 1])
                k = 1 if TenX.n == 1 else 10                     # the re-quote is for 10x the approved amount
                return _j.dumps({"success": True, "data": {"fromCoinAmount": str(qty * k),
                                                           "toCoinAmount": str(qty * k / PRICE * 0.998 * MULT)}})
            return super().__call__(argv)
    baw = TenX()
    clock = iter([0.0, 100.0])
    r = run_guarded_trade(Guard(FakeClient(), to_snapshot), AgenticWallet(BawRunner(run=baw)), "NFLXon", 5.0,
                          confirm=lambda s: True, sleep=lambda s: None, today="2026-10-04",
                          clock=lambda: next(clock, 100.0))
    assert r["stage"] == "quote" and r["result"].startswith("Re-quote")
    assert not any(c.startswith("market-order swap") for c in baw.calls)


def test_baw_nonzero_exit_without_json_is_an_error_with_the_exit_code(monkeypatch):
    import subprocess as sp
    from stockguard.adapters import agentic_wallet as aw
    monkeypatch.setattr(aw.shutil, "which", lambda b: "/usr/bin/baw")
    monkeypatch.setattr(aw.subprocess, "run", lambda *a, **k: sp.CompletedProcess(a, 3, stdout="", stderr="boom"))
    r = aw.BawRunner()("baw wallet status --json")
    assert r["success"] is False and r["error"]["name"] == "BAW_EXIT_3" and "boom" in r["error"]["message"]


def test_unreadable_balance_is_not_reported_as_zero():
    import json as _j
    import pytest
    from stockguard.adapters.agentic_wallet import AgenticWallet, BawRunner
    w = AgenticWallet(BawRunner(run=lambda argv: _j.dumps({"success": False, "error": {"name": "NOT_LOGGED_IN"}})))
    with pytest.raises(ValueError):
        w.balance("0xabc")


def test_audit_with_an_error_code_is_unavailable():
    from stockguard.adapters.token_audit import parse_audit
    a = parse_audit({"code": "100001", "data": {"hasResult": True, "isSupported": True, "riskLevel": 0}})
    assert a.available is False and "100001" in (a.error or "")


def test_ondo_limit_order_needs_an_explicit_yes():
    from stockguard.application.wallet_gate import gate_swap
    g = gate_swap(Guard(FakeClient(), to_snapshot), "NFLXon", 100.0, side="SELL", trigger_share_price=75.0)
    assert g["action"] == "CONFIRM" and any("Ondo-related tokens cannot be traded" in r for r in g["reasons"])


def test_audit_error_keeps_the_message():
    from stockguard.adapters.token_audit import TokenAuditClient
    def boom(url, payload):
        raise OSError("HTTP 503 from audit")
    a = TokenAuditClient(post=boom).audit("0xabc")
    assert a.available is False and "HTTP 503" in a.error


def test_next_step_tells_a_buyer_without_usdt_where_to_get_it():
    s = next_step("ALLOW", "NFLXB", "NFLX", "0xdef", "BUY", 50.0, 0.7, 0.7)
    assert any("No USDT" in x for x in s["steps"])


def test_risk_badge_bot_box_and_mode_line_are_in_the_developer_view():
    html = open(os.path.join(ROOT, "src", "stockguard", "web", "index.html"), encoding="utf-8").read()
    dev = html[html.index("const devHtml"):html.index("const nextHtml")]
    assert "risk ${d.risk}/100" in dev and "A bot that reads the per-share price" in dev


def test_swap_timeout_is_unknown_not_rejected():
    import subprocess as sp
    from test_trade import FakeBaw
    from stockguard.adapters.agentic_wallet import AgenticWallet, BawRunner
    from stockguard.application.trade import run_guarded_trade
    from stockguard.infrastructure.cli import trade_exit_code

    class Slow(FakeBaw):
        def __call__(self, argv):
            if " ".join(argv[:2]) == "market-order swap":
                raise sp.TimeoutExpired("baw", 60)
            return super().__call__(argv)
    r = run_guarded_trade(Guard(FakeClient(), to_snapshot), AgenticWallet(BawRunner(run=Slow())), "NFLXon", 5.0,
                          confirm=lambda s: True, sleep=lambda s: None, today="2026-10-04")
    assert r["stage"] == "unknown" and "may have been submitted" in r["result"] and "rejected" not in r["result"]
    assert trade_exit_code(r) == 3          # like "still processing": check before retrying


def test_check_with_an_ambiguous_ticker_exits_11_like_gate(capsys):
    from test_issuers import ThreeIssuers
    from stockguard.infrastructure import cli
    import stockguard.infrastructure.cli as c
    orig = c.build_guard
    c.build_guard = lambda offline=False: Guard(ThreeIssuers(), to_snapshot)
    try:
        assert cli.main(["check", "NFLX", "--offline"]) == 11
    finally:
        c.build_guard = orig


def test_page_says_share_exposure_not_shares_owned():
    html = open(os.path.join(ROOT, "src", "stockguard", "web", "index.html"), encoding="utf-8").read()
    assert "shares of exposure" in html
