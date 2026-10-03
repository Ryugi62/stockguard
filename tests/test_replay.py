from stockguard.application.replay import naive_share_bot


def test_x10_token_overspends_and_fractional_underspends():
    recs = [{"symbol": "NFLXon", "ticker": "NFLX", "token_price": 670.6, "multiplier": 10.0},
            {"symbol": "ENLVon", "ticker": "ENLV", "token_price": 1.0, "multiplier": 0.066667},
            {"symbol": "AAPLon", "ticker": "AAPL", "token_price": 334.7, "multiplier": 1.0034}]
    out = {r["symbol"]: r for r in naive_share_bot(recs, 1000)}
    assert out["NFLXon"]["real_usd"] == 10000.0 and out["NFLXon"]["error_usd"] == 9000.0
    assert abs(out["ENLVon"]["real_usd"] - 66.67) < 0.01
    assert "AAPLon" not in out
