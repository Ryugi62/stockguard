# Raw findings log (evidence for the Developer Experience Report)

This file is a lab notebook: what the public tokenized-securities endpoints returned, with the command to reproduce each observation. It is **not** the DX report. The organizers do not accept AI-generated reports, so the report itself must be written by the team member in their own words from these notes.

Snapshots: first scan 2026-10-03 ~04:45 UTC, rescan ~05:05 UTC (`data/scan-20261003-weekend.jsonl`) — 458 BSC tokens (chainId 56), Saturday, US market closed. Scan time 7.3–7.4 s, 0 request errors. Counts below are from the rescan unless stated; they move a little between scans.
Doc references point at the public skill file: https://github.com/binance/binance-skills-hub/blob/main/skills/binance-web3/binance-tokenized-securities-info/SKILL.md (line numbers as of 2026-10-03).

Reproduce: `PYTHONPATH=src python3 -m stockguard scan --out data/scan.jsonl`

## F1. Weekend "stock price" is the token price divided by the multiplier
- 432 of 458 tokens (427 in the first scan): `stockInfo.price × tokenInfo.sharesMultiplier == tokenInfo.price` to 1e-6.
- Example NFLXon (`0x7048f5227b032326cc8dbc53cf3fddd947a2c757`): token 670.62353, stock 67.062353, multiplier 10.
- The skill doc (SKILL.md L473, Stock Info table) says `stockInfo.price` "May be null outside trading hours". It is not null; it is filled with a value derived from the token itself.
- Effect: any premium/discount computed from this API outside US hours is always 0%. A bot cannot see whether it is overpaying on weekends. 8 tokens did return `null` (MAG7Xon, BLKDIGon, BRAINon, BLKHIon, YLD8on, BLKGRWon, YLD5on, and USDY), so client code must handle both.
- Fixture: `fixtures/dynamic_nflx_weekend.json`.

## F2. `marketStatus: "offhours"` is not in the documented enum
- Documented values (SKILL.md L328, API 4 response fields): premarket, regular, postmarket, overnight, closed, pause.
- 31 tokens returned `offhours` with `reasonCode: TRADING`, while the market-wide endpoint said `marketStatus: closed, reasonCode: MARKET_CLOSED, reasonMsg: "Weekend or Holiday"`.
- The market-wide response also carries an undocumented `offhours` object (`{"openState": true, "nextOpenTime": ..., "nextCloseTime": ...}`). Fixture: `fixtures/market_status_weekend.json`.
- Effect: a client that switches on the documented enum falls into its default branch.

## F3. Multipliers far from 1, in both directions
- `multiplier` ≥ 2 on 9 BSC tokens (KLACon 10.026, NFLXon 10, PPLTon 10, PALLon 5, CVNAon 5, NOWon 5, IWFon 4.013, CRWDon 4, APHon 2.004) and < 0.2 on 2 (ENLVon 0.066667, SOXSon 0.1017).
- Exposure table (`python3 -m stockguard replay data/scan-...jsonl --budget 1000`, arithmetic on real multipliers, not an observed agent): sizing $1,000 by the per-share price buys $10,026 of KLAC, $10,000 of NFLX, but only $66.67 of ENLV. On the Agentic Wallet market-order path a BUY is sized in USDT, so this error shows up in `limit-order --triggerPrice` (per token) and SELL token quantities.
- The doc does explain the multiplier (Key Concept). The finding is about defaults: the price most UIs and agents show next to a ticker is per token, and nothing in the payload flags "this token is not ~1 share".

## F4. One entry in the stock list has no symbol in the dynamic endpoint
- `list/ai?type=1` (stocks) includes USDY (`0x608593d17a2decbbc4399e4185be4922f97ed32e`). `dynamic/ai` for it returns no `symbol`/`ticker`, `marketStatus: regular`, `reasonCode: TRADING` on a Saturday.

## F5. Small things hit while building
- The `/v1` vs `/v2` split (dynamic is v2, the rest v1) is easy to miss when building URLs from a common prefix.
- `volume24h` in tokenInfo is the US stock volume in USD, not on-chain volume (the doc warns, but the field name invites the mistake).
- `nextOpen` / `nextClose` meaning flips with `openState` (documented), so "time until open" needs both fields.

