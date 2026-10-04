"""Same ticker, three issuers (Ondo `…on`, xStocks `…x`, bStocks `…B`) — real responses recorded 2026-10-04 (Sunday).

Agentic Wallet skill (binance-skills-hub, binance-agentic-wallet/SKILL.md "Common Token Addresses"):
"The same ticker often exists under more than one provider ... Bare ticker with no suffix — do not default to Ondo.
Ask the user which provider they mean".
"""
import json, os
import pytest

from stockguard.adapters.binance_rwa import RwaClient
from stockguard.adapters.mapping import to_snapshot
from stockguard.application.service import AmbiguousTicker, Guard
from stockguard.domain.guard import BLOCK, WARN, Snapshot, check_trade

FX = os.path.join(os.path.dirname(__file__), "..", "fixtures")
NFLX_ON, NFLX_X, NFLX_B = ("0x7048f5227b032326cc8dbc53cf3fddd947a2c757", "0xa6a65ac27e76cd53cb790473e4345c46e5ebf961",
                           "0xd6829ea836b6fa224d099d40e54b31262f874631")


def load(n):
    with open(os.path.join(FX, n)) as f:
        return json.load(f)["data"]


class ThreeIssuers:
    def list_tokens(self, chain_id="56"):
        return load("list_nflx_three_issuers.json")
    def market_status(self):
        return load("market_status_weekend.json")
    def dynamic(self, address, chain_id="56"):
        return load({NFLX_ON: "dynamic_nflx_weekend.json", NFLX_X: "dynamic_nflxx_weekend.json",
                     NFLX_B: "dynamic_nflxb_weekend.json"}[address])
    def meta(self, address, chain_id="56"):
        return {NFLX_B: {"name": "Netflix (bStocks)",
                         "dailyAttestationReports": "https://www.binance.com/proof-of-collateral/bstocks"}}.get(address, {})


def test_list_tokens_reads_all_three_issuer_types():
    seen = []
    def http_get(url):
        seen.append(url)
        t = url.split("type=")[1]
        return {"code": "000000", "data": [{"chainId": "56", "symbol": "X" + t, "type": int(t)},
                                           {"chainId": "1", "symbol": "ETH" + t, "type": int(t)}]}
    toks = RwaClient(http_get=http_get).list_tokens("56")
    assert sorted(u.split("type=")[1] for u in seen) == ["1", "2", "3"]
    assert [t["symbol"] for t in toks] == ["X1", "X2", "X3"]


def test_bare_ticker_with_three_issuers_is_ambiguous_and_lists_choices():
    with pytest.raises(AmbiguousTicker) as e:
        Guard(ThreeIssuers(), to_snapshot).resolve("NFLX")
    c = {x["symbol"]: x for x in e.value.candidates}
    assert set(c) == {"NFLXon", "NFLXx", "NFLXB"}
    assert c["NFLXon"]["issuer"] == "Ondo Global Markets" and c["NFLXon"]["multiplier"] == 10
    assert c["NFLXx"]["issuer"] == "xStocks" and c["NFLXB"]["issuer"] == "bStocks"


def test_explicit_symbol_resolves_without_asking():
    g = Guard(ThreeIssuers(), to_snapshot)
    assert g.resolve("nflxb")["contractAddress"] == NFLX_B
    assert g.resolve("NFLXon")["contractAddress"] == NFLX_ON


def test_xstocks_multiplier_conflict_is_flagged_not_trusted():
    # list/ai says multiplier 1, dynamic/ai says sharesMultiplier 10, token price ~1 share (71.30 vs stock 67.06)
    r = Guard(ThreeIssuers(), to_snapshot).check("NFLXx", "BUY", usd_amount=100)
    assert r["verdict"] == WARN
    assert any("two different multipliers" in x for x in r["reasons"])
    assert r["premium"] is None and r["reference_price"] is None   # no -89% phantom discount


def test_compare_shows_every_issuer_side_by_side():
    rows = Guard(ThreeIssuers(), to_snapshot).compare("NFLX", usd_amount=1000)
    assert [x["symbol"] for x in rows] == ["NFLXon", "NFLXx", "NFLXB"]
    assert rows[0]["multiplier"] == 10 and rows[2]["multiplier"] == 1
    assert all(abs(x["usd_amount"] - 1000) < 0.01 for x in rows)


def test_absolute_attestation_url_is_not_prefixed():
    r = Guard(ThreeIssuers(), to_snapshot).check("NFLXB", usd_amount=100)
    assert r["attestation_daily"] == "https://www.binance.com/proof-of-collateral/bstocks"


def test_missing_token_price_blocks():
    s = Snapshot(symbol="ABBVx", ticker="ABBV", token_price=0.0, stock_price=263.5, multiplier=1.02,
                 session="", status="TRADING")
    v = check_trade(s, "BUY", 1)
    assert v.level == BLOCK and v.premium is None and any("No token price" in r for r in v.reasons)


def test_null_market_status_is_reported_as_data_issue():
    from stockguard.domain.guard import find_inconsistencies
    s = to_snapshot(load("dynamic_nflxb_weekend.json"), load("market_status_weekend.json"))
    assert any("marketStatus is null" in x for x in find_inconsistencies(s))
