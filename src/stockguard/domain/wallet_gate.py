"""Agentic Wallet pre-trade gate — pure rules (SPEC.md UC-4).

StockGuard's verdict is translated into the same vocabulary the Agentic Wallet already uses for its own policy
(references/wallet-setting.md: `abnormalTxnHandling` AutoReject | NeedConfirmation, `quotaLeft`, `tradeAllTokens`):
  BLOCK                       -> REFUSE   (analogous to AutoReject — but the wallet never sees StockGuard's verdict)
  WARN with risk >= CONFIRM_AT -> CONFIRM (explicit user confirmation, analogous to NeedConfirmation; can't be skipped)
  WARN below CONFIRM_AT        -> PROCEED with the reasons as notes the agent must show (avoids confirm-fatigue)
  ALLOW                       -> PROCEED  (the skill's normal per-trade confirmation still applies)
  order > wallet quotaLeft    -> CONFIRM with the order cut (rounded down) to quotaLeft;  quotaLeft <= 0 -> REFUSE
Token audit (query-token-audit skill, required by security.md §1): unavailable -> CONFIRM (acknowledge),
riskLevel >= 4 or tax > 10% -> REFUSE, riskLevel 2-3 or tax 5-10% -> CONFIRM.
"""
import math
from dataclasses import dataclass, field
from typing import List, Optional

from stockguard.domain.guard import ALLOW, BLOCK, WARN, Verdict

PROCEED, CONFIRM, ASK, REFUSE = "PROCEED", "CONFIRM", "ASK", "REFUSE"
CONFIRM_AT = 40          # risk score from which a WARN needs an explicit yes (earnings-limited = 40)
MIN_ORDER_USD = 1.0
QUOTE_CONFIRM_GAP, QUOTE_REFUSE_GAP = 0.01, 0.05   # quote vs API token price: >1% confirm, >5% refuse

AUDIT_UNAVAILABLE = "Security audit data is not available for this token on this chain."   # security.md, verbatim
AUDIT_DOWN = "Token security audit is temporarily unavailable."                             # security.md, verbatim
AUDIT_SKIPPED = "The token security audit was skipped on request — the user must explicitly acknowledge trading without it."
AUDIT_DISCLAIMER = ('LOW risk does NOT mean "safe." Audit results are point-in-time snapshots. Project teams can modify '
                    'contracts or restrict liquidity after purchase. These risks cannot be predicted in advance.')  # verbatim
AUDIT_VERIFY = "You may verify the contract address and chain, or try again later."   # query-token-audit, unavailable case


@dataclass(frozen=True)
class AuditResult:
    """query-token-audit result. Only valid when hasResult AND isSupported (`available`)."""
    available: bool
    risk_level: Optional[int] = None
    hits: tuple = ()
    buy_tax: Optional[float] = None
    sell_tax: Optional[float] = None
    error: Optional[str] = None


@dataclass(frozen=True)
class QuoteCheck:
    level: str            # PROCEED | CONFIRM | REFUSE
    effective_price: float
    gap: float            # how much worse than the API token price (fraction, positive = worse)
    reason: str


def check_quote(side: str, from_amount: float, to_amount: float, token_price: float) -> QuoteCheck:
    """Re-gate on the wallet's own quote: effective price per token vs the API token price."""
    if from_amount <= 0 or to_amount <= 0 or token_price <= 0:
        return QuoteCheck(REFUSE, 0.0, 1.0, "The quote is empty or the token has no price — can't check it")
    if side == "BUY":
        eff = from_amount / to_amount            # USD paid per token received
        gap = eff / token_price - 1.0
    else:
        eff = to_amount / from_amount            # USD received per token sold
        gap = 1.0 - eff / token_price
    level = REFUSE if gap > QUOTE_REFUSE_GAP else CONFIRM if gap > QUOTE_CONFIRM_GAP else PROCEED
    word = "pay" if side == "BUY" else "receive"
    return QuoteCheck(level, eff, gap, f"The wallet's quote would {word} ${eff:,.4f} per token, {gap * 100:+.1f}% "
                                       f"{'worse' if gap > 0 else 'better'} than the token price ${token_price:,.4f}")


def per_token_trigger(share_price: float, multiplier: float, multiplier_conflict: bool) -> float:
    """limit-order `--triggerPrice` is the token's USD price; people think in share prices."""
    if multiplier_conflict:
        raise ValueError("the API gives two multipliers for this token, so a share price can't be turned into a token "
                         "price — refuse the limit order")
    if share_price <= 0 or multiplier <= 0:
        raise ValueError("share price and multiplier must be positive")
    return round(share_price * multiplier, 6)


