# Raw findings log (evidence for the Developer Experience Report)

This file is a lab notebook: what the public tokenized-securities endpoints (and the `baw` CLI) returned, with the command to reproduce each observation.

Snapshots: first scan 2026-10-03 ~04:45 UTC, rescan ~05:05 UTC (`data/scan-20261003-weekend.jsonl`) — 458 BSC tokens (chainId 56), Saturday, US market closed. Scan time 7.3–7.4 s, 0 request errors. Counts below are from the rescan unless stated; they move a little between scans.
Doc references point at the public skill file: https://github.com/binance/binance-skills-hub/blob/main/skills/binance-web3/binance-tokenized-securities-info/SKILL.md (line numbers as of 2026-10-03).

Reproduce: `PYTHONPATH=src python3 -m stockguard scan --out data/scan.jsonl` (all tokens) · `python3 scripts/reproduce_findings.py` (seven findings, one screen each, live in ~1 s; `--offline` for the recorded responses)

## F1. Outside regular hours, stock price × multiplier = token price (not two independent prices)
- 432 of 458 tokens (427 in the first scan): `stockInfo.price × tokenInfo.sharesMultiplier == tokenInfo.price` to 1e-6.
- Example NFLXon (`0x7048f5227b032326cc8dbc53cf3fddd947a2c757`): token 670.62353, stock 67.062353, multiplier 10.
- The skill doc (SKILL.md L473, Stock Info table) says `stockInfo.price` "May be null outside trading hours". It is not null; it is filled with a value derived from the token itself.
- Weekday recheck 2026-10-07 (Wednesday, US `overnight` session): NFLXon at 04:42 UTC token 691.625 vs stock 69.1625 × 10 (identical); at 04:38 UTC 691.66842 vs 691.65385 (2 bp); at 04:50 UTC 692.1988 vs 692.19761 (0.02 bp). So it is not weekend-only, and outside regular hours the two move together within a few bp.
- Equal values don't show which side is computed from which. Since Ondo K-line volume is always 0 (F7), the token price may well be computed from the stock quote rather than the other way round. Either way, the two are not independent observations, so no premium can be read from them. And the stock quote is one feed shared by all issuers: `stockInfo.price` was identical for 85 of the 86 tickers listed by more than one issuer and carrying a stock price (full scan 2026-10-07 05:3x UTC, 675 tokens, 0 errors), while 72 of the 87 bStocks (which carry none, F12) share a ticker with a token that has one. Across all 458 Ondo tokens in one overnight scan (2026-10-07 05:3x UTC) the gap was 0 for 319, under 5 bp for 88, 5–50 bp for 42 and over 50 bp for 1 (8 had no price): one feed updating with a lag, not independent quotes. StockGuard treats a gap ≤ 50 bp outside regular hours as "pinned" and prints the gap.
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

## F7. Ondo K-Line volume is always "0" (xStocks and bStocks candles do carry volume)  (reproduce: `PYTHONPATH=src python3 -m stockguard kline NFLXon --limit 10`, fixture `fixtures/kline_nflx_1d.json`)
- `dex/market/token/kline/ai?interval=1d&limit=10` for NFLXon, AAPLon, TSLAon, NVDAon, SPYon, QQQon, KLACon, ENLVon, MSTRon, COINon: every one of the 100 daily candles has volume `"0"`, while open/high/low/close move.
- Not so for the other issuers: NFLXx and NFLXB daily candles carry volume (NFLXB 324,468.95 on 2026-10-06; NFLXx 408.98 on 2026-09-28), checked 2026-10-07, screen 6 of `scripts/reproduce_findings.py`.
- So for Ondo either the field is not populated or the candles are not trade-derived. In both cases a client cannot use this endpoint to judge on-chain liquidity, which is exactly what a pre-trade check needs.

## F8. On-chain supply matches the API (a positive check)
- `totalSupply()` read directly from the NFLXon contract over public BSC RPC = 220.9909 tokens, equal to the API `circulatingSupply`. Total value on BNB Chain ≈ $148k, so a $20k order is ~13% of every NFLXon token in existence — StockGuard shows that as a size note. Supply is not depth (Ondo mints on demand), so price impact still needs a trade quote (Trading API — key required).

## F9. xStocks and bStocks say "TRADING" with no market status on a Sunday  (scan 2026-10-04 04:45 UTC, `data/scan-20261004-all-issuers.jsonl`)
- Reproduce: `PYTHONPATH=src python3 -m stockguard scan --out data/scan.jsonl` (lists `type=1,2,3`), then count `session == ""` per `issuer`; or screen 2 of `python3 scripts/reproduce_findings.py`.
- 130/130 xStocks and 87/87 bStocks: `statusInfo.marketStatus: null`, `reasonCode: "TRADING"`, `nextOpenTime: null`. Same moment, Ondo: 426 `closed` + 31 `offhours` + 1 `regular`, and the market-wide endpoint said `closed / "Weekend or Holiday"`.
- Fixtures: `fixtures/dynamic_nflxx_weekend.json`, `fixtures/dynamic_nflxb_weekend.json`.
- Effect: one API, three issuers, three different answers to "is this tradeable now". A client written against Ondo responses treats every xStock/bStock as open 24/7.

