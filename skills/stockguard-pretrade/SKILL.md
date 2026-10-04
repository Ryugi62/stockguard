---
name: stockguard-pretrade
description: |
  Use before ANY Binance Agentic Wallet trade of a tokenized US stock on BNB Chain (Ondo …on, xStocks …x, bStocks …B):
  `baw market-order swap`, `baw limit-order buy|sell`. Adds the stock-specific pre-check that the wallet's token audit
  can't do (the audit returns no data for 663 of 675 stock tokens): market session, dividend/split pauses, shares per
  token, disputed multipliers, issuer choice for a bare ticker, limit triggers in token units, daily quota.
metadata:
  requires: python3 >= 3.9, this repository (`pip install -e .` gives the `stockguard` command)
---

# StockGuard pre-trade gate (for agents that use binance-agentic-wallet)

Run this **after** `binance-agentic-wallet`'s preflight and **instead of** building the swap command yourself:

```bash
baw wallet settings --json > /tmp/aw-settings.json
stockguard gate <SYMBOL> --usd <amount> [--side SELL | --tokens <qty>] [--slippage <pct>] \
  [--trigger-share-price <price per share>] --wallet-settings /tmp/aw-settings.json
```
(Or the MCP tool `guard_agentic_wallet_swap` from `stockguard mcp`.)

Act on `action`:
| action | what you do |
|---|---|
| `REFUSE` | Do not trade. Tell the user every line of `reasons`. |
| `ASK` | The ticker is several tokens (`choices`, with shares per token). Ask the user which one. Never pick for them. |
| `CONFIRM` | Show `reasons` (and `notes` starting with "Heads-up"), wait for an explicit "yes". This replaces the separate audit acknowledgment. |
| `PROCEED` | Normal binance-agentic-wallet confirmation, then run `baw_commands` in order. |

Then run `baw_commands` exactly as given: quote → swap → poll `market-order list --orderId` until `FINISHED`/`FAILED`
(or the limit order, then `limit-order list --strategyId`). If a limit order is rejected, stop — never fall back to a
market order. Report CLI errors word for word.

`stockguard trade <SYMBOL> --usd <amount>` does all of the above itself with a typed yes.
