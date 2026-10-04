# StockGuard

**"Can I trade this tokenized stock right now — and what am I really buying?"**

A pre-trade safety layer for tokenized US stocks on BNB Chain, for people and for AI agents. It sits **in front of Binance Agentic Wallet**: before an agent calls `baw market-order swap`, StockGuard answers `PROCEED`, `CONFIRM`, `ASK` or `REFUSE`, with plain-English reasons and the exact wallet commands sized in the right units.

Covers all three issuers on BNB Chain, read through the Binance Web3 RWA Data API: **Ondo Global Markets** (`…on`, 458 tokens), **xStocks** (`…x`, 130) and **bStocks** (`…B`, 87).

## Judges: run it in one minute

```bash
git clone https://github.com/Ryugi62/bnb-hack-tokenized && cd bnb-hack-tokenized
python3 demo.py            # no install, no API key, no wallet, no network
python3 demo.py --live     # the same walkthrough on live public data
```

`demo.py` replays **recorded real responses** (`fixtures/recorded/demo-2026-10-04.json`, captured 2026-10-04 04:39 UTC by `scripts/record_demo_fixtures.py`). It runs in under a second. One token in it, `SPLITDEMOon`, is synthetic and labelled as such everywhere: it shows the stock-split `REFUSE` path, which can't be observed on a weekend. Python ≥3.9, standard library only.

What the demo shows, in five steps:
1. "NFLX" is three different tokens: NFLXon is 10 Netflix shares per token, NFLXB is 1, and NFLXx is 1 or 10 depending on which endpoint you ask. StockGuard asks which one you mean instead of guessing.
2. `check NFLXon --usd 1000` → `WARN`: the US market is closed and the quoted stock price is derived from the token price itself.
3. An agent buying "$1,000 of KLAC" by the per-share price would really buy $10,026. The gate sizes the order in dollars and returns the `baw` quote, swap and poll commands.
4. A token paused for a stock split → `REFUSE`, and no wallet command is emitted.
5. The wallet's own `quotaLeft` is $250 → the order is cut from $500 to $250 and needs confirmation.

Every command also takes `--offline`, and `STOCKGUARD_OFFLINE=1` does the same.

## Four ways to use it

| Surface | For | Command (after `pip install -e .`, or `PYTHONPATH=src python3 -m stockguard …`) |
|---|---|---|
| Agentic Wallet gate | AI agents, before any swap | `stockguard gate KLACon --usd 1000 [--wallet-settings settings.json]` |
| MCP tools `guard_agentic_wallet_swap`, `check_tokenized_stock_trade` | LLM agents | `stockguard mcp` (stdio) |
| Web page | non-crypto users ("Why can't I buy NFLX right now?") | `stockguard serve` → http://127.0.0.1:8787 |
| CLI / library | bots, scripts | `stockguard check NFLXon --usd 1000` · `stockguard compare NFLX` |

## The Agentic Wallet gate (`src/stockguard/domain/wallet_gate.py`)

StockGuard never signs and never calls the wallet. It turns its verdict into the vocabulary the wallet already uses for its own security settings (`references/wallet-setting.md`: `abnormalTxnHandling` = `AutoReject` | `NeedConfirmation`, `quotaLeft`, `tradeAllTokens`):

