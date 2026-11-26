import { listSupportedSymbols, readSnapshot, readStrategyMarkers } from "./research-api.mjs";
import { TODAY_LIMIT, TODAY_TIMEFRAME, todayState } from "./today-state.mjs";
import { supportedWatchlistSymbols, validateWatchlistSnapshot, workspaceHref } from "./watchlist-state.mjs";

const $ = (selector) => document.querySelector(selector);
const element = (tag, value, className) => {
  const node = document.createElement(tag);
  if (value !== undefined) node.textContent = value;
  if (className) node.className = className;
  return node;
};

async function coinState(fetcher, item) {
  const input = {};
  try {
    const snapshot = await readSnapshot(fetcher, {
      instrumentId: item.instrument_id, timeframe: TODAY_TIMEFRAME, limit: TODAY_LIMIT,
    });
    const invalid = validateWatchlistSnapshot(snapshot, {
      instrumentId: item.instrument_id, symbol: item.symbol, timeframe: TODAY_TIMEFRAME,
    });
    if (invalid) throw new Error(invalid);
    input.snapshot = snapshot;
  } catch (error) {
    input.snapshotError = error.message;
    return input;
  }
  if (input.snapshot.data_quality?.status !== "VALID" || input.snapshot.temporal_context !== "CURRENT") return input;
  try {
    input.markers = await readStrategyMarkers(fetcher, {
      instrumentId: item.instrument_id, timeframe: TODAY_TIMEFRAME,
      limit: Math.max(2, input.snapshot.candles.length),
    });
  } catch (error) {
    input.markersError = error.message;
  }
  return input;
}

function renderRow(item, input, symbols) {
  const result = todayState(input);
  const row = element("li", undefined, "today-row");
  row.dataset.instrumentId = item.instrument_id;
  row.dataset.tone = result.tone;
  const head = element("div", undefined, "today-row-head");
  head.append(element("strong", item.symbol), element("span", result.state, `today-chip today-chip-${result.tone}`));
  if (input.snapshot?.as_of) {
    head.append(element("span", `4h snapshot as of ${input.snapshot.as_of} · quality ${input.snapshot.data_quality?.status}`, "muted"));
  }
  const reasons = element("ul", undefined, "today-reasons");
  for (const reason of result.reasons) reasons.append(element("li", reason));
  row.append(head, reasons);
  const href = workspaceHref(item.instrument_id, TODAY_TIMEFRAME, symbols);
  if (href) {
    const link = element("a", `Record decision for ${item.symbol} (Charts)`, "today-record");
    link.href = `${href}#decision-panel`;
    row.append(link);
  }
  return row;
}

async function loadToday() {
  const list = $("#today-rows");
  const status = $("#today-status");
  if (!list) return;
  let symbols;
  try {
    symbols = supportedWatchlistSymbols(await listSupportedSymbols(globalThis.fetch));
  } catch (error) {
    status.textContent = `Today view unavailable — ${error.message}`;
    return;
  }
  const inputs = await Promise.all(symbols.map((item) => coinState(globalThis.fetch, item)));
  list.replaceChildren(...symbols.map((item, index) => renderRow(item, inputs[index], symbols)));
  status.textContent = `${symbols.length} supported pairs · ema-trend-atr-stop v1 on stored 4h snapshots. Research only — not a trade instruction.`;
}

if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", () => { void loadToday(); }, { once: true });
}
