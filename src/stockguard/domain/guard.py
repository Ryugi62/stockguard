"""StockGuard domain — pure rules, no I/O (SPEC.md §Ubiquitous language)."""
import math
from dataclasses import dataclass, field
from typing import List, Optional

ALLOW, WARN, BLOCK = "ALLOW", "WARN", "BLOCK"
DOCUMENTED_SESSIONS = {"premarket", "regular", "postmarket", "overnight", "closed", "pause"}
OUTSIDE_REGULAR = {"premarket", "postmarket", "overnight", "offhours"}
_RANK = {ALLOW: 0, WARN: 1, BLOCK: 2}
MULTIPLIER_CONFLICT = 0.01   # list vs price-feed multiplier differing by more than 1% is a conflict
DATA_ERROR_GAP = 0.25        # a token more than 25% away from its reference price is treated as bad data
STALE_WARN_H, STALE_BLOCK_H = 72.0, 168.0   # last trade-derived K-line candle older than 3 days / 7 days

PAUSE_REASONS = {
    "cash_dividend": "Paused for a cash dividend",
    "stock_dividend": "Paused for a stock dividend",
    "stock_split": "Paused for a stock split",
    "merger": "Paused for a merger",
    "maintenance": "Paused for maintenance",
    "acquisition": "Paused for an acquisition",
    "spinoff": "Paused for a spinoff",
    "corporate_action": "Paused for a corporate action",
}


@dataclass(frozen=True)
class Snapshot:
    """What the market says about one tokenized stock at one moment."""
    symbol: str
    ticker: str
    token_price: float
    stock_price: Optional[float]
    multiplier: float
    session: str            # premarket|regular|postmarket|overnight|offhours|closed|pause
    status: str             # TRADING|MARKET_CLOSED|MARKET_PAUSED|ASSET_PAUSED|ASSET_LIMITED
    reason: Optional[str] = None
    market_session: Optional[str] = None   # market-wide session (may disagree with per-asset session)
    reference_derived: bool = False        # stock price is just token price / multiplier (no independent quote)
    next_open_ms: Optional[int] = None     # when trading reopens (epoch ms), if known
    onchain_supply: Optional[float] = None # token totalSupply read from the BSC contract
    list_multiplier: Optional[float] = None  # multiplier as the token list reports it (may disagree with the price feed)
    api_supply: Optional[float] = None       # circulatingSupply as the API reports it
    multiplier_known: bool = True            # False when the API sent no sharesMultiplier (1.0 is then an assumption)
    last_trade_age_h: Optional[float] = None # hours since the last K-line candle that carried volume (None = unknown)
    reference_source: Optional[str] = None   # symbol whose stock quote was borrowed when this token has none (bStocks)
    reference_gap_bp: Optional[float] = None # token vs stock × multiplier, in basis points (shown with the pinned rule)

    @property
    def supply_mismatch(self) -> bool:
        """API circulatingSupply and on-chain totalSupply differ by more than 0.1%."""
        if not self.api_supply or not self.onchain_supply:
            return False
        return abs(self.api_supply - self.onchain_supply) / self.onchain_supply > 0.001

    @property
    def multiplier_conflict(self) -> bool:
        """The token list and the price feed give different shares-per-token (observed on xStocks, 2026-10-04)."""
        if not self.list_multiplier or self.list_multiplier <= 0 or self.multiplier <= 0:
            return False
        return abs(self.list_multiplier / self.multiplier - 1.0) > MULTIPLIER_CONFLICT

    @property
    def effective_multiplier(self) -> float:
        """On a multiplier conflict, the candidate the price ratio supports (token price / stock price)."""
        if not self.multiplier_conflict or not self.stock_price or not self.token_price:
            return self.multiplier
        implied = self.token_price / self.stock_price
        return min((self.list_multiplier, self.multiplier), key=lambda m: abs(math.log(implied / m)))

    @property
    def reference_price(self) -> Optional[float]:
        if self.reference_derived or self.multiplier_conflict or not self.stock_price or self.stock_price <= 0:
            return None
        return self.stock_price * self.multiplier

    @property
    def premium(self) -> Optional[float]:
        ref = self.reference_price
        if ref is None or not self.token_price or self.token_price <= 0:
            return None
        return self.token_price / ref - 1.0


