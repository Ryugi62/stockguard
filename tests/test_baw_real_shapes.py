"""Real `baw` 1.10.0 output captured without signing in (fixtures/baw/): the adapter must stop at preflight."""
import json, os

from stockguard.adapters.agentic_wallet import AgenticWallet, BawRunner
from stockguard.adapters.mapping import to_snapshot
from stockguard.application.service import Guard
from stockguard.application.trade import run_guarded_trade
from tests_support import FakeClient

FX = os.path.join(os.path.dirname(__file__), "..", "fixtures", "baw")


def raw(name):
    return open(os.path.join(FX, name)).read()


def test_real_unconnected_status_stops_at_preflight():
    calls = []
    def run(argv):
        calls.append(argv)
        return raw("wallet_status_unconnected.json")
    r = run_guarded_trade(Guard(FakeClient(), to_snapshot), AgenticWallet(BawRunner(run=run)), "NFLXon", 5.0,
                          confirm=lambda s: True, sleep=lambda s: None)
    assert r["stage"] == "preflight" and "UNCONNECTED" in r["result"] and len(calls) == 1


def test_real_not_logged_in_quote_is_not_mistaken_for_a_quote():
    from stockguard.adapters.agentic_wallet import parse_quote
    import pytest
    with pytest.raises((KeyError, TypeError, ValueError)):
        parse_quote(json.loads(raw("quote_not_logged_in.json")))


def test_our_flags_exist_in_the_real_cli_help():
    help_text = raw("cli-1.10.0-help.txt")
    for flag in ("--fromTokenQty", "--fromToken", "--toToken", "--binanceChainId", "--slippage", "--triggerPrice"):
        assert flag in help_text
