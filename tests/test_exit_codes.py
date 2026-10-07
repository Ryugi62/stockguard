"""CLI exit codes let scripts and agents branch without parsing JSON (README "Exit codes")."""
from stockguard.infrastructure.cli import EXIT, main, trade_exit_code


def test_gate_exit_codes_follow_the_action(capsys):
    assert main(["gate", "NFLXx", "--usd", "100", "--offline"]) == EXIT["REFUSE"] == 12
    assert main(["gate", "KLACon", "--usd", "1000", "--offline"]) == EXIT["CONFIRM"] == 10
    assert main(["gate", "NFLX", "--usd", "100", "--offline"]) == EXIT["ASK"] == 11
    assert main(["gate", "NFLXon", "--usd", "200", "--side", "SELL", "--trigger-share-price", "75", "--offline"]) == 0


def test_check_exit_codes_follow_the_verdict(capsys):
    assert main(["check", "NFLXon", "--usd", "1000", "--offline"]) == EXIT["WARN"] == 10


def test_trade_exit_codes():
    assert trade_exit_code({"stage": "done", "status": "FINISHED"}) == 0
    assert trade_exit_code({"stage": "done", "status": "LIMIT_PLACED"}) == 0
    assert trade_exit_code({"stage": "pending", "status": "PENDING"}) == 3
    assert trade_exit_code({"stage": "preflight", "result": "not ready"}) == 1
    assert trade_exit_code({"stage": "done", "status": "FAILED"}) == 1


def test_text_output_is_short_and_human(capsys):
    main(["check", "NFLXon", "--usd", "1000", "--offline", "--text"])
    out = capsys.readouterr().out
    assert out.startswith("NFLXon (Ondo Global Markets): WARN") and "--json for the full answer" in out
    main(["gate", "NFLXon", "--usd", "100", "--offline", "--json"])
    assert capsys.readouterr().out.lstrip().startswith("{")