@dataclass
class Verdict:
    level: str
    reasons: List[str] = field(default_factory=list)
    share_equivalent: float = 0.0
    reference_price: Optional[float] = None
    premium: Optional[float] = None
    risk: int = 0                     # 0-100, ranks WARNs against each other (weights: RISK_WEIGHTS)
    order_share_of_supply: Optional[float] = None
    notes: List[str] = field(default_factory=list)   # informational, does not raise the level

    def add_risk(self, points: int) -> None:
        self.risk = min(100, self.risk + points)

    def raise_to(self, level: str, reason: str) -> None:
        if _RANK[level] > _RANK[self.level]:
            self.level = level
        self.reasons.append(reason)


LARGE_FLOAT_SHARE = 0.01   # an order bigger than 1% of all tokens in existence is unusually large for this token

# Risk weights (documented; additive, capped at 100). They rank warnings, they are not probabilities.
RISK_WEIGHTS = {"halt_or_pause_or_no_token_price_or_price_off_25pct_or_no_trade_7d": 100, "last_trade_over_3d": 30, "multiplier_conflict": 40, "earnings_limited": 40, "market_closed": 15, "outside_regular_hours": 10,
                "multiplier": "up to 30, grows with |log10(multiplier)|", "multiplier_missing": 30,
                "premium": "1 point per 0.1% beyond threshold, max 40", "no_session_reported": 10,
                "no_independent_price": 15}


def check_trade(s: Snapshot, side: str, token_qty: float, premium_threshold: float = 0.01,
                sized_in_usd: bool = False) -> Verdict:
    """Is this trade safe to place now, and what is really being bought?"""
    if side not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")
    if token_qty <= 0:
        raise ValueError("token_qty must be positive")
    v = Verdict(ALLOW, [], share_equivalent=token_qty * s.effective_multiplier,
                reference_price=s.reference_price, premium=s.premium)

    if not s.token_price or s.token_price <= 0:
        v.raise_to(BLOCK, "No token price available right now — the order cannot be valued"); v.add_risk(100)
    if s.status == "MARKET_PAUSED" or s.session == "pause" or s.market_session == "pause":
        v.raise_to(BLOCK, "Market-wide trading halt"); v.add_risk(100)
    reason_key = (s.reason or "").strip().lower().replace(" ", "_")
    if s.status == "ASSET_PAUSED":
        v.raise_to(BLOCK, PAUSE_REASONS.get(reason_key, f"Asset paused ({s.reason or 'unknown reason'})")); v.add_risk(100)
    if s.status == "ASSET_LIMITED":
        what = "Earnings release" if reason_key == "earnings" else f"Limited ({s.reason or 'unknown reason'})"
        v.raise_to(WARN, f"{what} — trading restricted"); v.add_risk(40)
    if s.status == "MARKET_CLOSED" or s.session == "closed" or (not s.session and s.market_session == "closed"):
        v.raise_to(WARN, "US market is closed — the reference price is stale"); v.add_risk(15)
        if not s.session:
            v.raise_to(WARN, "The issuer reports no market session for this token — treat the price as unverified")
            v.add_risk(10)
    elif s.session in OUTSIDE_REGULAR or s.market_session == "closed" or s.market_session in OUTSIDE_REGULAR:
        v.raise_to(WARN, "Outside regular US hours — the stock quote is from extended/overnight trading or the last close, "
                         "and liquidity is thin"); v.add_risk(10)
    elif not s.session:
        v.raise_to(WARN, "The issuer reports no market session for this token — treat the price as unverified"); v.add_risk(10)

    if not s.multiplier_known:
        v.raise_to(WARN, "The API sent no multiplier for this token — the share count assumes 1 token = 1 share"); v.add_risk(30)
    if s.multiplier_conflict and s.supply_mismatch:
        v.raise_to(BLOCK, f"Token terms can't be verified — the API gives two multipliers ({s.list_multiplier:.4g} vs "
                          f"{s.multiplier:.4g}) and its supply ({s.api_supply:,.0f}) disagrees with the chain "
                          f"({s.onchain_supply:,.0f})"); v.add_risk(100)
    elif s.multiplier_conflict:
        v.raise_to(WARN, f"The API gives two different multipliers for this token (token list: {s.list_multiplier:.4g}, "
                         f"price feed: {s.multiplier:.4g}) — the real share count is uncertain; size the order in dollars "
                         f"and check the issuer's terms"); v.add_risk(40)   # >= CONFIRM_AT even when supply is unknown
    elif abs(s.multiplier - 1.0) > 0.05:
        msg = f"1 token = {s.multiplier:.4g} shares — compare prices per token, not per share"
        if sized_in_usd:
            v.notes.append(msg + " (already handled: your dollar amount was converted with the per-token price)")
        else:
            v.raise_to(WARN, msg)
            v.add_risk(min(30, int(10 * abs(math.log10(s.multiplier)) * 3)))

    age = s.last_trade_age_h
    if age is not None and age > STALE_BLOCK_H:
        v.raise_to(BLOCK, f"No trade in Binance's price history (K-line) for {age / 24:.0f} days — the token price is "
                          f"that old last trade, not a market price"); v.add_risk(100)
    elif age is not None and age > STALE_WARN_H:
        v.raise_to(WARN, f"Last trade in Binance's price history (K-line) was {age / 24:.0f} days ago — the token price "
                         f"may be stale, so no premium is computed"); v.add_risk(30)
    stale = age is not None and age > STALE_WARN_H
    if stale:
        v.premium = None
    p = None if stale else s.premium
    if s.multiplier_conflict and s.stock_price and s.stock_price > 0 and s.token_price and not stale:
        gap = s.token_price / (s.stock_price * s.effective_multiplier) - 1.0   # the candidate the prices support
        if abs(gap) > DATA_ERROR_GAP:
            v.raise_to(BLOCK, f"Token price is {gap * 100:+.0f}% off the reference price even with the multiplier the "
                              f"prices support — that is a data error, not a bargain"); v.add_risk(100)
    if p is not None and abs(p) > DATA_ERROR_GAP:
        v.raise_to(BLOCK, f"Token price is {p * 100:+.0f}% off the reference price — that is a data error or a broken "
                          f"market, not a bargain"); v.add_risk(100)
    elif p is not None and side == "BUY" and p > premium_threshold:
        v.raise_to(WARN, f"You would pay {p * 100:.1f}% above the reference price")
        v.add_risk(min(40, int(round((p - premium_threshold) * 1000))))
    elif p is not None and side == "SELL" and -p > premium_threshold:
        v.raise_to(WARN, f"You would sell {-p * 100:.1f}% below the reference price")
        v.add_risk(min(40, int(round((-p - premium_threshold) * 1000))))
    if s.reference_derived:
        gap = f", within {abs(s.reference_gap_bp):.1f} bp" if s.reference_gap_bp is not None else ""
        v.raise_to(WARN, f"No independent stock price right now — the token price and the stock quote are pinned "
                         f"together outside regular hours (stock × multiplier = token{gap}), so any premium is invisible")
        v.add_risk(15)
    elif s.reference_price is None and not s.multiplier_conflict:
        v.raise_to(WARN, "No reference price available"); v.add_risk(15)

    if s.onchain_supply and s.onchain_supply > 0:
        share = token_qty / s.onchain_supply
        v.order_share_of_supply = share
        if side == "BUY" and share > LARGE_FLOAT_SHARE:
            # Supply is not liquidity: Ondo mints/redeems on demand. This is a size signal, not a depth measurement.
            v.notes.append(f"Large order for this token — {share * 100:.1f}% of all {s.symbol} tokens on BNB Chain "
                           f"({s.onchain_supply:,.2f} in total); check the quote's price impact before signing")

    if not v.reasons:
        v.reasons.append("Trading normally; price is within the reference band")
    return v