| StockGuard | Gate | Same effect as |
|---|---|---|
| `BLOCK` (halt, dividend/split pause, no token price) | `REFUSE`, no command | `AutoReject` |
| `WARN` | `CONFIRM`: show the reasons, wait for an explicit yes, even if the user asked to skip confirmations | `NeedConfirmation` |
| `ALLOW` | `PROCEED` (the skill's normal per-trade confirmation still applies) | — |
| order > wallet `quotaLeft` | `CONFIRM` with the order reduced to `quotaLeft`; `quotaLeft` 0 → `REFUSE` | daily limit |

Each rule follows the official skill text (`binance-skills-hub/skills/binance-web3/binance-agentic-wallet`, v1.12.0):

| Skill text | What the gate does |
|---|---|
| "The same ticker often exists under more than one provider … **do not default to Ondo. Ask the user which provider they mean**" (SKILL.md) | bare ticker with several issuers → `ASK` + the choices with their multipliers |
| "**Fail-closed**: If the security check API is unreachable, inform the user and require acknowledgment" (SKILL.md) | market data unavailable → `REFUSE` |
| "**No address hallucination**: Never fabricate a contract address" (SKILL.md) | contract not in the RWA token list → `REFUSE`; the `toToken` address only ever comes from the list |
| "Confirm with the user each time before any state-changing command" (SKILL.md) | `CONFIRM` can't be skipped |
| `baw market-order quote/swap --fromTokenQty --fromToken --toToken --binanceChainId … --json` (references/market-order.md) | prints exactly these commands, with full addresses; USD amounts to 2 decimals; SELL token amounts rounded down |
| "an orderId is NOT a completed swap — poll to a terminal state" (references/market-order.md) | the third command is the `market-order list --orderId` poll until `FINISHED` / `FAILED` |
| `wallet settings` → `quotaLeft`, `tradeAllTokens` (references/wallet-setting.md) | `--wallet-settings` takes that JSON as is |

## What it checks (domain rules, `src/stockguard/domain/guard.py`)

- **Market-wide halt**, **asset paused** (cash/stock dividend, split, merger, acquisition, spinoff, maintenance), or **no token price** → `BLOCK`
- **Earnings-limited** asset → `WARN`
- **US market closed**, or pre-market / after-hours / overnight / 24-7 off-hours trading → `WARN`
- **Multiplier ≠ 1** → `WARN` with the real share count ("1 token = 10 shares"). If you size the order in dollars, it becomes a note instead, because the dollar amount already uses the per-token price.
- **The API contradicts itself on the multiplier** (the token list and the price feed disagree by more than 1%) → `WARN`, and no premium is computed from either value
- **Premium/discount** against the independent stock price → `WARN` above 1%
- **No independent stock price** (it is just token price ÷ multiplier) → `WARN` ("any premium is invisible")
- **Large order**: more than 1% of all tokens on BNB Chain (`totalSupply()` over public BSC RPC) → note. Supply is not liquidity.
- **Risk score 0–100**, so warnings can be ranked: halt/pause/no price 100 · earnings 40 · multiplier conflict 30 · multiplier up to 30 · premium up to 40 · market closed 15 · no independent price 15 · outside regular hours 10.

## What we found on live data

Scans of every BSC stock token: 2026-10-03 (Ondo, 458 tokens, 7.4 s) and 2026-10-04 (all three issuers, 675 tokens, 13.8 s, 0 request errors).

- 432 of 458 Ondo tokens reported a weekend "stock price" equal to the token price ÷ multiplier, so premium checks read 0%.
- xStocks and bStocks reported `marketStatus: null` and `reasonCode: TRADING` for all 217 tokens on a Sunday, while Ondo said `closed`.
- For 39 of 130 xStocks, the token list and the price feed give different multipliers: NFLXx 1 vs 10, CRWDx 1 vs 4, TQQQx 1 vs 2.01, AZNx 1 vs 0.51. 77 of 130 xStocks had no token price.
- 38 tickers exist under all three issuers, with different terms. NFLX is 10 shares per token on Ondo and 1 on bStocks. CRWD is 4 and 1.
- In a replay, a hypothetical agent that buys "$1,000 worth" by the per-share price ends up with **$10,026 of KLAC** or **$66.67 of ENLV** (`stockguard replay data/scan-20261003-weekend.jsonl`).

The raw notebook with reproduction commands is `docs/dx-findings.md`. The skeleton for the human-written DX report is `docs/dx-report-TEMPLATE.md`.

## Use it from an agent (MCP)

```json
{ "mcpServers": { "stockguard": { "command": "python3", "args": ["-m", "stockguard", "mcp"],
  "env": { "PYTHONPATH": "/path/to/bnb-hack-tokenized/src" } } } }
```
- `guard_agentic_wallet_swap({ticker, usd_amount, side?, pay_with?, wallet_settings?})` → action + reasons + `baw_commands`
- `check_tokenized_stock_trade({ticker, side?, token_qty? | usd_amount?})` → `ALLOW | WARN | BLOCK` + reasons + share count + issuer attestation link

## Not in this build

The live signed trade: gate → `baw market-order quote` → Agentic Wallet signature → small BSC mainnet buy. It needs a signed-in Agentic Wallet with a few dollars in it. The gate already prints the exact commands, so the remaining step is running them from a funded wallet.

## Architecture

`domain/` (pure rules: guard, wallet gate, issuers) ← `application/` (check, compare, scan, replay, gate_swap) ← `adapters/` (Binance public RWA HTTP, BSC RPC, recorded/offline client, `baw` command renderer, web, MCP stdio) ← `infrastructure/` (CLI, demo). The domain imports nothing from the other layers. Spec: `SPEC.md`.

## Tests

```
python3 -m pytest -q      # 64 tests, offline (fixtures are real recorded responses)
```

## Data source

Binance Web3 public tokenized-securities endpoints (`binance-skills-hub/binance-tokenized-securities-info`; list `type=1|2|3` from `binance-agentic-wallet`). Read-only. This is not investment advice.
