import { listSupportedSymbols, TIMEFRAME_SECONDS } from "./research-api.mjs";
import { readWatchlist, supportedWatchlistSymbols, workspaceHref } from "./watchlist-state.mjs";

const $ = (selector) => document.querySelector(selector);
const display = (value) => typeof value === "string" && value ? value : "Not reported";
const dateText = (value) => {
  if (typeof value !== "string") return "Not reported";
  return value;
};
const cell = (row, value) => {
  const td = document.createElement("td");
  td.textContent = value;
  row.append(td);
  return td;
};
const detail = (parent, label, value) => {
  const line = document.createElement("span");
  line.textContent = `${label}: ${display(value)}`;
  parent.append(line);
};

function renderRow(result, timeframe, symbols) {
  const row = document.createElement("tr");
  if (result.error) {
    row.dataset.state = "error";
    cell(row, result.symbol);
    const error = cell(row, `Unavailable — ${result.error}`);
    error.colSpan = 8;
    const linkCell = document.createElement("td");
    const href = workspaceHref(
      symbols.find((item) => item.symbol === result.symbol)?.instrument_id,
      timeframe,
      symbols,
    );
    if (href) {
      const link = document.createElement("a");
      link.href = href;
      link.textContent = "Open workspace";
      linkCell.append(link);
    } else {
      linkCell.textContent = "Unavailable";
    }
    row.append(linkCell);
    return row;
  }

  const { row: data } = result;
  row.dataset.state = data.quality === "VALID" && data.temporalContext === "CURRENT"
    ? "valid"
    : data.quality === "STALE" || data.temporalContext === "HISTORICAL"
      ? "warning"
      : "error";
  cell(row, `${data.symbol} · ${data.instrumentId}`);
  cell(row, `${data.close} ${data.priceUnit}`);
  cell(row, data.change);
  cell(row, dateText(data.candleTime));
  cell(row, `${data.volume} ${data.volumeUnit}`);
  const qualityCell = cell(row, `${data.quality} · ${data.temporalContext}`);
  detail(qualityCell, "Report status", data.reportQuality);
  cell(row, dateText(data.freshnessCutoff));
  const provenance = document.createElement("td");
  for (const [label, value] of [
    ["Venue", data.venue],
    ["Provider", data.source],
    ["Source ID", data.sourceId],
    ["Market data ID", data.marketDataId],
    ["Snapshot ID", data.snapshotId],
    ["Quality report ID", data.qualityReportId],
    ["Snapshot as-of", data.asOf],
    ["Source retrieved", data.sourceRetrievedAt],
  ]) detail(provenance, label, value);
  row.append(provenance);
  cell(row, data.analysis);
  const linkCell = document.createElement("td");
  const href = workspaceHref(data.instrumentId, timeframe, symbols);
  if (href) {
    const link = document.createElement("a");
    link.href = href;
    link.textContent = `Analyze ${data.symbol}`;
    linkCell.append(link);
  } else {
    linkCell.textContent = "Unavailable";
  }
  row.append(linkCell);
  return row;
}

async function bootstrap() {
  const timeframe = $("#timeframe-select");
  const rows = $("#watchlist-rows");
  const status = $("#overview-status");
  const error = $("#overview-error");
  let symbols = [];
  let symbolsPromise;
  let sequence = 0;

  const load = async () => {
    const requestSequence = ++sequence;
    error.hidden = true;
    rows.replaceChildren();
    status.dataset.state = "warning";
    status.replaceChildren(
      Object.assign(document.createElement("strong"), { textContent: `Reading stored ${timeframe.value} snapshots.` }),
      Object.assign(document.createElement("span"), { textContent: "Read-only local API requests; provider collection is not triggered." }),
    );
    if (!Object.hasOwn(TIMEFRAME_SECONDS, timeframe.value)) {
      error.textContent = "Select a timeframe supported by the local research API.";
      error.hidden = false;
      return;
    }
    try {
      if (!symbols.length) {
        symbolsPromise ??= listSupportedSymbols(globalThis.fetch)
          .then(supportedWatchlistSymbols)
          .then((supported) => {
            symbols = supported;
            return supported;
          });
        await symbolsPromise;
      }
      if (requestSequence !== sequence) return;
      const results = await readWatchlist(globalThis.fetch, timeframe.value, symbols);
      if (requestSequence !== sequence) return;
      rows.replaceChildren(...results.map((result) => renderRow(result, timeframe.value, symbols)));
      const failed = results.filter((result) => result.error).length;
      const nonCurrent = results.filter(({ row }) =>
        row && (row.quality !== "VALID" || row.reportQuality !== "VALID" || row.temporalContext !== "CURRENT"),
      ).length;
      status.dataset.state = failed === 0 && nonCurrent === 0 && results.length > 0 ? "valid" : "warning";
      status.replaceChildren(
        Object.assign(document.createElement("strong"), { textContent: `${results.length} supported instrument${results.length === 1 ? "" : "s"} · ${failed} unavailable · ${nonCurrent} non-VALID or non-current` }),
        Object.assign(document.createElement("span"), { textContent: "Snapshot quality and temporal context are shown per instrument; no analysis status is inferred." }),
      );
    } catch (loadError) {
      if (requestSequence !== sequence) return;
      rows.replaceChildren();
      status.dataset.state = "error";
      status.replaceChildren(
        Object.assign(document.createElement("strong"), { textContent: "Supported instruments unavailable." }),
        Object.assign(document.createElement("span"), { textContent: "The watchlist failed closed; no unsupported symbols are shown." }),
      );
      error.textContent = loadError.message;
      error.hidden = false;
    }
  };

  timeframe.addEventListener("change", () => { void load(); });
  await load();
}

if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", () => { void bootstrap(); }, { once: true });
}
