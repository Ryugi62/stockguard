"""Issuers of tokenized US stocks on BNB Chain, keyed by the RWA list `type` filter.

Source: binance-skills-hub, binance-agentic-wallet/SKILL.md — "type=1 = Ondo (…on), type=2 = xStocks-style (…x),
type=3 = bStock (…B)".
"""
ISSUER_BY_TYPE = {1: "Ondo Global Markets", 2: "xStocks", 3: "bStocks"}
LIST_TYPES = (1, 2, 3)


def issuer_name(list_type) -> str:
    try:
        return ISSUER_BY_TYPE.get(int(list_type), "unknown issuer")
    except (TypeError, ValueError):
        return "unknown issuer"
