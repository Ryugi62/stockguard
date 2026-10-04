import pytest
from stockguard.domain.guard import Snapshot, check_trade, find_inconsistencies, ALLOW, WARN, BLOCK


def snap(**kw):
    base = dict(symbol="AAPLon", ticker="AAPL", token_price=100.0, stock_price=100.0, multiplier=1.0,
                session="regular", status="TRADING", reason=None)
    base.update(kw)
    return Snapshot(**base)


def test_normal_trading_allows():
    v = check_trade(snap(), "BUY", 1)
    assert v.level == ALLOW


def test_market_closed_warns():
    v = check_trade(snap(session="closed", status="MARKET_CLOSED"), "BUY", 1)
    assert v.level == WARN and any("closed" in r for r in v.reasons)


def test_market_paused_blocks():
    assert check_trade(snap(status="MARKET_PAUSED"), "BUY", 1).level == BLOCK


def test_dividend_pause_blocks():
    v = check_trade(snap(status="ASSET_PAUSED", reason="cash_dividend"), "BUY", 1)
    assert v.level == BLOCK and "dividend" in v.reasons[0]


def test_split_pause_blocks():
    v = check_trade(snap(status="ASSET_PAUSED", reason="stock_split"), "SELL", 1)
    assert v.level == BLOCK and "split" in v.reasons[0]


def test_earnings_limited_warns():
    v = check_trade(snap(status="ASSET_LIMITED", reason="earnings"), "BUY", 1)
    assert v.level == WARN and "Earnings" in v.reasons[0]


def test_premium_above_threshold_warns_on_buy():
    v = check_trade(snap(token_price=102.5, session="closed", status="MARKET_CLOSED"), "BUY", 1, premium_threshold=0.01)
    assert v.level == WARN and any("2.5% above" in r for r in v.reasons)


def test_discount_warns_on_sell_only():
    s = snap(token_price=97.0)
    assert check_trade(s, "SELL", 1).level == WARN
    assert check_trade(s, "BUY", 1).level == ALLOW


def test_multiplier_share_equivalent_and_reference():
    s = snap(token_price=1000.0, stock_price=100.0, multiplier=10.0)
    v = check_trade(s, "BUY", 1)
    assert v.share_equivalent == 10
    assert v.reference_price == 1000.0
    assert abs(v.premium) < 1e-9
    assert any("1 token = 10 shares" in r for r in v.reasons)


def test_block_dominates_warn():
    v = check_trade(snap(status="ASSET_PAUSED", reason="stock_split", multiplier=10.0, token_price=1000), "BUY", 1)
    assert v.level == BLOCK


def test_invalid_inputs():
    with pytest.raises(ValueError):
        check_trade(snap(), "HOLD", 1)
    with pytest.raises(ValueError):
        check_trade(snap(), "BUY", 0)


def test_inconsistency_closed_market_but_trading_asset():
    s = snap(session="offhours", status="TRADING", market_session="closed")
    assert find_inconsistencies(s)


def test_derived_reference_hides_premium_and_warns():
    s = snap(token_price=670.62353, stock_price=67.062353, multiplier=10.0,
             session="closed", status="MARKET_CLOSED", reference_derived=True)
    v = check_trade(s, "BUY", 1)
    assert v.premium is None and v.reference_price is None
    assert any("No independent stock price" in r for r in v.reasons)


def test_fractional_multiplier_reported():
    v = check_trade(snap(token_price=1.0, stock_price=15.0, multiplier=0.066667), "BUY", 3)
    assert abs(v.share_equivalent - 0.200001) < 1e-9
    assert any("1 token = 0.06667 shares" in r for r in v.reasons)


def test_undocumented_session_flagged():
    assert any("undocumented" in x for x in find_inconsistencies(snap(session="offhours")))


def test_offhours_trading_while_market_closed_warns():
    # Real weekend shape (AAPLon 2026-10-03): asset says offhours/TRADING, market-wide says closed.
    s = snap(token_price=334.7, stock_price=333.5, session="offhours", status="TRADING", market_session="closed")
    v = check_trade(s, "BUY", 1)
    assert v.level == WARN and any("Outside regular US hours" in r for r in v.reasons)


def test_premarket_warns_even_if_market_session_unknown():
    assert check_trade(snap(session="premarket"), "BUY", 1).level == WARN


def test_pause_reason_free_text_is_normalised():
    v = check_trade(snap(status="ASSET_PAUSED", reason="Corporate Action"), "BUY", 1)
    assert v.level == BLOCK and v.reasons[0] == "Paused for a corporate action"


def test_large_order_vs_supply_is_a_note_not_a_warning():
    # supply is not liquidity (Ondo mints on demand) — informational only
    v = check_trade(snap(onchain_supply=220.99), "BUY", 15)   # ~6.8% of all tokens
    assert v.level == ALLOW and any("Large order" in n for n in v.notes)
    assert abs(v.order_share_of_supply - 15 / 220.99) < 1e-9


def test_multiplier_is_a_note_when_sized_in_usd():
    v = check_trade(snap(token_price=1000.0, stock_price=100.0, multiplier=10.0), "BUY", 1, sized_in_usd=True)
    assert v.level == ALLOW and any("already handled" in n for n in v.notes)


def test_risk_ranks_x10_closed_above_plain_closed():
    plain = check_trade(snap(session="closed", status="MARKET_CLOSED"), "BUY", 1)
    x10 = check_trade(snap(session="closed", status="MARKET_CLOSED", multiplier=10, token_price=1000), "BUY", 1)
    assert x10.risk > plain.risk > 0
    assert check_trade(snap(status="ASSET_PAUSED", reason="stock_split"), "BUY", 1).risk == 100


def test_market_wide_pause_blocks_even_when_the_asset_reports_no_session():
    # xStocks/bStocks send an empty per-asset session (F9); the market-wide halt must still win
    v = check_trade(snap(session="", status="TRADING", market_session="pause"), "BUY", 1)
    assert v.level == BLOCK


def test_market_wide_overnight_warns_when_asset_session_is_empty():
    v = check_trade(snap(session="", status="TRADING", market_session="overnight"), "BUY", 1)
    assert v.level == WARN and any("Outside regular" in r for r in v.reasons)


def test_empty_session_alone_warns():
    v = check_trade(snap(session="", status="TRADING", market_session="regular"), "BUY", 1)
    assert v.level == WARN and any("no market session" in r for r in v.reasons)


def test_missing_multiplier_warns():
    v = check_trade(snap(multiplier_known=False), "BUY", 1)
    assert v.level == WARN and any("no multiplier" in r for r in v.reasons)


def test_premium_risk_counts_only_beyond_threshold():
    v = check_trade(snap(token_price=101.5), "BUY", 1)      # 1.5% premium, 1% threshold -> 5 points
    assert v.risk == 5


def test_price_far_off_reference_in_either_direction_is_a_data_error_block():
    assert check_trade(snap(token_price=12.0), "BUY", 1).level == BLOCK     # -88% (MRVLx-like)
    assert check_trade(snap(token_price=945.0), "BUY", 1).level == BLOCK    # +845% (GMEx-like)


def test_empty_session_while_market_closed_says_closed_and_no_session():
    v = check_trade(snap(session="", status="TRADING", market_session="closed"), "BUY", 1)
    assert any("closed" in r for r in v.reasons) and any("no market session" in r for r in v.reasons) and v.risk == 25