## F10. xStocks: the token list and the price feed disagree on the multiplier (39 of 130)
- Reproduce: `PYTHONPATH=src python3 -m stockguard compare NFLX --offline` (or live without `--offline`).
- `list/ai?type=2` says `multiplier: "1"` for NFLXx; `dynamic/ai` says `sharesMultiplier: "10"`. The token price (71.30 vs stock 67.06) looks like about 1 share, not 10. Others: CRWDx 1 vs 4, TQQQx 1 vs 2.009, AZNx 1 vs 0.511, CMCSAx 1 vs 1.088 (39 tokens differ by more than 1%).
- `list/ai?type=2` also returns a Solana entry for NFLXx (`chainId: "CT_501"`, `multiplier: "10"`); the BSC entry says `"1"`. The BSC price feed's `sharesMultiplier` (`"10"`) equals the Solana value (checked 2026-10-07 04:4x UTC). Same pattern for CRWDx (Solana 4, BSC 1).
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
- Full run 2026-10-04 05:10–05:15 UTC over all 675 BSC stock tokens (raw `data/audit-all-20261004.jsonl`, `PYTHONPATH=src python3 scripts/audit_sample.py --n 0 --out …`): 663 returned `hasResult: false, isSupported: false, riskLevel: -1` — all 458 Ondo, all 130 xStocks, 75 of 87 bStocks. The 12 bStocks with data (GPROB, RDDTB, CYPHB, AGPUB, AMCB, ZMB, HPEB, ADBEB, SHAZB, FWDIB, PDDB, WENB) were all `riskLevel 0`. USDT returned `hasResult: true, riskLevel: 3` (MEDIUM), last line of the same file.
- The Agentic Wallet skill (`references/security.md` §1) requires this audit before every `market-order swap` / `limit-order`, and when it is unavailable it requires "explicit user acknowledgment". So every tokenized-stock order an agent places ends in an acknowledgment prompt that carries no information about the stock. StockGuard is built to supply the stock-specific checks that the audit does not cover.
- The no-data response still carries `riskLevelEnum: "LOW"` next to `riskLevel: -1` (NFLXon, 2026-10-04 and again 2026-10-07 04:42 UTC). The skill's own rule says not to show the level when `hasResult` is false, so a client that reads only `riskLevelEnum` shows "LOW" for a token that was never audited.
- Recorded responses for the demo tokens: `fixtures/recorded/demo-2026-10-04.json` → `audit`.

## F15. Notes from installing `baw` (npm `@binance/agentic-wallet` 1.10.0, not signed in)
- `--json` is a global option: it is not listed in each subcommand's `--help` (`baw market-order swap --help`), only in `baw --help`. The skill says to "Always append `--json`", and it works after the subcommand.
- Without signing in, `wallet status` answers `{"success": true, "data": {"status": "UNCONNECTED"}}`, but `market-order quote` fails with `NOT_LOGGED_IN` (code 10003000). So a read-only price quote needs a signed-in wallet. Raw output: `fixtures/baw/`.

## F16. NFLXx's token price is a nine-day-old trade, and only the K-line says so (Binance's price history, not a chain log)
- `dynamic/ai` for NFLXx (`0xa6a65ac27e76cd53cb790473e4345c46e5ebf961`) returned `tokenInfo.price: "71.302720129194506196863678605096598194"` on 2026-10-04 04:54 UTC (Sunday, `fixtures/dynamic_nflxx_weekend.json`) and the identical string on 2026-10-07 04:42 UTC (Wednesday), while `stockInfo.price` moved 67.06 → 69.16 and NFLXB's token price moved 67.71 → 69.24.
- The NFLXx K-line explains it: its last candle with volume is 2026-09-28 (close 71.3027, volume 408.98). The token price is the last trade of a thin pool, not a frozen feed. But `dynamic/ai` carries no timestamp or source for the token price, so a client has to call a second endpoint to learn that the price is nine days old. `compare` used to show it as a +3.1% per-share premium; StockGuard now reads the K-line and, for a last trade older than 3 days, computes no premium (WARN); older than 7 days, it BLOCKs.
- Reproduce: screen 1 of `python3 scripts/reproduce_findings.py` (lines `last K-line candle with volume` and `tokenInfo.price == that close`).

