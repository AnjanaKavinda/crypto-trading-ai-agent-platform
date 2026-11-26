// U6 Today screen (owner answer "U6 A", #516): per coin show the stored price,
// data quality/freshness and NO_TRADE while no strategy has passed its study.
// No failed-strategy BUY/SELL state is shown. No network or DOM here.

export const TODAY_TIMEFRAME = "4h";

// Study verdicts recorded by the owner's operator runs on #516. The API does not
// serve study verdicts yet, so this list is the single place to update when a
// new verdict is recorded. Never add a verdict that was not actually produced.
export const STRATEGY_STUDIES = Object.freeze([
  Object.freeze({
    strategy: "ema-trend-atr-stop",
    version: "1",
    protocol: "spot-trend-holdout v1",
    verdict: "FAIL",
    recordedOn: "2026-11-26",
    reasons: Object.freeze([
      "NON_POSITIVE_EXPECTANCY_AFTER_COSTS",
      "DOES_NOT_BEAT_CASH",
      "PORTFOLIO_DRAWDOWN_LIMIT_EXCEEDED",
      "SYMBOL_DRAWDOWN_LIMIT_EXCEEDED",
    ]),
  }),
  Object.freeze({
    strategy: "trend-daily-regime",
    version: "1",
    protocol: "spot-walk-forward-prospective v2",
    verdict: "NO_RESULT_RECORDED",
    recordedOn: null,
    reasons: Object.freeze(["Pre-registered; no study result recorded yet."]),
  }),
]);

const PASSING = new Set(["PASS", "HISTORICAL_PASS"]);

export function studyLine(study) {
  const when = study.recordedOn ? ` (${study.recordedOn})` : "";
  const why = study.reasons.length ? ` — ${study.reasons.join(", ")}` : "";
  return `${study.strategy} v${study.version}, ${study.protocol}: ${study.verdict}${when}${why}`;
}

function dataLine(row) {
  if (row.quality !== "VALID") return `Data quality ${row.quality ?? "not reported"} — price is shown for reference only.`;
  if (row.temporalContext !== "CURRENT") return `Snapshot is ${row.temporalContext ?? "of unknown time"}, not current.`;
  return null;
}

// `entry` is one item from readWatchlist(): { symbol, row, error }.
export function todayState(entry, studies = STRATEGY_STUDIES) {
  const passed = studies.filter((study) => PASSING.has(study.verdict));
  const reasons = passed.length
    ? ["A strategy has passed its study, but no signal source is connected yet."]
    : ["No strategy has passed its study."];
  reasons.push(...studies.map(studyLine));

  if (!entry?.row) {
    return {
      decision: "NO_TRADE",
      data: "UNAVAILABLE",
      tone: "error",
      price: null,
      reasons: [`Snapshot unavailable — ${entry?.error ?? "no response"}`, ...reasons],
    };
  }
  const row = entry.row;
  const issue = dataLine(row);
  return {
    decision: "NO_TRADE",
    data: issue ? (row.quality !== "VALID" ? row.quality ?? "NOT_REPORTED" : row.temporalContext ?? "UNKNOWN") : "VALID",
    tone: issue ? "warning" : "neutral",
    price: `${row.close} ${row.priceUnit}`,
    freshness: `4h candle closed ${row.candleTime} · snapshot as of ${row.asOf} · freshness cutoff ${row.freshnessCutoff}`,
    reasons: issue ? [issue, ...reasons] : reasons,
  };
}
