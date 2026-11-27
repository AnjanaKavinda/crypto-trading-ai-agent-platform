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

## Strategy A study: `trend-daily-regime` v1, protocol v2 (E2e)

Pre-registered on #516 (2026-11-26) before any result existed. Run once:

```powershell
python -m trading_platform_api.research fetch --timeframe 1d --start 2021-09-30
python -m trading_platform_api.research run --strategy trend-daily-regime --protocol v2 --timeframe 1d
```

| Item | Value |
|---|---|
| Strategy | trend state `EMA20 > EMA50 AND close > SMA200` at the daily close; enter at the next open when the state turns true; initial stop entry − 3×ATR14; trailing stop `max(stop, highest close since entry − 3×ATR14)`, never lowered; exit at the next open when EMA20 < EMA50; no take-profit |
| Protocol | `spot-walk-forward-prospective` v2 |
| Judged | development era: data from 2021-09-30 (indicator warm-up first, so trading starts 2022-04-18) up to the 2025-05-11 daily bar |
| Criteria | all v1 criteria pooled across symbols on the whole era, **plus** positive pooled expectancy in at least 3 of 4 consecutive equal windows (a trade counts in the window of its entry bar) |
| Result | HISTORICAL_PASS / FAIL / INCONCLUSIVE |
| Not judged | 2025-05-12 → 2026-11-25 is reported as `CONTAMINATED_INFORMATIONAL`; bars from 2026-11-26 are counted, never evaluated |

Only a HISTORICAL_PASS moves to the prospective stage (signals recorded
forward; review at 15 trades or 6 months). Other strategy/protocol pairs are
refused (fail closed). Chart markers: see `strategy=trend-daily-regime` below.

## Strategy B study: `range-reversion-4h` v1, protocol v2 (E2f)

Pre-registered on #516 (2026-11-26) before any result existed. Run once:

```powershell
python -m trading_platform_api.research fetch --timeframe 4h --start 2021-09-30
python -m trading_platform_api.research run --strategy range-reversion-4h --protocol v2 --timeframe 4h
```

| Item | Value |
|---|---|
| Strategy | enter at the next open when at the 4h close `ADX14 < 20 AND close < lower Bollinger band (20, 2σ population) AND RSI14 < 30`; fixed stop entry − 1.5×ATR14; exit at the next open after a close ≥ the middle band (SMA20), or after 12 held bars (time stop, entry bar counted); no take-profit |
| Indicators | RSI14 (Wilder) and Bollinger (20, 2σ population) equal the platform's registered methods exactly (parity test); ADX14 is the standard Wilder definition (no platform method yet; hand-computed test) |
| Protocol | `spot-walk-forward-prospective` v2, same criteria and periods as Strategy A, on 4h bars |
| Prospective review | 30 trades or 3 months, only after a HISTORICAL_PASS |

Chart markers: `GET /api/research/spot/{instrument}/strategy-markers?timeframe=4h&limit=500&strategy=range-reversion-4h&version=1`
(4h snapshots only). BUY markers list ADX14, close vs lower band and RSI14 at the
signal close; SELL markers explain the middle-band exit, the 12-bar time stop
(`TIME_EXIT`, with bars held) or the stop. The served RSI14 and Bollinger values
must equal the research formulas or no markers are returned; ADX14 is recomputed
from the snapshot's validated candles.

## Candidate tournament: `spot-candidate-tournament` v1 (E2t)

Pre-registered on #516 (comment 7203109547, "tournament OK") with Amendment 1
(gold, `owner-answer:tournament-gold`) before any result existed. Research
only; no tuning; no extra candidates. Run once, in this order, from the repo
root on the owner's machine (internet needed for the fetches):

```powershell
# S1 (5 approved coins) from 2021-09-30
python -m trading_platform_api.research fetch --timeframe 1d --start 2021-09-30
# S2 (8 research-only coins) and S5 gold, same dates
python -m trading_platform_api.research fetch --research-only --timeframe 1d --start 2021-09-30 --symbols ADAUSDT,DOGEUSDT,LTCUSDT,LINKUSDT,AVAXUSDT,DOTUSDT,TRXUSDT,BCHUSDT,PAXGUSDT
# S3 earlier history: BTC and ETH from their first Binance daily candle
python -m trading_platform_api.research fetch --research-only --timeframe 1d --start 2017-01-01 --symbols BTCUSDT,ETHUSDT --data research-data/early
# The tournament: one JSON + one Markdown report in research-output/
python -m trading_platform_api.research tournament --protocol tournament-v1
```