@dataclass(frozen=True)
class WalletSettings:
    """The parts of the Agentic Wallet's own security settings that bound a trade."""
    quota_left: Optional[float] = None        # USD left of the 24h daily limit
    daily_limit: Optional[float] = None
    abnormal_handling: Optional[str] = None   # AutoReject | NeedConfirmation
    trade_all_tokens: Optional[bool] = None   # False -> allow-listed tokens only
    quota_date: Optional[str] = None          # the day quotaLeft applies to (YYYY-MM-DD)
    session_expires: Optional[str] = None     # sessionExpireTime


@dataclass
class GateDecision:
    action: str
    requested_usd: float
    approved_usd: float
    reasons: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    confirmation_required: bool = False


def _floor_cents(x: float) -> float:
    return math.floor(x * 100 + 1e-9) / 100


def decide(verdict: Verdict, requested_usd: float, settings: Optional[WalletSettings] = None,
           audit: Optional[AuditResult] = None, confirm_at: int = CONFIRM_AT) -> GateDecision:
    if requested_usd <= 0:
        raise ValueError("requested_usd must be positive")
    notes = list(verdict.notes)
    if requested_usd < MIN_ORDER_USD:
        return GateDecision(REFUSE, requested_usd, 0.0, [f"Order below the ${MIN_ORDER_USD:.2f} minimum"], notes)
    if verdict.level == BLOCK:
        return GateDecision(REFUSE, requested_usd, 0.0, list(verdict.reasons),
                            notes + ["Refused before the wallet is called (the wallet never sees this verdict)."])
    serious = verdict.level == WARN and verdict.risk >= confirm_at
    d = GateDecision(CONFIRM if serious else PROCEED, requested_usd, requested_usd,
                     list(verdict.reasons) if serious else [], notes, confirmation_required=serious)
    if serious:
        d.notes.append("Show these reasons to the user and wait for an explicit yes, even if they asked to skip "
                       "confirmations.")
    elif verdict.level == WARN:
        d.notes += [f"Heads-up to show the user: {r}" for r in verdict.reasons]
    if audit is not None:
        if not audit.available:
            if d.action != CONFIRM and verdict.level == WARN:      # the stock warnings go into the confirmation text
                d.reasons = list(verdict.reasons) + d.reasons
                d.notes = [n for n in d.notes if not n.startswith("Heads-up")]
            d.action, d.confirmation_required = CONFIRM, True
            d.reasons.append(AUDIT_SKIPPED if audit.error == "skipped" else AUDIT_DOWN if audit.error else AUDIT_UNAVAILABLE)
            d.notes.append("The wallet skill requires the user's explicit acknowledgment before trading without an audit.")
            if not audit.error:
                d.notes.append(AUDIT_VERIFY)
        else:
            d.notes.append(AUDIT_DISCLAIMER)
            tax = max(audit.buy_tax or 0.0, audit.sell_tax or 0.0)
            if (audit.risk_level or 0) >= 4 or tax > 10:   # skill: 4 = "Avoid trading", 5 = "Block", tax >10% critical
                return GateDecision(REFUSE, requested_usd, 0.0, d.reasons + [
                    f"Token audit: riskLevel {audit.risk_level}, tax {tax:g}% — avoid trading"] + list(audit.hits), d.notes)
            if (audit.risk_level or 0) >= 2 or tax > 5:     # 2-3 = "Exercise caution", tax 5-10% = warning
                d.action, d.confirmation_required = CONFIRM, True
                d.reasons.append(f"Token audit: caution (riskLevel {audit.risk_level}, tax {tax:g}%)"
                                 + (": " + ", ".join(audit.hits) if audit.hits else ""))
    if settings is not None:
        if settings.quota_left is not None and settings.quota_left <= 0:
            return GateDecision(REFUSE, requested_usd, 0.0,
                                d.reasons + ["The wallet's daily limit is used up (quotaLeft 0) — the wallet would reject it"],
                                d.notes)
        if settings.quota_left is not None and requested_usd > settings.quota_left:
            d.approved_usd = _floor_cents(float(settings.quota_left))
            d.action, d.confirmation_required = CONFIRM, True
            d.reasons.append(f"Reduced from ${requested_usd:,.2f} to ${d.approved_usd:,.2f} — what is left of the "
                             f"wallet's daily limit (quotaLeft)")
        if settings.trade_all_tokens is False:
            d.notes.append("This wallet trades only tokens on its allowed list (tradeAllTokens=false); if this token "
                           "is not on it, the wallet will reject the order — the list is changed in the Binance App.")
        if settings.quota_left is not None and 0 < settings.quota_left < MIN_ORDER_USD:
            return GateDecision(REFUSE, requested_usd, 0.0, d.reasons + ["Less than $1 of the daily limit is left"], d.notes)
        if settings.abnormal_handling == "AutoReject" and verdict.level == WARN:
            d.notes.append("The wallet auto-rejects transactions it flags as abnormal; StockGuard's warnings are "
                           "separate and are not seen by the wallet.")
    return d
