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

## Futures data (E11a, research only)

The owner-approved E11 slice fetches public USD-M perpetual 1h klines,
settled funding rates and 1h premium-index klines, together with matching Spot
1h candles. Run from the repository root, on the owner's machine:

```powershell
python -m trading_platform_api.research fetch --market um-futures --timeframe 1h --start 2021-09-30 --symbols BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT --data research-data/futures
# Standalone Spot fetch also supports these five symbols at 1h:
python -m trading_platform_api.research fetch --timeframe 1h --start 2021-09-30 --symbols BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT --data research-data/futures/spot
```

The first command validates all four files for each symbol before writing:
`spot/<SYMBOL>_1h.csv`, `um-futures/<SYMBOL>_klines_1h.csv`,
`um-futures/<SYMBOL>_premium_1h.csv`, and
`um-futures/<SYMBOL>_funding_8h.csv`. Existing Spot CSV format and digest
semantics stay unchanged. Futures headers include `source`, `venue=BINANCE-USDM`,
`symbol`, `dataset`, `interval`, `fetched_at` and `content_sha256` (hash of the
UTF-8 document with the ` content_sha256=...` header field removed).
Futures files use LF bytes on every operating system so the stored digest
matches the saved bytes on Windows as well. Explicit timezone offsets in a
Futures `--start` timestamp are converted to UTC, not discarded.

The request ends at the latest fully closed UTC hour at fetch time; current
open candles are outside the requested range. Missing/duplicate/off-grid rows,
unclosed candles, mismatched close times or Spot/perpetual alignment failures
reject the symbol with a UTC diagnostic and write none of its files; other
symbols continue. Funding must cover every 00/08/16 UTC settlement strictly
before that boundary. Non-8h historical regimes are rejected, never resampled.
Premium values are dimensionless rates and may be negative or zero.
Provider access failures also fail closed. Existing files are preserved on a
validation failure; remove or archive old files explicitly before an owner run
if a clean output directory is needed. No data is repaired or date shifted.

These are research-only inputs; no Futures symbol is added to the UI approved
list. No keys or exchange account are used. #570's carry simulation starts only
after #569 is merged; the fetch does not run or evaluate that study.

## Futures carry study (E11b, simulation only)

