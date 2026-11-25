# Lean Spot strategy research lane (ADR-0032)

Deterministic, candle-based backtests of versioned rule-based strategies with a
pre-registered evaluation protocol. **Research evidence only** — no
qualification, approval or execution authority, and no order path.

## Run the first study (owner machine, needs internet)

```powershell
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -e .
python -m trading_platform_api.research fetch --start 2019-01-01
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
| FAIL if | expectancy ≤ 0 after costs, portfolio return ≤ 0 (cash baseline), portfolio max drawdown > 30%, or return/drawdown below buy-and-hold |
| PASS needs | none of the FAIL conditions, profit factor ≥ 1.20, bootstrap 5% lower bound of mean trade return > 0 |

The report records the dataset, strategy, protocol and cost digests. Changing
any rule or threshold needs a new strategy or protocol version — never edit
them after seeing a result.

## Data integrity

A candle file is rejected if it has a gap, a misaligned or unclosed candle,
inconsistent OHLC values, an unapproved symbol or a missing provenance header.
Nothing is repaired or interpolated. If a symbol's history has a gap, choose a
later `--start`.
