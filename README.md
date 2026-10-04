# StockGuard

**"Can I trade this tokenized stock right now — and what am I really buying?"**

A pre-trade safety layer for tokenized US stocks on BNB Chain, for people and for AI agents. It sits **in front of Binance Agentic Wallet**: before an agent calls `baw market-order swap` or `baw limit-order`, StockGuard answers `PROCEED`, `CONFIRM`, `ASK` or `REFUSE`, with plain-English reasons and the exact wallet commands in the right units. With a signed-in wallet, `stockguard trade` drives the whole order: preflight, gate, a re-check of the wallet's own quote, the user's typed yes, the swap, and polling until the order finishes or fails.

Covers all three issuers on BNB Chain, read through the Binance Web3 RWA Data API and the Token Security Audit API: **Ondo Global Markets** (`…on`, 458 tokens), **xStocks** (`…x`, 130) and **bStocks** (`…B`, 87).

## Judges: run it in one minute

```bash
git clone https://github.com/Ryugi62/stockguard && cd stockguard
python3 demo.py            # no install, no API key, no wallet, no network
python3 demo.py --live     # the same walkthrough on live public data
```

`demo.py` replays **recorded real responses** (`fixtures/recorded/demo-2026-10-04.json`, captured 2026-10-04 04:39 UTC by `scripts/record_demo_fixtures.py`). It runs in under a second. One token in it, `SPLITDEMOon`, is synthetic and labelled as such everywhere: it shows the stock-split `REFUSE` path, which can't be observed on a weekend. Python ≥3.9, standard library only.

What the demo shows:
1. "NFLX" is three different tokens: NFLXon is 10 Netflix shares per token, NFLXB is 1, and NFLXx is 1 or 10 depending on which endpoint you ask. StockGuard asks which one you mean instead of guessing.
2. `check NFLXon --usd 1000` → `WARN`: the US market is closed and the quoted stock price is derived from the token price itself.
3. An agent buying NFLXx → `REFUSE` on real data: the API gives two multipliers, and its supply (10,000) disagrees with the chain (100,000). No wallet command is emitted.
4. KLACon → `CONFIRM` with the `baw` quote and swap commands. The wallet skill's mandatory token audit has no data for any tokenized stock, so the user has to acknowledge.
5. "Sell when Netflix hits $75" → `baw limit-order sell --triggerPrice 750.00`. The trigger is per token, and NFLXon is 10 shares, so a $75 trigger would fire immediately.
6. A token paused for a stock split → `REFUSE` (synthetic scenario token).
7. The wallet's own `quotaLeft` is $250 → the order is cut from $500 to $250.

Every command also takes `--offline`, and `STOCKGUARD_OFFLINE=1` does the same.

## Four ways to use it

| Surface | For | Command (after `pip install -e .`, or `PYTHONPATH=src python3 -m stockguard …`) |
|---|---|---|
| Agentic Wallet gate | AI agents, before any swap or limit order | `stockguard gate KLACon --usd 1000 [--slippage 1] [--trigger-share-price 75 --side SELL] [--wallet-settings settings.json]` |
| Guarded trade | a person with a signed-in Agentic Wallet | `stockguard trade KLACon --usd 5` (runs `baw`; the wallet signs under its own limits) |
| MCP tools `guard_agentic_wallet_swap`, `check_tokenized_stock_trade` | LLM agents | `stockguard mcp` (stdio) |
| Web page | non-crypto users ("Why can't I buy NFLX right now?") | `stockguard serve` → http://127.0.0.1:8787 |
| CLI / library | bots, scripts | `stockguard check NFLXon --usd 1000` · `stockguard compare NFLX` |

## The Agentic Wallet gate (`src/stockguard/domain/wallet_gate.py`)

StockGuard never signs. `gate` prints the wallet commands; `trade` runs them through `baw` only after the gate and the user's typed yes, so the wallet still signs under its own limits. The verdict uses the same words as the wallet's own security settings (`references/wallet-setting.md`: `abnormalTxnHandling` = `AutoReject` | `NeedConfirmation`, `quotaLeft`, `tradeAllTokens`). It is an analogy: the wallet itself never sees StockGuard's verdict.

