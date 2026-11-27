// Pure state for the one-page trading desk (UR1/UR3). No network or DOM here.

export const DESK_TABS = Object.freeze([
  Object.freeze({ id: "today", label: "Today" }),
  Object.freeze({ id: "charts", label: "Charts" }),
  Object.freeze({ id: "strategy-lab", label: "Strategy lab" }),
  Object.freeze({ id: "my-results", label: "My results" }),
]);

export const DEFAULT_TAB = "today";

// The one timeframe control (UR1): 1h / 4h / 1D. 1 minute and weekly/monthly
// candles are not offered.
export const DESK_TIMEFRAMES = Object.freeze(["1h", "4h", "1d"]);
export const DEFAULT_TIMEFRAME = "4h";
export const SELECTION_KEY = "spot-research.desk-selection.v1";

export function timeframeLabel(timeframe) {
  return timeframe === "1d" ? "1D" : String(timeframe ?? "");
}

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

function readStored(storage) {
  try {
    const saved = JSON.parse(storage?.getItem(SELECTION_KEY));
    return saved && typeof saved === "object" ? saved : {};
  } catch {
    return {};
  }
}

// Selected coin and timeframe shared by every tab (UR3). A single, valid URL
// value wins (deep links), then the remembered choice, then BTC · 4h. Values
// outside the supported lists are ignored, never echoed.
export function deskSelection({ search = "", storage = null, symbols = [], timeframes = DESK_TIMEFRAMES } = {}) {
  const parameters = new URLSearchParams(search);
  const one = (name) => {
    const values = parameters.getAll(name);
    return values.length === 1 ? values[0] : null;
  };
  const stored = readStored(storage);
  const instrumentIds = symbols.map((item) => item.instrument_id);
  const pick = (candidates, allowed, fallback) =>
    candidates.find((value) => allowed.includes(value)) ?? fallback;
  return {
    instrumentId: pick([one("instrument"), stored.instrumentId], instrumentIds, instrumentIds[0] ?? null),
    timeframe: pick([one("timeframe"), stored.timeframe], timeframes,
      timeframes.includes(DEFAULT_TIMEFRAME) ? DEFAULT_TIMEFRAME : timeframes[0]),
  };
}

export function saveSelection(storage, { instrumentId, timeframe }) {
  try {
    storage.setItem(SELECTION_KEY, JSON.stringify({ instrumentId, timeframe }));
    return true;
  } catch {
    return false;
  }
}

const utcMinute = (time) => new Date(time).toISOString().slice(0, 16).replace("T", " ") + " UTC";

// Header data chip from the five stored snapshots of the selected timeframe:
// worst backend quality wins; the time is the latest snapshot as_of (the last
// refresh). Nothing is inferred when a read fails.
export function summariseFreshness(results, timeframe) {
  const label = timeframeLabel(timeframe);
  if (!Array.isArray(results) || !results.length) {
    return { state: "error", text: `Data: unavailable · ${label}`, title: "No supported pair could be read from the local research API." };
  }
  const counts = new Map();
  let failed = 0;
  let historical = 0;
  let latestRefresh = null;
  let latestCandle = null;
  for (const result of results) {
    if (!result?.row) { failed += 1; continue; }
    const quality = String(result.row.quality);
    counts.set(quality, (counts.get(quality) ?? 0) + 1);
    if (result.row.temporalContext === "HISTORICAL") historical += 1;
    const refreshed = Date.parse(result.row.asOf);
    if (Number.isFinite(refreshed) && (latestRefresh === null || refreshed > latestRefresh)) latestRefresh = refreshed;
    const candle = Date.parse(result.row.candleTime);
    if (Number.isFinite(candle) && (latestCandle === null || candle > latestCandle)) latestCandle = candle;
  }
  const parts = [...counts.entries()].map(([quality, count]) => `${count} ${quality}`);
  if (failed) parts.push(`${failed} unavailable`);
  if (historical) parts.push(`${historical} historical`);
  const total = results.length;
  const valid = counts.get("VALID") ?? 0;
  const badQuality = [...counts.keys()].some((quality) => !["VALID", "STALE"].includes(quality));
  const [state, word] = failed === total
    ? ["error", "unavailable"]
    : failed || badQuality
      ? ["error", "incomplete"]
      : valid === total && !historical ? ["valid", "fresh"] : ["warning", "stale"];
  const when = latestRefresh === null ? "" : ` · ${utcMinute(latestRefresh)}`;
  const candleText = latestCandle === null
    ? "no finalized candle"
    : `latest finalized candle ${new Date(latestCandle).toISOString().replace(".000Z", "Z")}`;
  return {
    state,
    text: `Data: ${word} · ${label}${when}`,
    title: `${total} pairs at ${label}: ${parts.join(" · ")} — ${candleText}${latestRefresh === null ? "" : `; last refresh ${new Date(latestRefresh).toISOString()}`}.`,
  };
}