## F17. `baw` 1.10.0 reads tokenized-stock amounts as shares, the skill says "human-readable units"
- Read from the published package (`npm pack @binance/agentic-wallet@1.10.0`, shasum `606a357a41638c72beb40c56cb5acee8efa0f275` = the registry's `dist.shasum`; `dist/index.js`, read, not run). For a token in its RWA list (`…/rwa/stock/scaleui/list`; its multipliers equal `list/ai` for all 675 BSC stock tokens of types 1–3, checked 2026-10-07; the list also holds 4 type-4 pre-IPO tokens — xKLSH, xOPAI, xSPCX, pPOLY — that `list/ai?type=1|2|3` doesn't return):
  - `market-order quote|swap` SELL: `--fromTokenQty` is a **share** amount; the CLI divides by the multiplier before sending (`Wt`, `Wn`), capped at the balance.
  - `market-order quote` BUY: `toCoinAmount` comes back in shares (`toTokenShare`, or `toCoinAmount` × multiplier).
  - `wallet balance`: `balance` and `price` are per share. The token amounts exist as `rawBalance` / `rawPrice` in the table view, but with `--json` the CLI strips `rawBalance`, `rawPrice`, `multiplier`, `shareBalance` and `sharePrice` (`({isOndo,multiplier,rawBalance,rawPrice,shareBalance,sharePrice,...A}) => …`). So an agent using `--json` can't get token units or the multiplier from baw at all; it has to know the multiplier from the RWA list.
  - `limit-order buy|sell` create: amount and `--triggerPrice` are sent as given (token units, per-token price), but `limit-order list` shows them per share.
  - The RWA list only maps `type` 1 → ondo and 3 → bstock; xStocks (type 2) are `kind: "unknown"`.
- The skill (`references/market-order.md`) only says amounts are in "human-readable units". On NFLXon (10 shares per token), a SELL sized in tokens sells a tenth of what was meant; on ENLVon (0.0667) it sells 15× more, up to the whole balance. StockGuard's earlier build made exactly this mistake (caught by a mock judge reading the bundle) and now sends SELL amounts in shares, divides the JSON share balance by the list multiplier, converts quotes back to token units, and refuses a quote for a different amount or one that is far *better* than the market (the signature of a unit error) (tests: `tests/test_trade.py`, `tests/test_wallet_gate.py`).

## F18. The token audit API can't be called from a browser
- `OPTIONS …/security/token/audit` answers `access-control-allow-origin: *` but no `Access-Control-Allow-Headers`, so under the CORS rules a browser won't send the `Content-Type: application/json` POST; a `text/plain` body (no preflight) is answered `{"code":"000002","message":"illegal parameter"}` (checked 2026-10-07). The RWA Data endpoints and the BSC RPC node do allow browser calls. So a web wallet front-end can't run the audit the wallet skill requires before every swap. The in-browser build of StockGuard (`site/`) therefore shows the audit as unreachable.

## Latency (2026-10-04 04:43 UTC, n=10 per endpoint, `PYTHONPATH=src python3 scripts/latency.py`, raw `data/latency-20261004.json`)
- p50 74–111 ms, p95 130–189 ms, max 424 ms (list type=2). The `list` call is the slowest. A full 675-token scan takes 13.8 s with 8 workers.

## Agentic Wallet skill — what the gate is built on (binance-skills-hub, `binance-agentic-wallet` v1.12.0, cloned 2026-10-04)
- Swap syntax and the "orderId is not a completed swap — poll" rule: `references/market-order.md`. Wallet policy fields: `references/wallet-setting.md`. Fail-closed / no address hallucination / ask the provider: `SKILL.md`.
- Things that slowed us down (raw, for the report): the token-audit pre-check (`references/security.md`) depends on a separate skill (`query-token-audit`), and it has no data for stock tokens (F14). `limit-order --triggerPrice` is a per-token USD price, so on a multiplier-10 token a per-share target is off by 10×. The skill tells agents to "Determine support at runtime" for limit orders, and quotes an `Ondo-related tokens cannot be traded` error. Wallet settings "can only be changed in the Binance App", so an agent can read the limits but never set them.

Reading guide for the report: F1, F2, F6 and F12 are one theme — **how far can a client trust the reference price**. F9, F10, F11 and F13 are a second one — **the same API means different things per issuer**. Both lead to the redesign questions in the report.

## Still to write from first-hand use (the human report must cover these)
- Onboarding time from opening the docs to the first successful call, and where it stalled.
- AI stack section: Agentic Wallet / Wallet Skills / CLI — `baw` 1.10.0 was installed for F15 (2026-10-04) and is wired into `stockguard trade`; a signed-in run is still needed for first-hand sign-in, quote and swap experience.
- Transaction API dry-run pitfalls (needs an API key from the developer portal).
- Redesign suggestions and requested capabilities (candidates from this log: `referenceSource` field, `offhours` in the enum, a per-token `isTradeable` boolean, populated kline volume, one `sharesPerToken` value served identically by list and dynamic, a per-issuer `marketStatus` that is never null).

## Not yet verified (needs a weekday session and/or an API key)
- Behaviour during an actual `ASSET_PAUSED` (dividend/split) or `ASSET_LIMITED` (earnings) window.
- Order placement through the Agentic Wallet / Binance Web3 APIs (requires sign-in and funds).