| StockGuard | Gate | Analogous wallet setting |
|---|---|---|
| `BLOCK` (halt, dividend/split pause, no token price, unverifiable token terms) | `REFUSE`, no command | `AutoReject` |
| `WARN` with risk ≥ 40 (earnings, unclear multiplier, big premium …) | `CONFIRM`: show the reasons, wait for an explicit yes | `NeedConfirmation` |
| `WARN` with risk < 40 (market closed, stale reference) | `PROCEED`, with the reasons as heads-up notes to show the user, so users don't learn to click through | — |
| `ALLOW` | `PROCEED` (the skill's normal per-trade confirmation still applies) | — |
| token audit unavailable / riskLevel 4 / riskLevel 5 or tax > 10% | `CONFIRM` (acknowledge) / `CONFIRM` / `REFUSE` | — |
| order > wallet `quotaLeft` | `CONFIRM` with the order cut (rounded down) to `quotaLeft`; under $1 left → `REFUSE` | daily limit |
| the wallet's quote is > 1% / > 5% worse than the token price (`trade`) | `CONFIRM` / stop before the swap | — |

Each rule follows the official skill text (`binance-skills-hub` commit `9960c675`, `skills/binance-web3/binance-agentic-wallet` v1.12.0 and `query-token-audit`):

| Skill text | What the gate does |
|---|---|
| "The same ticker often exists under more than one provider … **do not default to Ondo. Ask the user which provider they mean**" (SKILL.md) | bare ticker with several issuers → `ASK` + the choices with their multipliers |
| "Before `market-order swap`, `limit-order buy`, or `limit-order sell`, complete the pre-check in security.md" → token audit; "Security audit data is not available for this token on this chain." / "Token security audit is temporarily unavailable." → "Require explicit user acknowledgment" (references/security.md) | calls the public audit API for every order. Unavailable or unreachable → `CONFIRM` with those exact words; `riskLevel` 5 or tax > 10% → `REFUSE` (query-token-audit) |
| "**Fail-closed**: If the security check API is unreachable, inform the user and require acknowledgment" (SKILL.md) | applied to the audit as above. StockGuard applies the same principle to its own market data: if the list or price call fails → `REFUSE` |
| "**No address hallucination**: Never fabricate a contract address" (SKILL.md) | contract not in the RWA token list → `REFUSE`; the `toToken` address only ever comes from the list |
| "Confirm with the user each time before any state-changing command" (SKILL.md) | `CONFIRM` can't be skipped |
| `baw market-order quote/swap --fromTokenQty --fromToken --toToken --binanceChainId [--slippage] … --json` (references/market-order.md) | prints exactly these commands with full contract addresses; stablecoin amounts to the cent, SELL token amounts rounded down, BNB amounts converted at the given BNB price |
| `limit-order buy/sell --triggerPrice` = "USD price that activates the order" (references/limit-order.md); "never silently downgrade to immediate execution" (SKILL.md step 7) | converts a per-share target into the per-token trigger (refuses when the multiplier is disputed); if the wallet rejects the limit order, `trade` stops and never falls back to a market order |
| "For trades without explicit slippage, disclose the default ("auto")" (SKILL.md) | `--slippage` is passed through, or the disclosure note is added |
| "an orderId is NOT a completed swap — poll to a terminal state" (references/market-order.md) | the third command is the `market-order list --orderId` poll until `FINISHED` / `FAILED` |
| `wallet settings` → `quotaLeft`, `tradeAllTokens`, `quotaDate` (references/wallet-setting.md) | `--wallet-settings` takes that JSON as is (`trade` reads it live); flags settings from another day |
| `wallet status` → `CONNECTED` (references/wallet-view.md) | `trade` stops at preflight unless the wallet is connected; SELL checks `wallet balance` first |

## What it checks (domain rules, `src/stockguard/domain/guard.py`)

- **Market-wide halt**, **asset paused** (cash/stock dividend, split, merger, acquisition, spinoff, maintenance), or **no token price** → `BLOCK`
- **Earnings-limited** asset → `WARN`
- **US market closed**, or pre-market / after-hours / overnight / 24-7 off-hours trading → `WARN`
- **Multiplier ≠ 1** → `WARN` with the real share count ("1 token = 10 shares"). If you size the order in dollars, it becomes a note instead, because the dollar amount already uses the per-token price.
- **The API contradicts itself on the multiplier** (the token list and the price feed disagree by more than 1%) → `WARN`, with no premium from either value and the share count taken from the price ratio. Together with an API-vs-chain supply mismatch → `BLOCK` ("token terms can't be verified")
- **No market session reported** by the issuer (all xStocks/bStocks on weekends), or the market-wide session is pause / pre / post / overnight → `BLOCK` for a halt, `WARN` otherwise
- **No multiplier** in the payload → `WARN` (1 is only an assumption)
- **Premium/discount** against the independent stock price → `WARN` above 1%
- **No independent stock price** (it is just token price ÷ multiplier) → `WARN` ("any premium is invisible")
- **Large order**: more than 1% of all tokens on BNB Chain (`totalSupply()` over public BSC RPC) → note. Supply is not liquidity.
- **Risk score 0–100**, so warnings can be ranked: halt/pause/no price/unverifiable terms 100 · earnings 40 · multiplier conflict 30 · missing multiplier 30 · multiplier up to 30 · premium up to 40 (1 point per 0.1% beyond the threshold) · market closed 15 · no independent price 15 · outside regular hours 10 · no session reported 10.

## What we found on live data

Scans of every BSC stock token: 2026-10-03 (Ondo, 458 tokens, 7.4 s) and 2026-10-04 (all three issuers, 675 tokens, 13.8 s, 0 request errors).

- 432 of 458 Ondo tokens reported a weekend "stock price" equal to the token price ÷ multiplier, so premium checks read 0%.
- xStocks and bStocks reported `marketStatus: null` and `reasonCode: TRADING` for all 217 tokens on a Sunday, while Ondo said `closed`.
- For 39 of 130 xStocks, the token list and the price feed give different multipliers: NFLXx 1 vs 10, CRWDx 1 vs 4, TQQQx 1 vs 2.01, AZNx 1 vs 0.51. The supply is off by the same factor: NFLXx totalSupply on chain 100,000 vs API 10,000. 77 of 130 xStocks had no token price.
- The token security audit that the Agentic Wallet skill requires before every swap returned `hasResult: false, isSupported: false` for all 45 stock tokens we sampled (15 per issuer). USDT came back `riskLevel 3`.
- 38 tickers exist under all three issuers, with different terms. NFLX is 10 shares per token on Ondo and 1 on bStocks. CRWD is 4 and 1.
- Multiplier exposure (simple arithmetic on the real multipliers, not an observed agent): sizing "$1,000" by the per-share price instead of the per-token price buys **$10,026 of KLAC** or **$66.67 of ENLV** (`stockguard replay data/scan-20261003-weekend.jsonl`). On the `baw` market-order path a BUY is sized in USDT, so this bites in limit-order triggers and SELL quantities. The gate converts both.

The raw notebook with reproduction commands is `docs/dx-findings.md`. The skeleton for the human-written DX report is `docs/dx-report-TEMPLATE.md`.

## Use it from an agent (MCP)

```json
{ "mcpServers": { "stockguard": { "command": "python3", "args": ["-m", "stockguard", "mcp"],
  "env": { "PYTHONPATH": "/path/to/stockguard/src" } } } }
```
- `guard_agentic_wallet_swap({ticker, usd_amount, side?, pay_with?, slippage?, trigger_share_price?, pay_price?, wallet_settings?})` → action + reasons + audit + `baw_commands`
- `check_tokenized_stock_trade({ticker, side?, token_qty? | usd_amount?})` → `ALLOW | WARN | BLOCK` + reasons + share count + issuer attestation link

## Not in this build yet

A recorded live mainnet trade. `stockguard trade` is built and tested against a fake `baw` (`tests/test_trade.py`). Running it for real needs a signed-in Agentic Wallet with a few dollars in it.

## Architecture

`domain/` (pure rules: guard, wallet gate, quote check, issuers) ← `application/` (check, compare, scan, replay, gate_swap, guarded trade over a `WalletPort`) ← `adapters/` (Binance public RWA HTTP, token audit, BSC RPC, recorded/offline client, Agentic Wallet `baw` adapter, web, MCP stdio) ← `infrastructure/` (CLI, demo). The domain imports nothing from the other layers. Spec: `SPEC.md`.

## Tests

```
python3 -m pytest -q      # 94 tests, offline (fixtures are real recorded responses; `baw` is faked)
```

## Data source

Binance Web3 public tokenized-securities endpoints (`binance-skills-hub/binance-tokenized-securities-info`; list `type=1|2|3` from `binance-agentic-wallet`). Read-only. This is not investment advice.
