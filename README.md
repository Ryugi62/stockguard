# StockGuard

**"Can I trade this tokenized stock right now — and what am I really buying?"**

Tokenized US stocks on BNB Chain trade 24/7. The underlying stocks do not. Corporate actions pause single tokens, and one token is often not one share: NFLXon is 10 Netflix shares, ENLVon is 0.067 of an Enlivex share. StockGuard sits in front of any trade, whether a person or an agent places it, and answers with `ALLOW`, `WARN` or `BLOCK` plus reasons in plain English.

It ships three ways:

| Surface | For | Command |
|---|---|---|
| Web page | non-crypto users ("Why can't I buy NFLX right now?") | `python3 -m stockguard serve` → http://127.0.0.1:8787 |
| MCP tool `check_tokenized_stock_trade` | LLM agents | `python3 -m stockguard mcp` (stdio) |
| Python library / CLI | trading bots | `python3 -m stockguard check NFLX BUY 1` |

Run from the repo root with `PYTHONPATH=src`. It needs Python ≥3.9 and the standard library only. There are no API keys and no wallet, because StockGuard never signs anything.

## What it checks (domain rules, `src/stockguard/domain/guard.py`)

- **Market-wide halt** or **asset paused** for a cash dividend, stock dividend, split, merger, acquisition, spinoff or maintenance → `BLOCK`
- **Earnings-limited** asset → `WARN`
- **US market closed** → `WARN` (the reference price is stale)
- **Multiplier ≠ 1** → `WARN` with the real share count ("1 token = 10 shares")
- **Premium/discount** against the independent stock price → `WARN` above a threshold (default 1%)
- **No independent stock price**, because the API quotes `token price ÷ multiplier` as the stock price → `WARN` ("any premium is invisible")

## What we found on live data (2026-10-03, 458 BSC tokens, scan in 7.3 s)

- 427 of 458 tokens reported a weekend "stock price" equal to the token price divided by the multiplier. Premium checks based on it always read 0%.
- 31 tokens reported `marketStatus: "offhours"`, a value missing from the documented enum, while the market-wide status said `closed`.
- 11 tokens have multipliers ≥2 or <0.2. In a replay, an agent that buys "$1,000 worth" by reading the per-share price ends up holding **$10,026 of KLAC** or **$66.67 of ENLV**: `python3 -m stockguard replay data/scan-20261003-weekend.jsonl`.

Evidence and reproduction steps: `docs/dx-findings.md`.

## Architecture

`domain/` (pure rules) ← `application/` (check, scan, replay) ← `adapters/` (Binance public RWA HTTP client, JSON mapping, web, MCP stdio) ← `infrastructure/` (CLI). The domain imports nothing from the other layers. Spec: `SPEC.md`.

## Tests

```
python3 -m pytest -q      # 24 tests, offline, fixtures from real responses in fixtures/
```

## Data source

Binance Web3 public tokenized-securities endpoints (`binance-skills-hub/binance-tokenized-securities-info`). Read-only. This is not investment advice.
