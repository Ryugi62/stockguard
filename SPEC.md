# StockGuard — "Can I trade this tokenized stock right now?"

## Purpose
Tokenized stocks on BSC trade 24/7, but the underlying US stocks do not. Corporate actions (cash dividends, stock dividends, splits, earnings) pause or limit individual tokens, and each token represents `multiplier` shares, not exactly one share. A trading bot or a first-time user who ignores these facts buys at the wrong time, the wrong price, or the wrong quantity.

StockGuard is a small safety layer that answers one question before any tokenized-stock trade — **"is this trade safe to place right now, and what am I really buying?"** — and exposes the answer through a library, MCP tools, a web page, the Agentic Wallet gate and a guarded-trade command:
1. a Python library (`check_trade(...)`) for agents,
2. an MCP-style JSON tool over stdio for LLM agents,
3. a plain-language web page for non-crypto users ("Why can't I buy AAPL right now?").

## Ubiquitous language
- **Token price** — on-chain price of the token (USD).
- **Multiplier** — shares of the underlying per token (`sharesMultiplier`).
- **Reference price** — underlying stock price × multiplier (what one token *should* be worth).
- **Premium** — token price ÷ reference price − 1.
- **Market session** — `premarket | regular | postmarket | overnight | offhours | closed | pause`.
- **Asset status** — `TRADING | MARKET_CLOSED | MARKET_PAUSED | ASSET_PAUSED | ASSET_LIMITED` with reason (`cash_dividend | stock_dividend | stock_split | earnings | …`).
- **Verdict** — `ALLOW | WARN | BLOCK` + human-readable reasons + share-equivalent quantity.

## Success criteria (numbers)
- S1: Domain rules cover 7 cases with unit tests: normal trading, market closed, market paused, asset paused (dividend), asset paused (split), earnings-limited, premium above threshold. 100% of domain tests pass.
- S2: Multiplier awareness: for a token with multiplier 10, an order of 1 token is reported as 10 shares and the reference price uses ×10 (test).
- S3: Live scan of all BSC tokenized stocks from the public RWA endpoints completes in < 3 minutes and writes a JSONL snapshot with session/status/premium per token.
- S4: Inconsistencies found in live data are logged with raw evidence (for the Developer Experience Report).
- S5: Web page renders a verdict for any ticker in < 2 s from cached snapshot.

## Given / When / Then
- Given an asset with `ASSET_PAUSED/stock_split`, when a BUY is checked, then verdict = BLOCK with reason "Paused for a stock split".
- Given `ASSET_LIMITED/earnings`, when a BUY is checked, then verdict = WARN ("Earnings release — trading restricted").
- Given session `closed` and premium +2.5% with threshold 1%, when a BUY is checked, then verdict = WARN ("You would pay 2.5% above the reference price while the US market is closed").
- Given multiplier 10 and quantity 1 token, then `share_equivalent` = 10.
- Given status `TRADING` in a regular session and premium within threshold, then verdict = ALLOW.
- Given per-asset session `offhours` (or pre/post/overnight) while the market-wide session is `closed`, then verdict = WARN ("Outside regular US hours").
- Given an on-chain totalSupply of 220.99 tokens and a BUY of 15 tokens, then a note "Large order for this token — 6.8% of all tokens" is added and the level is not raised (supply is not liquidity).
- Given a USD order size, then token quantity = USD ÷ per-token price (never per-share price).

- S6: Every verdict carries a 0–100 risk score so WARNs can be ranked (pause/halt = 100).
- S7: On-chain cross-check: token `totalSupply` from the BSC contract vs API `circulatingSupply`; mismatch >0.1% is reported.

- S8: Judge path — `python3 demo.py` from a fresh clone, with no install, key, wallet or network, finishes in < 5 s (measured 0.06 s) and shows NFLX across issuers, a USD-sized check, a gated swap with `baw` commands, a REFUSE and a quota reduction (test `test_offline_demo.py`).
- S9: All three issuers (list `type` 1 Ondo, 2 xStocks, 3 bStocks) are resolved; a bare ticker held by more than one issuer is never silently resolved.
- S10: Agentic Wallet gate — every rule cites the official skill text (`binance-agentic-wallet` v1.12.0) and has a test (`test_wallet_gate.py`).

