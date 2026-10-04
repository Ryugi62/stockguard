# Developer Experience Report — StockGuard (TEMPLATE: the team member writes every ✍ part in their own words)

> Organizer rule: "Specific and honest beats polite. Vague feedback doesn't count, and perfunctory or AI-generated reports won't be accepted."
> This file is a **skeleton**: section order, evidence pointers, reproduction steps and screenshots. Every sentence of opinion, experience or recommendation goes where the ✍ marks are, written by the human author. Delete this box and every "Evidence" list before submitting, or keep the lists as an appendix.
> Section order follows the organizer's own list of questions (blog post, 2026-09-16), with the question they "care about most" first.

---

## 1. If I were the engineer behind the developer platform, how would I rebuild it?  ← "the one we care about most"

✍ Your redesign (aim for 3–5 concrete changes, each one tied to a finding below, for example "what I'd change / why / what it would have saved me"):

✍ 1.

✍ 2.

✍ 3.

Evidence you can cite for each change (facts only — choose, don't copy):
- Reference price trust → F1 (432/458 derived), F6 (live vs stale vs derived can't be told apart), F12 (bStocks: no stock price at all) — screenshot `screenshots/03-web-nflxon-weekend-warn.png`
- One meaning per field across issuers → F9 (xStocks/bStocks `marketStatus: null` + TRADING on a Sunday), F10 (NFLXx multiplier 1 in the list vs 10 in the price feed, totalSupply 100,000 vs circulatingSupply 10,000) — screenshot `screenshots/05-raw-nflxx-list-vs-dynamic.png`
- Ticker → token resolution → F13 (38 tickers under all three issuers; NFLX = 10 shares on Ondo, 1 on bStocks); the tokenized-securities skill only knows `type=1` — screenshot `screenshots/01-web-nflx-is-three-tokens.png`
- Enum drift → F2 (`offhours` missing from the documented enum, SKILL.md L328)
- Liquidity signal → F7 (kline volume always "0")

## 2. Time from opening the docs to the first successful call, and where we got stuck

✍ Your timeline (fill the clock times from memory or browser history; be exact):

| Step | Clock time (KST) | What happened / where it stalled ✍ |
|---|---|---|
| Opened the docs (which page?) | ✍ | ✍ |
| First request sent | ✍ | ✍ |
| First successful call | ✍ | ✍ |
| First call that needed a key / sign-in | ✍ | ✍ |

Facts you can cite: our first code commit is `75e8cc7` (git log shows the time). The public RWA endpoints need no key and no special headers (plain `curl` returned 200 JSON, checked 2026-10-04). The `/v1` vs `/v2` split (F5).

## 3. Which page had the error, and where on it

✍ For each, say what you expected from the page and what you got:

| Doc page and spot | What it says | What the API did | Finding |
|---|---|---|---|
| tokenized-securities SKILL.md L473 (Stock Info table) | `stockInfo.price` "May be null outside trading hours" | filled with token price ÷ multiplier on 432/458 tokens | F1 |
| tokenized-securities SKILL.md L328 (API 4 response fields) | enum: premarket, regular, postmarket, overnight, closed, pause | `offhours` on 31 tokens | F2 |
| agentic-wallet SKILL.md "Common Token Addresses" | `type=1` Ondo, `type=2` xStocks, `type=3` bStock | tokenized-securities skill resolves `type=1` only | F13 |
| ✍ (any page you hit yourself) | ✍ | ✍ | ✍ |

## 4. Error messages that made no sense

✍ Paste each message exactly, say where you saw it, and what you thought it meant vs. what it meant:

- ✍
- (raw material) Our scan logs failures in `data/*.jsonl` under `"error"`; the 2026-10-04 scan had 0 errors across 675 tokens.

## 5. Edge cases that bit us — reproduction steps

Each one can be reproduced from a fresh clone with no key. Results move a little between scans.

| # | Reproduce | Expected | Actual (2026-10-03/04) |
|---|---|---|---|
| F1 | `PYTHONPATH=src python3 -m stockguard scan --out /tmp/s.jsonl` → count `reference_derived` | `stockInfo.price` null or a real quote on weekends | 432/458 Ondo tokens: exactly token price ÷ multiplier |
| F2 | same scan → `session == "offhours"` | value in the documented enum | 31 tokens `offhours` |
| F3 | `PYTHONPATH=src python3 -m stockguard replay data/scan-20261003-weekend.jsonl` | — | $1,000 intent → $10,026 KLAC / $66.67 ENLV (hypothetical naive bot) |
| F7 | `PYTHONPATH=src python3 -m stockguard kline NFLXon --limit 10` | volume > 0 on some candles | 100/100 candles volume "0" (10 tokens) |
| F9 | scan → `session == ""` grouped by `issuer` | a session per token | 130/130 xStocks, 87/87 bStocks: `marketStatus: null`, `TRADING`, Sunday |
| F10 | `PYTHONPATH=src python3 -m stockguard compare NFLX` | same multiplier in list and price feed | NFLXx 1 vs 10; 39/130 xStocks differ by >1% |
| F11 | scan → `token_price == null`, issuer xStocks | a token price | 77/130 |
| F12 | scan → `stock_price == null`, issuer bStocks | a stock price | 87/87 |
| F13 | `PYTHONPATH=src python3 -m stockguard check NFLX` | — | three tokens, NFLXon 10 shares, NFLXB 1 share → StockGuard asks |

✍ Which of these actually cost you time, and how much? Which one surprised you most?

## 6. What the latency looked like

Measured 2026-10-04 04:43 UTC from Korea, n=10 per endpoint (`PYTHONPATH=src python3 scripts/latency.py`, raw `data/latency-20261004.json`): p50 74–111 ms, p95 130–189 ms, max 424 ms. A full 675-token scan takes 13.8 s with 8 workers.

✍ Was this fast enough for what you built? Where did you need caching?

## 7. How the assets actually behaved

### Outside traditional market hours
✍ (material: F1, F2, F6, F9 — Ondo says `closed`/`offhours`, xStocks/bStocks say TRADING with no session)

### How the bStocks, Ondo and xStocks versions of the same thing differ in practice
✍ (material: F10, F12, F13 · `stockguard compare NFLX` output · screenshot `01`, `02`)

### Liquidity depth and slippage
✍ (material: F7 kline volume 0; F8 supply ≠ depth. Real slippage needs `baw market-order quote` from a signed-in wallet: ☐ fill after the live run)

## 8. AI stack

✍ What you used and how (Claude Code wrote most of the code — say so plainly; AI-assisted code is allowed):

✍ Agentic Wallet / Wallet Skills: what you installed, what worked, where it stalled. Material:
- StockGuard's gate is built from `binance-agentic-wallet` v1.12.0 (cloned 2026-10-04): swap syntax `references/market-order.md`, policy fields `references/wallet-setting.md`, fail-closed / no-address-hallucination / ask-the-provider rules from `SKILL.md`. MCP tool `guard_agentic_wallet_swap`.
- ☐ fill after the live run: sign-in time, `baw wallet settings --json` output (redact), quote → swap → poll result, tx hash.

## 9. What we'd ask for (requested capabilities)

✍ Your top 3, in order:

Candidates from our log: a `referenceSource: live | last_close | derived` field · `offhours` in the enum · one `sharesPerToken` value served the same way by list and dynamic · a per-asset `marketStatus` that is never null, for every issuer · populated kline volume · a per-token `isTradeable` boolean · the tokenized-securities skill resolving `type=2|3`.

---

### Appendix — screenshots (`docs/screenshots/`)
1. `01-web-nflx-is-three-tokens.png` — one ticker, three tokens, different multipliers
2. `02-web-nflxx-multiplier-conflict.png` — the API contradicts itself on NFLXx
3. `03-web-nflxon-weekend-warn.png` — weekend: derived reference price, market closed
4. `04-demo-terminal.png` — `python3 demo.py` (offline, recorded 2026-10-04)
5. `05-raw-nflxx-list-vs-dynamic.png` — raw `list/ai` vs `dynamic/ai` vs on-chain `totalSupply()` for NFLXx
