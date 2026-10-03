# StockGuard — "Can I trade this tokenized stock right now?"

## Purpose
Tokenized stocks on BSC trade 24/7, but the underlying US stocks do not. Corporate actions (cash dividends, stock dividends, splits, earnings) pause or limit individual tokens, and each token represents `multiplier` shares, not exactly one share. A trading bot or a first-time user who ignores these facts buys at the wrong time, the wrong price, or the wrong quantity.

StockGuard is a small safety layer that answers one question before any tokenized-stock trade — **"is this trade safe to place right now, and what am I really buying?"** — and exposes the answer three ways:
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
- Given an on-chain totalSupply of 220.99 tokens and a BUY of 15 tokens, then verdict = WARN ("Thin market — 6.8% of all tokens").
- Given a USD order size, then token quantity = USD ÷ per-token price (never per-share price).

- S6: Every verdict carries a 0–100 risk score so WARNs can be ranked (pause/halt = 100).
- S7: On-chain cross-check: token `totalSupply` from the BSC contract vs API `circulatingSupply`; mismatch >0.1% is reported.

## Non-goals
- No trading strategy, no PnL claims, no perps.
- No private keys handled by StockGuard (signing stays in the wallet / Agentic Wallet).

## Architecture
`domain/` (pure rules, no I/O) ← `application/` (use cases: check_trade, scan) ← `adapters/` (Binance public RWA HTTP client, MCP stdio tool, web handler) ← `infrastructure/` (CLI entry points, config).
