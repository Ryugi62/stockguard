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
    assert s["steps"][0].startswith("Read the warning")          # WARN: the warning comes before the buy steps
    assert s["agent_command"] == "stockguard trade NFLXon --usd 100"


def test_next_step_for_a_block_is_wait_with_no_buy_button():
    s = next_step("BLOCK", "SPLITDEMOon", "SPLITDEMO", "0xabc", "BUY", 100.0, 1.0, 1.0)
    assert s["kind"] == "wait" and s["button"] is None and s["wallet_url"] is None
    assert "Don't" in s["title"]


def test_next_step_for_an_allowed_sell():
    s = next_step("ALLOW", "NFLXB", "NFLX", "0xdef", "SELL", 50.0, 0.7, 0.7)
    assert s["kind"] == "sell" and s["button"] == "Sell $50 of NFLXB" and not s["steps"][0].startswith("Read")


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