A fetch that fails its data checks writes no file for that symbol, prints
`not written (fail closed)` and exits 1. The other symbols are still written.
The tournament then reports that S2 coin as excluded, or S3 / S5 as
`UNAVAILABLE`; no substitute coin or date is used. A missing or failing S1 coin
stops the run.

| Item | Value |
|---|---|
| Candidates (k = 9) | C1 `sma200-long-cash`, C2 `ema-cross-1d`, C3 `donchian-20-10`, C4 `tsmom-28d`, C5 `tsmom-84d`, C6 `rsi2-uptrend`, C7 `bb-reversion-1d`, C8 `sma200-voltarget` (fractional position, rest in cash), C9 `trend-daily-regime` v1 (reference) |
| Execution | 1d, long-only, signal at close, fill at next open, 10 bps fee + 5 bps slippage per side, equal-weight never-rebalanced portfolio; each candidate is judged only after its indicators exist |
| S1 (seen) | BTC, ETH, BNB, SOL, XRP, 2021-09-30 → 2025-05-11, 4 equal windows. **H1:** expectancy > 0, ≥ 3 of 4 windows positive, portfolio DD ≤ 30%, every coin DD ≤ 40%, return/DD ≥ buy-and-hold's, ≥ 30 trades |
| S2 (unseen coins) | ADA, DOGE, LTC, LINK, AVAX, DOT, TRX, BCH, same dates. **H2:** expectancy > 0 with the Bonferroni bootstrap lower bound > 0 (one-sided 5%/9, 20,000 resamples, seed 20261127, sorted index 111), return/DD ≥ buy-and-hold's, portfolio DD ≤ 30%, ≥ 30 trades |
| S3 (earlier history) | BTC and ETH from the later of their first daily candles to 2021-09-29. **H3:** expectancy > 0, return/DD ≥ buy-and-hold's, ≥ 10 trades |
| S4 (seen) | 2025-05-12 → 2026-11-25 on the S1 coins, informational only |
| S5 (gold) | PAXGUSDT on S1 dates, judged on its own: GOLD_PASS / GOLD_FAIL / GOLD_INCONCLUSIVE (expectancy > 0, return/DD ≥ PAXG buy-and-hold's, ≥ 10 trades), weekend/weekday entry split for information, plus S4-style figures |
| Verdict | INCONCLUSIVE if S1 or S2 has < 30 trades; else TOURNAMENT_PASS (H1, H2, H3), PROVISIONAL_PASS (H1, H2, S3 `UNAVAILABLE`) or FAIL |

The research-only symbols are accepted only with `--research-only` and by the
tournament; the chart, Today screen, daily check and refresh path stay on the
five approved coins. Passing candidates go to forward paper tracking with a
6-month review; only a forward pass could justify real money. If none passes,
these simple rules show no defensible edge on Binance Spot after costs.
Post the report's verdict table on #516 (queue item O5).

## Forward (prospective) stage (E2f2)

`research/forward.py` replays each candidate's frozen rules over candles from
2026-11-26 onward (indicators may warm up on earlier candles) and reports every
signal and outcome as **SIMULATED**: fill at the next open plus slippage, the
strategy's own stop/exit rules and fees. Never an order.

Stage status comes only from the pre-registered rules: no recorded historical
verdict → `NOT_VALIDATED`; historical FAIL → `FAIL`; HISTORICAL_PASS →
`FORWARD_TESTING` until the review point (A: 15 trades or 6 months; B: 30 trades
or 3 months, whichever first), then `FORWARD_PASS` if pooled expectancy after
costs > 0 and the forward portfolio max drawdown ≤ 1.5 × the historical one,
else `FAIL`. The historical verdict is read from the owner's study report only
if its strategy and protocol digests match exactly (owner decision on #516:
import the report).

Import a study report once it has been run (the local stack must be up):

```powershell
python -m trading_platform_api.research record-verdict research-output\<report>.json
```

The API stores it append-only as C-109 (an identical re-import returns the same
record). `GET /api/research/forward/trend-daily-regime` (or
`range-reversion-4h`) then returns the SIMULATED forward signals, stats and
stage.

**Forward history (E2f2 part 3).** Every forward replay starts at a fixed
warm-up candle: the prospective start minus the strategy's warm-up bars
(A: 2026-05-10 on 1d; B: 2026-11-21 12:00 UTC on 4h), so it is identical each
time it is recomputed. One snapshot holds at most 501 candles (and one refresh
below 1d at most 90 days), so the API stitches the history from several persisted snapshots;
overlapping snapshots must agree exactly and any missing candle fails closed
(`FORWARD_HISTORY_INSUFFICIENT`, naming the uncovered date). The daily check
refreshes any missing historical window back to the warm-up start in fixed,
aligned windows (1d: 501 candles, 4h: 480 candles), then reads both forward
stages and reports them.

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

`GET /api/research/spot/{instrument}/strategy-markers?timeframe=4h&limit=500&strategy=ema-trend-atr-stop&version=1`
replays the named strategy version over the latest persisted snapshot and returns
BUY/SELL markers with their conditions, EMA20/EMA50/ATR14 values and labelled
fields (`VERIFIED_FACT`, `RESEARCH_PROPOSAL`, `NOT_APPLICABLE`, `UNAVAILABLE`).
Add `account_size` (USDT) and `risk_pct` for a position size:
(account × risk%) ÷ (entry − stop), capped at account ÷ entry (Spot, no
leverage). Stale or invalid data, or any indicator mismatch, returns no
markers. Markers cover one snapshot only and are not a strategy verdict.

`strategy` and `version` are required (422 `STRATEGY_REQUIRED` otherwise);
there is no default strategy. Every response carries `study_verdict`: the
latest study report imported with `research record-verdict` for that exact
strategy digest (`FAIL`, `INCONCLUSIVE` or `HISTORICAL_PASS`, with reasons),
`NO_RESULT_RECORDED` when none was imported, or `UNAVAILABLE` with a reason
when the verdict store cannot be read. `ema-trend-atr-stop` v1 (FAIL,
2026-11-26) was judged under protocol v1, which cannot be imported, so it
always reports `NO_RESULT_RECORDED`.

## Daily research check (E2c3)

With the local stack running (`http://127.0.0.1:5173`):

```powershell
.venv\Scripts\python -m trading_platform_api.research daily-check
# or: powershell -ExecutionPolicy Bypass -File scripts\daily-research-check.ps1
```

It explicitly refreshes 4h (501 candles) and 1d (501 candles; daily refreshes
are bounded by candle count, not by the 90-day window used below 1d) for BTC, ETH, BNB, SOL and XRP through the same local web
endpoint and headers the browser uses, then checks that each snapshot's quality
is `VALID` and `CURRENT`, that EMA 20/50/500, ATR 14, Bollinger 20 and RSI 14
are `AVAILABLE` on both timeframes (501 candles warm up EMA 500 and give
Strategy A's SMA200 enough history), and that the decision-journal and strategy-signal
reads return 200. It writes `research-output/daily-check-<UTC date>.md` with
READY/PROBLEM per check and exits `1` on any PROBLEM. It only refreshes and
reads: it never records a decision, journal entry or outcome.

**Windows Task Scheduler** (daily, after the 00:00 UTC daily close, e.g.
06:00 Asia/Colombo):

1. Task Scheduler → *Create Task…* → name `Daily research check`; *Run only
   when user is logged on* (the Docker stack runs in your session).
2. *Triggers* → *New…* → Daily, 06:00.
3. *Actions* → *New…* → Program `powershell.exe`, arguments
   `-NoProfile -ExecutionPolicy Bypass -File "<repo>\scripts\daily-research-check.ps1"`,
   start in `<repo>`.
4. *Settings* → *Run task as soon as possible after a scheduled start is
   missed*.

The task's *Last Run Result* is `0x0` when everything is READY and `0x1` when
the report lists a PROBLEM.

`strategy=trend-daily-regime&version=1` replays Strategy A instead, on `1d`
snapshots only (other timeframes return `TIMEFRAME_NOT_PRE_REGISTERED` and no
markers). BUY markers show the trend-state transition (EMA20, EMA50, close and
SMA200 at the signal and the previous close); STOP exits show the trailing
stop in effect and the initial stop; an open position reports `current_stop`
for the next candle. SMA200 is recomputed from the snapshot's validated
candles. Any other strategy/version pair is refused with `422
STRATEGY_NOT_REGISTERED`. Use `limit` ≥ 202 so SMA200 is warmed up and one candle can trade.