## UC-4 Agentic Wallet gate (Given / When / Then)
Ubiquitous language: **Gate action** — `PROCEED | CONFIRM | ASK | REFUSE`. **Wallet settings** — `quotaLeft`, `dailyLimit`, `abnormalTxnHandling`, `tradeAllTokens` as returned by `baw wallet settings --json`. **Approved USD** — the order size the gate lets through.
- Given verdict BLOCK, when a swap is gated, then action = REFUSE, approved USD = 0, and no wallet command is emitted.
- Given verdict WARN with risk ≥ 40, then action = CONFIRM and `confirmation_required` = true (it can't be skipped). Given WARN below 40, then PROCEED with the reasons as heads-up notes.
- Given the token audit is unavailable (hasResult or isSupported false) or unreachable, then CONFIRM with the skill's exact sentence. Given riskLevel 5 or a tax above 10%, then REFUSE.
- Given a limit order at $75 per share on a 10-share token, then `--triggerPrice 750.00`. Given a disputed multiplier, then REFUSE.
- Given no slippage, then a note discloses "auto". Given an order under $1, then REFUSE. quotaLeft is rounded down to the cent.
- Given verdict ALLOW and no wallet limits, then action = PROCEED.
- Given quotaLeft 120 and an order of 500, then action = CONFIRM and approved USD = 120. Given quotaLeft 0, then REFUSE.
- Given a bare ticker held by several issuers, then action = ASK with the candidates, and no command.
- Given the market-data call fails, then action = REFUSE ("fail-closed").
- Given a contract address that is not in the RWA list, then REFUSE.
- Given BUY $100 of NFLXon, then the commands are `baw market-order quote|swap --fromTokenQty 100.00 --fromToken <USDT BSC> --toToken <NFLXon contract> --binanceChainId 56 --json`, followed by the `market-order list --orderId` poll. SELL swaps the token into USDT, and the token quantity is rounded down.

## UC-6 Guarded trade (`stockguard trade`, `application/trade.py` over a `WalletPort`)
- Given `wallet status` is not CONNECTED, then stop before any other call.
- Given the wallet's quote is more than 5% worse than the token price, then stop before the swap (1–5% → included in the confirmation).
- Given no typed yes, then no swap. Given a swap, then poll `market-order list` until FINISHED or FAILED, and report that status and txHash.
- Given SELL, then `wallet balance` must cover the quantity. Given a rejected limit order, then stop (no market fallback).

## UC-5 Issuers
- Given the list and the price feed disagree on the multiplier by more than 1% (NFLXx: 1 vs 10), then verdict ≥ WARN ("two different multipliers"), and reference price and premium are both null.
- Given a token price of null or 0, then verdict = BLOCK ("No token price").
- Given a per-asset `marketStatus` of null, then it is reported as a data inconsistency and the verdict is ≥ WARN. A market-wide `pause` → BLOCK even then.
- Given a multiplier conflict and an API-vs-chain supply mismatch (> 0.1%), then BLOCK ("token terms can't be verified"). On a conflict alone, the share count follows the price ratio.

## UC-7 Reproduce the DX findings (`scripts/reproduce_findings.py`)
Purpose: anyone (a judge, the W3W team, the report author) can see seven findings from `docs/dx-findings.md` on the real endpoints in one command. Success: 7 screens (F10, F9, F12, F1, F2, F7, F14) in that order, each with the exact request, the raw fields, the expectation and `reproduced: YES|NO`; live run < 10 s (measured 1.1 s); `--offline` reproduces all 7 from the recorded responses (test `test_reproduce_findings.py`).
- Given the list says multiplier 1 and the price feed says 10, then F10 = YES; given both say 1, then NO.
- Given a token price equal to the recording's, then F10 shows `tokenInfo.price unchanged since recording: true`.
- Given one endpoint fails, then that screen shows the error and NO, and the other screens still run.
- Given an independent stock quote (stock × multiplier ≠ token price), then F1 = NO with a note that it depends on the session.

## Non-goals
- No trading strategy, no PnL claims, no perps.
- No private keys handled by StockGuard (signing stays in the wallet / Agentic Wallet).

## Architecture
`domain/` (pure rules, no I/O: guard, wallet_gate, issuers) ← `application/` (use cases: check, compare, scan, replay, gate_swap) ← `adapters/` (Binance public RWA HTTP client, BSC RPC, recorded offline client, Agentic Wallet `baw` adapter (renderer + runner), MCP stdio tools, web handler) ← `infrastructure/` (CLI entry points, demo).
