# Lean Spot strategy research lane (ADR-0032)

Deterministic, candle-based backtests of versioned rule-based strategies with a
pre-registered evaluation protocol. **Research evidence only** — no
qualification, approval or execution authority, and no order path.

## Run the first study (owner machine, needs internet)

```powershell
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -e .
python -m trading_platform_api.research fetch --start 2021-09-30
python -m trading_platform_api.research run
```

`fetch` downloads closed public 4h klines for the five approved Spot symbols
from Binance's public market-data endpoint (no API key) into `research-data/`.
`run` writes a JSON report and a Markdown summary into `research-output/` and
prints the verdict. Both folders are git-ignored.

## What is fixed before you look at results

| Item | Value |
|---|---|
| Strategy | `ema-trend-atr-stop` v1: long when EMA20 crosses above EMA50, 2×ATR14 initial stop, exit on cross below; signal at bar close, fill next bar open |
| Costs | 10 bps fee + 5 bps slippage per side (assumption) |
| Split | last 30% of the common history is the holdout; only the holdout is judged |
| Sample | at least 30 pooled holdout trades, else INCONCLUSIVE |
| FAIL if | expectancy ≤ 0 after costs, portfolio return ≤ 0 (cash baseline), portfolio max drawdown > 30%, any single coin's max drawdown > 40% (whole equity in that coin), or return/drawdown below buy-and-hold |
| PASS needs | none of the FAIL conditions, profit factor ≥ 1.20, bootstrap 5% lower bound of mean trade return > 0 |

The report records the dataset, strategy, protocol and cost digests. Changing
any rule or threshold needs a new strategy or protocol version — never edit
them after seeing a result.

## Protocol v2 rule: the v1 holdout is now seen

The first real-data study (2026-11-26, `ema-trend-atr-stop` v1, verdict FAIL)
judged the holdout **2025-05-12T12:00Z → 2026-11-25T12:00Z**. That period is
now **seen**: it informed the owner's view of the strategy and can no longer
give an unbiased verdict.

From protocol v2 onwards:

- A new strategy version (or changed rule, parameter, cost or threshold) is
  developed and tuned only on data **before 2025-05-12T12:00Z**.
- It is judged only on data it has never seen: either a **walk-forward**
  split inside the pre-holdout history fixed before running, or a
  **prospective** period starting after the version is frozen (candles after
  2026-11-25T12:00Z).
- A verdict computed on the seen v1 holdout is reported as **in-sample /
  exploratory**, never as PASS evidence.
- The protocol version, the development cut-off and the judged period are
  written down before the study runs.

## Calculation verification (E2d)

`tests/backend/test_research_calculation_verification.py` (synthetic candles):

- **Parity:** `research.indicators` EMA20/EMA50 and Wilder ATR14 equal the
  registered platform calculators (`analysis/moving_averages.py`,
  `analysis/volatility.py`) exactly on the same candles.
- **Golden backtest:** three hand-computed trades — entry at next open plus
  5 bps slippage, 2×ATR stop, a signal exit, a gap-through stop filled at the
  open, a stop hit on the entry bar, 10 bps fees on both sides, net return,
  R multiple and final equity.

## Data integrity

A candle file is rejected if it has a gap, a misaligned or unclosed candle,
inconsistent OHLC values, an unapproved symbol or a missing provenance header.
Nothing is repaired or interpolated. If a symbol's history has a gap, choose a
later `--start`.

**Known Binance outage candles.** Binance 4h Spot history contains outage
candles that end early (their `close_time_ms` is before the regular 4h close)
up to 2021-09-29 04:00 UTC. They are rejected with a
`close_time_ms does not match` error naming the symbol and the candle's UTC
open time. Use `--start 2021-09-30` to begin after them:

```powershell
python -m trading_platform_api.research fetch --start 2021-09-30
```

## Strategy markers on the chart (E3)

`GET /api/research/spot/{instrument}/strategy-markers?timeframe=4h&limit=500`
replays `ema-trend-atr-stop` v1 over the latest persisted snapshot and returns
BUY/SELL markers with their conditions, EMA20/EMA50/ATR14 values and labelled
fields (`VERIFIED_FACT`, `RESEARCH_PROPOSAL`, `NOT_APPLICABLE`, `UNAVAILABLE`).
Add `account_size` (USDT) and `risk_pct` for a position size:
(account × risk%) ÷ (entry − stop), capped at account ÷ entry (Spot, no
leverage). Stale or invalid data, or any indicator mismatch, returns no
markers. Markers cover one snapshot only and are not a strategy verdict.
