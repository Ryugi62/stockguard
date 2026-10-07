# Developer Experience Report — StockGuard (worksheet: the team member writes every ✍ answer in their own words)

> Organizer rule: "Specific and honest beats polite. Vague feedback doesn't count, and perfunctory or AI-generated reports won't be accepted."
> This worksheet holds **facts and pointers only**, in the order of the real form (https://forms.gle/EUQ39xf54GHjC2ys5: 7 sections, 46 questions, 31 required, read 2026-10-07). Every opinion, experience and recommendation is written by the human author at the ✍ marks. Nothing here is meant to be pasted.

## Step 0 — open the seven screens (3 min)

```bash
python3 scripts/reproduce_findings.py      # live public endpoints, no key, about 1 s
```

Look at each screen yourself before you write about it. The screens feed these questions:

| Screen | Finding | What to look at on the screen | Feeds form questions |
|---|---|---|---|
| 1 | F10 + F16 | `list multiplier: "1"` vs `dynamic sharesMultiplier: "10"` · `tokenInfo.price unchanged since recording: true` | 22, 28, 40 |
| 2 | F9 | `statusInfo.marketStatus: null` + `TRADING` for NFLXx and NFLXB | 22, 38, 40 |
| 3 | F12 | NFLXB `stockInfo.price: null` | 28, 39, 40 |
| 4 | F1 | `stockInfo.price x multiplier == tokenInfo.price: true` (session-dependent; weekend screenshot `screenshots/03-web-nflxon-weekend-warn.png`) | 16, 38, 39 |
| 5 | F2 | `undocumented offhours object: true` | 16, 22 |
| 6 | F7 | `candles with volume 0: 10` of 10 | 22, 36 |
| 7 | F14 | `hasResult: false` next to `riskLevelEnum: "LOW"` | 23, 32, 33 |

Raw notebook for every finding (F1–F16): `docs/dx-findings.md`. Screenshots: `docs/screenshots/01`–`05`.

---

## Section 1. Submission details (Q1–7, 3 min)
| Q | Question (form text) | Facts |
|---|---|---|
| 1 | Team or project name | StockGuard |
| 2 | Contact email | the same address as on the project submission |
| 3 | Public repository URL | https://github.com/Ryugi62/stockguard |
| 4 | Which Binance Web3 API modules or tools (inc. BNB) did you use? "Tick every module you actually called" | called: RWA Data API (list, dynamic, market status, meta) · Market API (token K-line) · Agentic Wallet / Wallet Skills (`baw` 1.10.0 installed; `wallet status`, `market-order quote` → `NOT_LOGGED_IN`, F15). Not called: Trading, Transaction, Wallet, DeFi, b402, Agent Studio |
| 5 | Team size | ✍ |
| 6 | Most experienced member: time building on Web3 | ✍ |
| 7 | Anyone used the Binance Web3 API before? | ✍ |

## Section 2. Onboarding (Q8–14, 5 min)
Facts: first code commit `afb8938`, 2026-10-03 13:49 KST (`git log --reverse | head -1`). The public RWA endpoints answered plain `curl` with no key. No developer-portal API key was obtained (the portal needs a Binance account sign-in). The `/v1` vs `/v2` split (F5).
- Q8 docs → first successful call: ✍ · Q9 API key time: ✍ · Q10 rating: ✍
- Q11 where exactly you got stuck (page, step, what you tried): ✍
- Q12 step that took longer than expected: ✍
- Q13 llms.txt / llms-full.txt: ✍ · Q14 what the AI agent got wrong (optional): ✍

## Section 3. Documentation issues (Q15–20, 4 min)
Q16 format is "page URL, section or heading, what is wrong, what it should say", one per line. Spots we checked:
| Page | Section | What the API did | Finding |
|---|---|---|---|
| https://github.com/binance/binance-skills-hub/blob/main/skills/binance-web3/binance-tokenized-securities-info/SKILL.md | L473, Stock Info table: `stockInfo.price` "May be null outside trading hours" | filled with token price ÷ multiplier | F1, screen 4 |
| same | L328, API 4 response fields: enum premarket … pause | `offhours` value (31 tokens, weekend) and an `offhours` object in market status | F2, screen 5 |
| binance-agentic-wallet SKILL.md, "Common Token Addresses" | `type=1` Ondo, `type=2` xStocks, `type=3` bStock | the tokenized-securities skill resolves `type=1` only | F13 |
- Q15 rating: ✍ · Q16 your lines: ✍ · Q17 missing topics: ✍ · Q18–19 examples: ✍ · Q20 most useful page (URL): ✍

## Section 4. API pitfalls (Q21–28, 7 min)
- Q22 edge cases (endpoint + request + what came back): screens 1, 2, 5, 6 → ✍
- Q23 unclear or misleading messages (exact text + endpoint): screen 7 (`riskLevelEnum: "LOW"` on a no-data audit) → ✍
- Q24 latency (optional): p50 74–111 ms, p95 130–189 ms, max 424 ms, n=10 per endpoint, 2026-10-04 (`data/latency-20261004.json`) → ✍
- Q25 rate limits: the 675-token scans of 2026-10-03/04 logged 0 request errors → ✍
- Q27 auth/signing (optional): no signed endpoint was called → ✍
- Q28 data you could not trust (optional): screens 1, 3; F11 (77/130 xStocks without a token price) → ✍
- Q21 reliability rating: ✍

## Section 5. AI stack feedback (Q29–34, 4 min)
Facts: `baw` 1.10.0 installed, not signed in; `--json` is listed only in `baw --help`, not per subcommand; `wallet status` → `UNCONNECTED`, `market-order quote` → `NOT_LOGGED_IN` (code 10003000) — F15, raw `fixtures/baw/`. StockGuard's gate follows `binance-agentic-wallet` v1.12.0 (`references/market-order.md`, `wallet-setting.md`, `security.md`). The audit that `security.md` requires before every swap has no data for 663/675 stock tokens — F14, screen 7. `limit-order --triggerPrice` is per token (10× off on NFLXon).
- Q29 parts used: ✍ · Q30 rating: ✍ · Q31 worked: ✍ · Q32 did not work (skill, command, how): ✍ · Q33 missing: ✍ · Q34 Agent Studio: not used → ✍

## Section 6. Tokenized-stock specifics (Q35–40, 5 min)
Facts: read all three issuers (Ondo 458, xStocks 130, bStocks 87 BSC tokens); no trade was executed (the form offers "None, my project did not execute trades").
- Q35 platforms: ✍ · Q36 liquidity depth: screen 6 (volume 0), F8 (NFLXon supply 220.99 tokens ≈ $148k on BSC) → ✍
- Q37 slippage: no trade was executed → ✍
- Q38 outside market hours: screens 2, 4; F2 → ✍ · Q39 on-chain vs reference gap: screens 3, 4; F6, F11 → ✍
- Q40 bStocks vs Ondo vs xStocks: screens 1, 2, 3; F13 (`python3 -m stockguard compare NFLX` after `pip install -e .`) → ✍

## Section 7. Redesign suggestions and requested capabilities (Q41–46, 9 min) — "The section we care about most"
Candidates from the log, each tied to a screen (choose, don't copy): a `referenceSource: live | last_close | derived` field (screens 1, 4) · one `sharesPerToken` served the same by list and price feed, per chain (screen 1) · a per-asset `marketStatus` that is never null, for every issuer (screen 2) · `offhours` in the docs (screen 5) · populated K-line volume (screen 6) · an audit response without a risk label when there is no result (screen 7) · the tokenized-securities skill resolving `type=2|3` (F13).
- Q41 redesign so a developer can call immediately after landing (what to cut, add, the first five minutes): ✍
- Q42 endpoints/SDK/tooling wanted, one per line + what you'd build: ✍
- Q43 the one change that would have saved the most time: ✍
- Q44–45 keep building, why: ✍ · Q46 anything else: ✍
