"""StockGuard domain — pure rules, no I/O (SPEC.md §Ubiquitous language)."""
from dataclasses import dataclass, field
from typing import List, Optional

ALLOW, WARN, BLOCK = "ALLOW", "WARN", "BLOCK"
DOCUMENTED_SESSIONS = {"premarket", "regular", "postmarket", "overnight", "closed", "pause"}
OUTSIDE_REGULAR = {"premarket", "postmarket", "overnight", "offhours"}
_RANK = {ALLOW: 0, WARN: 1, BLOCK: 2}

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

    @property
    def reference_price(self) -> Optional[float]:
        if self.reference_derived or not self.stock_price or self.stock_price <= 0:
            return None
        return self.stock_price * self.multiplier

    @property
    def premium(self) -> Optional[float]:
        ref = self.reference_price
        if ref is None:
            return None
        return self.token_price / ref - 1.0


@dataclass
class Verdict:
    level: str
    reasons: List[str] = field(default_factory=list)
    share_equivalent: float = 0.0
    reference_price: Optional[float] = None
    premium: Optional[float] = None

    def raise_to(self, level: str, reason: str) -> None:
        if _RANK[level] > _RANK[self.level]:
            self.level = level
        self.reasons.append(reason)


def check_trade(s: Snapshot, side: str, token_qty: float, premium_threshold: float = 0.01) -> Verdict:
    """Is this trade safe to place now, and what is really being bought?"""
    if side not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")
    if token_qty <= 0:
        raise ValueError("token_qty must be positive")
    v = Verdict(ALLOW, [], share_equivalent=token_qty * s.multiplier,
                reference_price=s.reference_price, premium=s.premium)

    if s.status == "MARKET_PAUSED" or s.session == "pause":
        v.raise_to(BLOCK, "Market-wide trading halt")
    reason_key = (s.reason or "").strip().lower().replace(" ", "_")
    if s.status == "ASSET_PAUSED":
        v.raise_to(BLOCK, PAUSE_REASONS.get(reason_key, f"Asset paused ({s.reason or 'unknown reason'})"))
    if s.status == "ASSET_LIMITED":
        what = "Earnings release" if reason_key == "earnings" else f"Limited ({s.reason or 'unknown reason'})"
        v.raise_to(WARN, f"{what} — trading restricted")
    if s.status == "MARKET_CLOSED" or s.session == "closed":
        v.raise_to(WARN, "US market is closed — the reference price is stale")
    elif s.session in OUTSIDE_REGULAR or s.market_session == "closed":
        v.raise_to(WARN, "Outside regular US hours — the stock quote is from extended/overnight trading or the last close, "
                         "and liquidity is thin")

    if abs(s.multiplier - 1.0) > 0.05:
        v.raise_to(WARN, f"1 token = {s.multiplier:.4g} shares — compare prices per token, not per share")

    p = s.premium
    if p is not None and side == "BUY" and p > premium_threshold:
        v.raise_to(WARN, f"You would pay {p * 100:.1f}% above the reference price")
    if p is not None and side == "SELL" and -p > premium_threshold:
        v.raise_to(WARN, f"You would sell {-p * 100:.1f}% below the reference price")
    if s.reference_derived:
        v.raise_to(WARN, "No independent stock price right now — the quoted stock price is just the token price "
                         "divided by the multiplier, so any premium is invisible")
    elif s.reference_price is None:
        v.raise_to(WARN, "No reference price available")

    if not v.reasons:
        v.reasons.append("Trading normally; price is within the reference band")
    return v


def find_inconsistencies(s: Snapshot) -> List[str]:
    """Data contradictions worth reporting (Developer Experience Report material)."""
    out = []
    if s.market_session == "closed" and s.status == "TRADING":
        out.append(f"{s.symbol}: market-wide session is 'closed' but asset status is TRADING (session={s.session})")
    if s.session and s.session not in DOCUMENTED_SESSIONS:
        out.append(f"{s.symbol}: undocumented marketStatus value '{s.session}'")
    if s.multiplier <= 0:
        out.append(f"{s.symbol}: non-positive multiplier {s.multiplier}")
    if s.stock_price is not None and s.stock_price <= 0:
        out.append(f"{s.symbol}: non-positive stock price")
    return out
