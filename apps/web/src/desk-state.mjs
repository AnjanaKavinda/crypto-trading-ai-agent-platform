// Pure state for the trading-desk shell (U1). No network, DOM or storage here.

export const DESK_TABS = Object.freeze([
  Object.freeze({ id: "today", label: "Today", page: "./watchlist.html",
    title: "Spot market overview for the five supported pairs" }),
  Object.freeze({ id: "charts", label: "Charts", page: "./index.html",
    title: "Asset analysis workspace with exact API candles and indicators" }),
  Object.freeze({ id: "strategy-lab", label: "Strategy lab", page: "./evidence.html",
    title: "Stored strategy evidence reports" }),
  Object.freeze({ id: "my-results", label: "My results", page: "./signals.html",
    title: "My results vs baselines, research records, NO_TRADE decisions and the owner decision journal" }),
]);

export const DEFAULT_TAB = "today";
export const FRESHNESS_TIMEFRAME = "1h";

export function tabFromHash(hash) {
  const value = typeof hash === "string" ? hash.replace(/^#/, "") : "";
  return DESK_TABS.some((tab) => tab.id === value) ? value : DEFAULT_TAB;
}

export function adjacentTab(currentId, key) {
  const index = DESK_TABS.findIndex((tab) => tab.id === currentId);
  if (index < 0) return DEFAULT_TAB;
  if (key === "Home") return DESK_TABS[0].id;
  if (key === "End") return DESK_TABS[DESK_TABS.length - 1].id;
  const step = key === "ArrowRight" ? 1 : key === "ArrowLeft" ? -1 : 0;
  return DESK_TABS[(index + step + DESK_TABS.length) % DESK_TABS.length].id;
}

// Summarise watchlist reads (see watchlist-state.readWatchlist) for the status
// header. Only backend-reported quality and timestamps are used; nothing is
// inferred when a read fails.
export function summariseFreshness(results, timeframe = FRESHNESS_TIMEFRAME) {
  if (!Array.isArray(results) || !results.length) {
    return { state: "error", text: `Data freshness (${timeframe}): unavailable — no supported pairs were read.` };
  }
  const counts = new Map();
  let failed = 0;
  let historical = 0;
  let latest = null;
  for (const result of results) {
    if (!result?.row) { failed += 1; continue; }
    const quality = String(result.row.quality);
    counts.set(quality, (counts.get(quality) ?? 0) + 1);
    if (result.row.temporalContext === "HISTORICAL") historical += 1;
    const time = Date.parse(result.row.candleTime);
    if (Number.isFinite(time) && (latest === null || time > latest)) latest = time;
  }
  const parts = [...counts.entries()].map(([quality, count]) => `${count} ${quality}`);
  if (failed) parts.push(`${failed} unavailable`);
  if (historical) parts.push(`${historical} historical`);
  const total = results.length;
  const valid = counts.get("VALID") ?? 0;
  const state = failed || [...counts.keys()].some((q) => !["VALID", "STALE"].includes(q))
    ? "error"
    : valid === total && !historical ? "valid" : "warning";
  const latestText = latest === null
    ? "no finalized candle"
    : `latest finalized candle ${new Date(latest).toISOString().replace(".000Z", "Z")}`;
  return { state, text: `Data freshness (${timeframe}, ${total} pairs): ${parts.join(" · ")} — ${latestText}.` };
}