def find_inconsistencies(s: Snapshot) -> List[str]:
    """Data contradictions worth reporting (Developer Experience Report material)."""
    out = []
    if s.market_session == "closed" and s.status == "TRADING":
        out.append(f"{s.symbol}: market-wide session is 'closed' but asset status is TRADING (session={s.session})")
    if not s.session:
        out.append(f"{s.symbol}: per-asset marketStatus is null (reasonCode={s.status})")
    if s.multiplier_conflict:
        out.append(f"{s.symbol}: list multiplier {s.list_multiplier:.6g} != price-feed sharesMultiplier {s.multiplier:.6g}")
    if not s.token_price or s.token_price <= 0:
        out.append(f"{s.symbol}: token price is null")
    if s.session and s.session not in DOCUMENTED_SESSIONS:
        out.append(f"{s.symbol}: undocumented marketStatus value '{s.session}'")
    if s.multiplier <= 0:
        out.append(f"{s.symbol}: non-positive multiplier {s.multiplier}")
    if not s.multiplier_known:
        out.append(f"{s.symbol}: sharesMultiplier is missing")
    if s.onchain_supply is not None and s.onchain_supply <= 0:
        out.append(f"{s.symbol}: zero on-chain supply")
    if s.stock_price is not None and s.stock_price <= 0:
        out.append(f"{s.symbol}: non-positive stock price")
    return out
