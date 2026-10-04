"""Agentic Wallet pre-trade gate — pure rules (SPEC.md UC-4).

StockGuard's verdict is translated into the same vocabulary the Agentic Wallet already uses for its own policy
(references/wallet-setting.md: `abnormalTxnHandling` AutoReject | NeedConfirmation, `quotaLeft`, `tradeAllTokens`):
  BLOCK                    -> REFUSE   (never reaches the wallet, like AutoReject)
  WARN                     -> CONFIRM  (explicit user confirmation, like NeedConfirmation — cannot be skipped)
  ALLOW                    -> PROCEED  (the skill's normal per-trade confirmation still applies)
  order > wallet quotaLeft -> CONFIRM with the order reduced to quotaLeft;  quotaLeft <= 0 -> REFUSE
"""
from dataclasses import dataclass, field
from typing import List, Optional

from stockguard.domain.guard import ALLOW, BLOCK, WARN, Verdict

PROCEED, CONFIRM, ASK, REFUSE = "PROCEED", "CONFIRM", "ASK", "REFUSE"


@dataclass(frozen=True)
class WalletSettings:
    """The parts of the Agentic Wallet's own security settings that bound a trade."""
    quota_left: Optional[float] = None        # USD left of the 24h daily limit
    daily_limit: Optional[float] = None
    abnormal_handling: Optional[str] = None   # AutoReject | NeedConfirmation
    trade_all_tokens: Optional[bool] = None   # False -> allow-listed tokens only


@dataclass
class GateDecision:
    action: str
    requested_usd: float
    approved_usd: float
    reasons: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    confirmation_required: bool = False


def decide(verdict: Verdict, requested_usd: float, settings: Optional[WalletSettings] = None) -> GateDecision:
    if requested_usd <= 0:
        raise ValueError("requested_usd must be positive")
    notes = list(verdict.notes)
    if verdict.level == BLOCK:
        return GateDecision(REFUSE, requested_usd, 0.0, list(verdict.reasons),
                            notes + ["Refused before the wallet is called (same effect as AutoReject)."])
    d = GateDecision(PROCEED if verdict.level == ALLOW else CONFIRM, requested_usd, requested_usd,
                     list(verdict.reasons) if verdict.level == WARN else [], notes,
                     confirmation_required=verdict.level == WARN)
    if verdict.level == WARN:
        d.notes.append("Show these reasons to the user and wait for an explicit yes, even if they asked to skip "
                       "confirmations (same effect as NeedConfirmation).")
    if settings is not None:
        if settings.quota_left is not None and settings.quota_left <= 0:
            return GateDecision(REFUSE, requested_usd, 0.0,
                                d.reasons + ["The wallet's daily limit is used up (quotaLeft 0) — the wallet would reject it"],
                                d.notes)
        if settings.quota_left is not None and requested_usd > settings.quota_left:
            d.approved_usd = round(float(settings.quota_left), 2)
            d.action, d.confirmation_required = CONFIRM, True
            d.reasons.append(f"Reduced from ${requested_usd:,.2f} to ${d.approved_usd:,.2f} — what is left of the "
                             f"wallet's daily limit (quotaLeft)")
        if settings.trade_all_tokens is False:
            d.notes.append("This wallet trades only tokens on its allowed list (tradeAllTokens=false); if this token "
                           "is not on it, the wallet will reject the order — the list is changed in the Binance App.")
        if settings.abnormal_handling == "AutoReject" and verdict.level == WARN:
            d.notes.append("The wallet auto-rejects transactions it flags as abnormal; StockGuard's warnings are "
                           "separate and are not seen by the wallet.")
    return d