`funding-carry-8h` v1 / `futures-carry-holdout` v1 implements the
[binding preregistration](https://github.com/AnjanaKavinda/crypto-trading-ai-agent-platform/issues/516#issuecomment-7219026152).
CLI protocol name: `futures-carry-v1`. No tuning or extra coins are accepted.
The owner approved adding public 1h mark prices, explicit starting capital,
and a sourced, effective-dated margin-tier file for liquidation modelling.

Owner commands (public market data only; no API keys):

```powershell
python -m trading_platform_api.research fetch --market um-futures --include-mark --timeframe 1h --start 2021-09-30 --symbols BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT --data research-data/futures
$capital = Read-Host "Starting USDT capital per set"
python -m trading_platform_api.research carry --protocol futures-carry-v1 --capital $capital --margin-tiers research-data/futures/margin-tiers.json --data research-data/futures --out research-output/carry
```

`--include-mark` adds `um-futures/<SYMBOL>_mark_1h.csv` using the public
`/fapi/v1/markPriceKlines` endpoint, the same validation, LF bytes and digest
as other Futures candles. Without the flag the existing E11a fetch is unchanged.
Real historical data and the full study are run by the owner, not agent tests.

The margin file is owner-supplied JSON. It must contain `source` (a public
HTTPS reference without credentials), `retrieved_at` (UTC ISO timestamp), and
`tiers` (a list). Each tier has these fields:

| Field | Meaning |
|---|---|
| `symbol` | One of the five preregistered symbols |
| `effective_from`, `effective_until` | UTC ISO timestamps, half-open historical validity |
| `notional_floor`, `notional_cap` | USDT bracket, inclusive floor / exclusive cap |
| `maintenance_rate`, `maintenance_amount` | Maintenance = notional × rate − amount |

Financial fields are decimal **strings**. Supply actual sourced historical
values; no example numbers here are implied to be Binance tiers. Gaps,
overlapping brackets, invalid values or missing date/notional coverage make
the relevant set `UNAVAILABLE`. A current tier table is not automatically a
historical table. The runner records the file SHA256, source and retrieval
time; it does not authenticate the owner's historical source claims.
If the file or mark prices are missing, it writes an `UNAVAILABLE` verdict.

Rules and accounting interpretations (recorded in the strategy digest):

- At 00/08/16 UTC, funding is credited/debited only to an existing short using
  settled rate × short units × settlement mark open. The last three settlements
  **within the set** form the mean: enter at ≥ 0.0001, exit below zero. Until
  three exist, remain in cash. Orders are not created: both simulated fills
  use the next 1h open, shifted adversely by 0.05% per leg/side.
- Capital is split equally across each set's symbols, never rebalanced between
  symbols. Each episode reserves entry fees, then divides deployable capital
  equally into Spot notional and 1× isolated perpetual margin. Both executed
  entry notionals are equal. Spot costs 0.10%, perpetual 0.05% per traded side.
  Slippage is already in fill prices and is reported, never deducted twice.
- The basis stop uses the adverse change in quantity-weighted perpetual-minus-
  Spot value from entry raw opens, strictly **greater than** 2% of entry leg
  notional. Exit both at the next hourly open. Naive carry ignores this stop
  and the funding signal, and holds from the first open to the final close.
- Liquidation compares isolated balance to maintenance at each bar's **mark
  high**, including the entry bar. Liquidation takes precedence over a
  close-based stop on that bar. The short's entire margin balance, including
  funding left there, is lost; the Spot leg closes next open (last close at
  the boundary). The perpetual has no invented exit fill or extra taker fee
  after its margin is lost. Naive carry does not restart after liquidation.
- At each set boundary, open positions close at the last hourly close with
  costs. These are completed episodes with reason `END_OF_SET`. Drawdown uses
  hourly close equity marked using mark close; hourly OHLC cannot establish
  intrabar drawdown or exact intrabar liquidation ordering.
- Four windows divide development hours equally; the last takes any remainder.
  Positions continue across windows. Window positivity is the change in pooled
  equity, not a separate restart. Return/DD comparison uses cross-products
  when drawdown is zero (no invented epsilon). Bootstrap uses 5,000 resamples,
  seed 20261127 and the sorted index 250 for the 5% lower bound of episode means.

Fixed sets: development BTC/ETH from 2021-09-30 through 2024-06-30 inclusive;
holdout BTC/ETH from 2024-07-01 through 2026-11-25 inclusive; unseen BNB/SOL/XRP
over development dates. Missing/bad series makes its **whole set** unavailable;
no dates move and no symbol is dropped. Cash, naive carry and buy-and-hold
Spot are reported for every available set. Development needs ≥20 episodes
and ≥365 pooled position-days; holdout needs ≥10 episodes. Otherwise the
verdict is `INCONCLUSIVE`. With sufficient data/sample, PASS requires every
preregistered net, bootstrap, windows, return/DD and 10% drawdown criterion;
any failed criterion gives FAIL. Required unavailable sets give `UNAVAILABLE`.

The output is `futures-carry-v1.json` plus `.md`. The JSON is first written
and flushed with development results and dataset/strategy/protocol digests;
only then may holdout evaluation begin. An exclusive
`research-data/futures/.futures-carry-v1-holdout.claim.json` prevents repeated
holdout evaluation even with a different output folder. Final JSON retains
the development result/digest and adds holdout, unseen, every baseline,
per-episode records, windows and report digest. Existing reports are never
overwritten by a new run. If development is unavailable, the holdout is not
accessed and no claim is created. A failed/interrupted claimed holdout stays
consumed; there is no automatic retry or claim deletion. Local owner-controlled
files are not a tamper-proof external ledger. No PASS grants trading authority.

## Spot data integrity

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

**`limit` is a window, not a guess of the stored size (E2w).** Any `limit`
from 2 to 501 works on any stored snapshot. `/candles` serves the most recent
`limit` closed candles of the latest snapshot (same `snapshot_id`, quality
report and lineage); indicators are calculated over the whole snapshot and
their points sliced to the same window, so EMA500 keeps its warm-up. Markers
always replay the whole snapshot and return only the markers whose signal
candle is inside the window. Both responses carry `served_window` (stored
and served candle counts, first/last open time, scope). Only `limit` above
501 is rejected (422).

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
STRATEGY_NOT_REGISTERED`. SMA200 needs a stored 1d snapshot of at least 202
candles (the daily check stores 501).