## F6. Two different kinds of weekend quote, with no field telling them apart
- Of the 31 `offhours` tokens, 18 carry a stock price that is **not** derived from the token price (an independent but stale quote), while the other 440 tokens carry either a derived price (F1) or `null`.
- A client cannot tell "live", "stale but real" and "derived" apart without re-doing the arithmetic. A `referenceSource: live | last_close | derived` field would remove the guesswork.

## F7. Token K-Line volume is always "0"  (reproduce: `PYTHONPATH=src python3 -m stockguard kline NFLXon --limit 10`, fixture `fixtures/kline_nflx_1d.json`)
- `dex/market/token/kline/ai?interval=1d&limit=10` for NFLXon, AAPLon, TSLAon, NVDAon, SPYon, QQQon, KLACon, ENLVon, MSTRon, COINon: every one of the 100 daily candles has volume `"0"`, while open/high/low/close move.
- Either the field is not populated for RWA tokens or the candles are not trade-derived. In both cases a client cannot use this endpoint to judge on-chain liquidity, which is exactly what a pre-trade check needs.

## F8. On-chain supply matches the API (a positive check)
- `totalSupply()` read directly from the NFLXon contract over public BSC RPC = 220.9909 tokens, equal to the API `circulatingSupply`. Total value on BNB Chain ≈ $148k, so a $20k order is ~13% of every NFLXon token in existence — StockGuard shows that as a size note. Supply is not depth (Ondo mints on demand), so price impact still needs a trade quote (Trading API — key required).

## F9. xStocks and bStocks say "TRADING" with no market status on a Sunday  (scan 2026-10-04 04:45 UTC, `data/scan-20261004-all-issuers.jsonl`)
- Reproduce: `PYTHONPATH=src python3 -m stockguard scan --out data/scan.jsonl` (lists `type=1,2,3`), then count `session == ""` per `issuer`.
- 130/130 xStocks and 87/87 bStocks: `statusInfo.marketStatus: null`, `reasonCode: "TRADING"`, `nextOpenTime: null`. Same moment, Ondo: 426 `closed` + 31 `offhours` + 1 `regular`, and the market-wide endpoint said `closed / "Weekend or Holiday"`.
- Fixtures: `fixtures/dynamic_nflxx_weekend.json`, `fixtures/dynamic_nflxb_weekend.json`.
- Effect: one API, three issuers, three different answers to "is this tradeable now". A client written against Ondo responses treats every xStock/bStock as open 24/7.

## F10. xStocks: the token list and the price feed disagree on the multiplier (39 of 130)
- Reproduce: `PYTHONPATH=src python3 -m stockguard compare NFLX --offline` (or live without `--offline`).
- `list/ai?type=2` says `multiplier: "1"` for NFLXx; `dynamic/ai` says `sharesMultiplier: "10"`. The token price (71.30 vs stock 67.06) looks like about 1 share, not 10. Others: CRWDx 1 vs 4, TQQQx 1 vs 2.009, AZNx 1 vs 0.511, CMCSAx 1 vs 1.088 (39 tokens differ by more than 1%).
- On-chain: NFLXx `totalSupply()` = 100,000 tokens (BSC RPC), API `circulatingSupply` = 10,000 — again a factor of 10.
- Effect: a client can't know how many shares it is buying. If it trusts `sharesMultiplier`, NFLXx shows a phantom 89% discount. StockGuard refuses to compute a premium for these tokens and warns.

## F11. xStocks with no token price (77 of 130)
- `tokenInfo.price: null` on 77 xStocks (ABBVx, ABTx, ACNx, ADBEx …), while `statusInfo.reasonCode` is `TRADING`. StockGuard BLOCKs these ("No token price").
- 44 xStocks have both a token price and a stock price; for the 28 of them without a multiplier conflict, the largest gaps vs `stockInfo.price` were GMEx +844.9%, MRVLx −88.1%, UBERx −87.5%. These look like stale token prices or unit mismatches, not real premiums. Treat them as data issues, not trading signals.

## F12. bStocks carry no stock price at all (87 of 87)
- `stockInfo.price: null` for every bStock on 2026-10-04, so no premium/discount can be computed for that issuer on weekends. bStocks' `dailyAttestationReports` is an absolute URL (`https://www.binance.com/proof-of-collateral/bstocks`), while Ondo's is a relative path. This broke our first link builder (fixed, test `test_absolute_attestation_url_is_not_prefixed`).

