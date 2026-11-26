import { listSupportedSymbols } from "./research-api.mjs";
import { TODAY_TIMEFRAME, todayState } from "./today-state.mjs";
import { readWatchlist, supportedWatchlistSymbols, workspaceHref } from "./watchlist-state.mjs";

const element = (document, tag, value, className) => {
  const node = document.createElement(tag);
  if (value !== undefined) node.textContent = value;
  if (className) node.className = className;
  return node;
};

export function renderTodayRow(document, entry, instrumentId, symbols) {
  const result = todayState(entry);
  const row = element(document, "li", undefined, "today-row");
  row.dataset.instrumentId = instrumentId;
  row.dataset.tone = result.tone;
  const head = element(document, "div", undefined, "today-row-head");
  head.append(
    element(document, "strong", entry.symbol),
    element(document, "span", result.decision, "today-chip"),
    element(document, "span", `Data ${result.data}`, `today-chip today-chip-${result.tone}`),
  );
  if (result.price) head.append(element(document, "span", result.price, "today-price"));
  row.append(head);
  if (result.freshness) row.append(element(document, "p", result.freshness, "muted"));
  const reasons = element(document, "ul", undefined, "today-reasons");
  for (const reason of result.reasons) reasons.append(element(document, "li", reason));
  row.append(reasons);
  const href = workspaceHref(instrumentId, TODAY_TIMEFRAME, symbols);
  if (href) {
    const link = element(document, "a", `Record my decision for ${entry.symbol}`, "today-record");
    link.href = `${href}#decision-panel`;
    row.append(link);
  }
  return row;
}

export async function loadToday(document, fetcher) {
  const list = document.querySelector("#today-rows");
  const status = document.querySelector("#today-status");
  if (!list || !status) return;
  let symbols;
  let entries;
  try {
    symbols = supportedWatchlistSymbols(await listSupportedSymbols(fetcher));
    entries = await readWatchlist(fetcher, TODAY_TIMEFRAME, symbols);
  } catch (error) {
    status.textContent = `Today view unavailable — ${error.message}`;
    return;
  }
  list.replaceChildren(...entries.map((entry, index) =>
    renderTodayRow(document, entry, symbols[index].instrument_id, symbols)));
  status.textContent = `${entries.length} supported pairs · stored 4h snapshots. NO_TRADE until a strategy passes its study. Research only — not a trade instruction.`;
}

if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", () => { void loadToday(document, globalThis.fetch); }, { once: true });
}
