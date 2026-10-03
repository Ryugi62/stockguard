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
- Replay (`python3 -m stockguard replay data/scan-...jsonl --budget 1000`) — a **hypothetical** agent (not an observed one) that wants $1,000 of exposure, reads the per-share price, and buys that many tokens would end up with $10,026 of KLAC, $10,000 of NFLX, but only $66.67 of ENLV.
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

## F7. Token K-Line volume is always "0"  (reproduce: `PYTHONPATH=src python3 -m stockguard kline NFLX --limit 10`, fixture `fixtures/kline_nflx_1d.json`)
- `dex/market/token/kline/ai?interval=1d&limit=10` for NFLXon, AAPLon, TSLAon, NVDAon, SPYon, QQQon, KLACon, ENLVon, MSTRon, COINon: every one of the 100 daily candles has volume `"0"`, while open/high/low/close move.
- Either the field is not populated for RWA tokens or the candles are not trade-derived. In both cases a client cannot use this endpoint to judge on-chain liquidity, which is exactly what a pre-trade check needs.

## F8. On-chain supply matches the API (a positive check)
- `totalSupply()` read directly from the NFLXon contract over public BSC RPC = 220.9909 tokens, equal to the API `circulatingSupply`. Total value on BNB Chain ≈ $148k, so a $20k order is ~13% of every NFLXon token in existence — StockGuard shows that as a size note. Supply is not depth (Ondo mints on demand), so price impact still needs a trade quote (Trading API — key required).

Reading guide for the report: F1, F2 and F6 are one theme — **how far can a client trust the reference price** — and lead to one request (a `referenceSource` field + `offhours` in the enum).

## Still to write from first-hand use (the human report must cover these)
- Onboarding time from opening the docs to the first successful call, and where it stalled.
- AI stack section: Agentic Wallet / Wallet Skills / CLI install and use (not used in this build — needs sign-in).
- Transaction API dry-run pitfalls (needs an API key from the developer portal).
- Redesign suggestions and requested capabilities (candidates from this log: `referenceSource` field, `offhours` in the enum, a per-token `isTradeable` boolean, populated kline volume).

## Not yet verified (needs a weekday session and/or an API key)
- Behaviour during an actual `ASSET_PAUSED` (dividend/split) or `ASSET_LIMITED` (earnings) window.
- Whether the derived-price behaviour (F1) also appears during `overnight` on weekdays.
- Order placement through the Agentic Wallet / Binance Web3 APIs (requires sign-in and funds).