## F13. Same ticker, different terms across issuers
- 120 tickers exist under more than one issuer, 38 under all three. The multiplier differs by more than 1.5× for NFLX (on 10 · x 1-or-10 · B 1), CRWD (on 4 · x 1-or-4 · B 1), TQQQ (x 2.009 in the price feed) and SOXS (on 0.102 · B 1.009).
- The Agentic Wallet skill says, for a bare ticker, "do not default to Ondo. Ask the user which provider they mean". The tokenized-securities skill's own lookup only knows `type=1`. StockGuard resolves all three and returns `ASK` with the choices.

## F14. The wallet's mandatory token audit can't see tokenized stocks
- Reproduce: `curl -X POST https://web3.binance.com/bapi/defi/v1/public/wallet-direct/security/token/audit -H 'Content-Type: application/json' -H 'source: agent' -H 'User-Agent: binance-web3/1.4 (Skill)' -d '{"binanceChainId":"56","contractAddress":"0x7048f5227b032326cc8dbc53cf3fddd947a2c757","requestId":"<uuid4>"}'`
- 45 of 45 sampled stock tokens (the first 15 of each issuer's list, 2026-10-04) returned `hasResult: false, isSupported: false, riskLevel: -1`. USDT returned `hasResult: true, riskLevel: 3` (MEDIUM).
- The Agentic Wallet skill (`references/security.md` §1) requires this audit before every `market-order swap` / `limit-order`, and when it is unavailable it requires "explicit user acknowledgment". So every tokenized-stock order an agent places ends in an acknowledgment prompt that carries no information about the stock. StockGuard is built to supply the stock-specific checks that the audit does not cover.
- Recorded responses for the demo tokens: `fixtures/recorded/demo-2026-10-04.json` → `audit`.

## Latency (2026-10-04 04:43 UTC, n=10 per endpoint, `PYTHONPATH=src python3 scripts/latency.py`, raw `data/latency-20261004.json`)
- p50 74–111 ms, p95 130–189 ms, max 424 ms (list type=2). The `list` call is the slowest. A full 675-token scan takes 13.8 s with 8 workers.

## Agentic Wallet skill — what the gate is built on (binance-skills-hub, `binance-agentic-wallet` v1.12.0, cloned 2026-10-04)
- Swap syntax and the "orderId is not a completed swap — poll" rule: `references/market-order.md`. Wallet policy fields: `references/wallet-setting.md`. Fail-closed / no address hallucination / ask the provider: `SKILL.md`.
- Things that slowed us down (raw, for the report): the token-audit pre-check (`references/security.md`) depends on a separate skill (`query-token-audit`), and it has no data for stock tokens (F14). `limit-order --triggerPrice` is a per-token USD price, so on a multiplier-10 token a per-share target is off by 10×. The skill tells agents to "Determine support at runtime" for limit orders, and quotes an `Ondo-related tokens cannot be traded` error. Wallet settings "can only be changed in the Binance App", so an agent can read the limits but never set them.

Reading guide for the report: F1, F2, F6 and F12 are one theme — **how far can a client trust the reference price**. F9, F10, F11 and F13 are a second one — **the same API means different things per issuer**. Both lead to the redesign questions in `docs/dx-report-TEMPLATE.md`.

## Still to write from first-hand use (the human report must cover these)
- Onboarding time from opening the docs to the first successful call, and where it stalled.
- AI stack section: Agentic Wallet / Wallet Skills / CLI install and use (not used in this build — needs sign-in).
- Transaction API dry-run pitfalls (needs an API key from the developer portal).
- Redesign suggestions and requested capabilities (candidates from this log: `referenceSource` field, `offhours` in the enum, a per-token `isTradeable` boolean, populated kline volume, one `sharesPerToken` value served identically by list and dynamic, a per-issuer `marketStatus` that is never null).

## Not yet verified (needs a weekday session and/or an API key)
- Behaviour during an actual `ASSET_PAUSED` (dividend/split) or `ASSET_LIMITED` (earnings) window.
- Whether the derived-price behaviour (F1) also appears during `overnight` on weekdays.
- Order placement through the Agentic Wallet / Binance Web3 APIs (requires sign-in and funds).
