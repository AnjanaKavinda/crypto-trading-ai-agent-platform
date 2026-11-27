// Today screen state (U6, UR1, UR5): per coin the stored price, data quality
// and NO_TRADE while no strategy has passed its study. No failed-strategy
// BUY/SELL state is shown. No network or DOM here.
import { displayDecimals, formatDisplayNumber } from "./chart-interaction.mjs";
import { PASSING_VERDICTS, STRATEGY_STUDIES, studyLine } from "./strategy-studies.mjs";

export { STRATEGY_STUDIES, studyLine };

export const TODAY_TIMEFRAME = "4h";

function dataLine(row) {
  if (row.quality !== "VALID") return `Data quality ${row.quality ?? "not reported"} — price is shown for reference only; decisions need a VALID snapshot.`;
  if (row.temporalContext !== "CURRENT") return `Snapshot is ${row.temporalContext ?? "of unknown time"}, not current.`;
  return null;
}

// `entry` is one item from readWatchlist(): { symbol, row, error }.
// `reasons` is the coin's plain "Why" list; `studies` the recorded verdicts.
export function todayState(entry, studies = STRATEGY_STUDIES) {
  const passed = studies.filter((study) => PASSING_VERDICTS.has(study.verdict));
  const headline = passed.length
    ? "A strategy has passed its study, but no signal source is connected yet."
    : "No strategy has passed its study.";
  const summary = passed.length
    ? "So this coin stays NO_TRADE until a signal source is connected."
    : `All ${studies.length} recorded studies failed, so this coin is NO_TRADE. This is research, not a trade instruction.`;
  const studyLines = studies.map(studyLine);

  if (!entry?.row) {
    return {
      decision: "NO_TRADE",
      chip: "UNAVAILABLE",
      data: "UNAVAILABLE",
      tone: "error",
      price: null,
      reasons: [`Snapshot unavailable — ${entry?.error ?? "no response"}`, headline, summary],
      studies: studyLines,
    };
  }
  const row = entry.row;
  const issue = dataLine(row);
  const data = issue ? (row.quality !== "VALID" ? row.quality ?? "NOT_REPORTED" : row.temporalContext ?? "UNKNOWN") : "VALID";
  return {
    decision: "NO_TRADE",
    chip: issue ? data : "NO_TRADE",
    data,
    tone: issue ? "warning" : "neutral",
    price: `${row.close} ${row.priceUnit}`,
    freshness: `${row.timeframe ?? TODAY_TIMEFRAME} candle closed ${row.candleTime} · snapshot as of ${row.asOf} · freshness cutoff ${row.freshnessCutoff}`,
    reasons: issue ? [issue, headline, summary] : [headline, summary],
    studies: studyLines,
  };
}

const DAY_MS = 24 * 60 * 60 * 1000;

// Change over the last 24 hours from two returned closes (display arithmetic
// only). Null unless the candle that closed exactly 24h before the latest one
// is in the snapshot.
export function change24h(snapshot) {
  const candles = Array.isArray(snapshot?.candles) ? snapshot.candles : [];
  const latest = candles.at(-1);
  const latestClose = Date.parse(latest?.close_time);
  if (!Number.isFinite(latestClose)) return null;
  const earlier = candles.find((candle) => Date.parse(candle.close_time) === latestClose - DAY_MS);
  const from = Number(earlier?.metrics?.close?.value);
  const to = Number(latest?.metrics?.close?.value);
  if (!earlier || !Number.isFinite(from) || !Number.isFinite(to) || from <= 0) return null;
  const percent = ((to - from) / from) * 100;
  return {
    percent,
    text: `${percent >= 0 ? "+" : "−"}${Math.abs(percent).toFixed(2)}%`,
    direction: percent >= 0 ? "up" : "down",
    exact: `${earlier.metrics.close.value} → ${latest.metrics.close.value} ${latest.metrics.close.unit}`,
  };
}

// Price at the instrument's display precision; the exact string stays on hover.
export function displayPrice(row) {
  if (!row) return null;
  return { text: formatDisplayNumber(row.close, displayDecimals(row.close)), exact: `${row.close} ${row.priceUnit}` };
}
