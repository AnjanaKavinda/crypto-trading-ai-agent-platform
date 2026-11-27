// Today tab (U6, UR1, UR5): the five coins at the shared timeframe, the
// selected coin's compact chart, its NO_TRADE reasons, every recorded study
// verdict, and "Record my decision" against that coin's exact snapshot.
// Read-only except the owner's own journal declaration.
import { mountJournal, snapshotDecisionEligibility } from "./decision-journal.mjs";
import { timeframeLabel } from "./desk-state.mjs";
import { indicatorBindingError, plotValues, snapshotCandles } from "./workspace-state.mjs";
import { change24h, displayPrice, todayState } from "./today-state.mjs";
import { reasonText, STRATEGY_STUDIES } from "./strategy-studies.mjs";
import { renderWatchlistFailure, renderWatchlistTable } from "./watchlist.mjs";

const SVG_NS = "http://www.w3.org/2000/svg";
const MINI_CANDLES = 90;

const element = (document, tag, value, className) => {
  const node = document.createElement(tag);
  if (value !== undefined) node.textContent = value;
  if (className) node.className = className;
  return node;
};
const svgNode = (document, tag, attributes = {}) => {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, String(value));
  return node;
};
const shortSymbol = (symbol) => String(symbol ?? "").replace(/USDT$/, "");

function chip(document, text, tone) {
  const node = element(document, "span", text, "state-chip");
  node.dataset.tone = tone;
  return node;
}

// Recorded verdicts as compact expandable rows (Today) …
export function renderVerdictList(document, list, studies = STRATEGY_STUDIES) {
  if (!list) return;
  list.replaceChildren(...studies.map((study) => {
    const item = element(document, "li", undefined, "verdict-row");
    const details = element(document, "details");
    const summary = element(document, "summary");
    summary.append(
      element(document, "span", `${study.strategy} v${study.version}`, "verdict-name"),
      chip(document, study.verdict, study.verdict === "FAIL" ? "fail" : "neutral"),
      element(document, "span", study.recordedOn ?? "no date", "card-note"),
    );
    const reasons = element(document, "ul", undefined, "verdict-reasons");
    for (const reason of study.reasons) reasons.append(element(document, "li", reasonText(reason)));
    details.append(summary, element(document, "p", `${study.protocol} · ${study.summary}`, "card-note"), reasons,
      element(document, "p", `Recorded on ${study.source}.`, "card-note"));
    item.append(details);
    return item;
  }));
}

// … and as cards (Strategy lab).
export function renderVerdictCards(document, container, studies = STRATEGY_STUDIES) {
  if (!container) return;
  container.replaceChildren(...studies.map((study) => {
    const card = element(document, "article", undefined, "verdict-card");
    const head = element(document, "div", undefined, "verdict-card-head");
    head.append(element(document, "h3", `${study.strategy} · v${study.version}`),
      chip(document, `Verdict: ${study.verdict}`, study.verdict === "FAIL" ? "fail" : "neutral"));
    const reasons = element(document, "ul", undefined, "verdict-reasons");
    for (const reason of study.reasons) reasons.append(element(document, "li", reasonText(reason)));
    card.append(head,
      element(document, "p", `${study.protocol}${study.timeframe ? ` · ${timeframeLabel(study.timeframe)} candles` : ""} · recorded ${study.recordedOn}`, "card-note"),
      element(document, "p", study.summary, "verdict-summary"), reasons,
      element(document, "p", `Source: ${study.source}.`, "card-note"));
    return card;
  }));
}

function renderCoinRow(document, entry, instrumentId, selected, onSelect) {
  const state = todayState(entry);
  const item = element(document, "li");
  const button = element(document, "button", undefined, "coin-row");
  button.type = "button";
  button.dataset.instrumentId = instrumentId;
  button.setAttribute("aria-pressed", String(selected));
  const price = displayPrice(entry.row);
  const change = entry.snapshot ? change24h(entry.snapshot) : null;
  const priceNode = element(document, "span", price?.text ?? "—", "coin-price");
  if (price) priceNode.title = `Exact returned close: ${price.exact}`;
  const changeNode = element(document, "span", change?.text ?? "—", `coin-change${change ? ` change-${change.direction}` : ""}`);
  changeNode.title = change ? `24h change from returned closes ${change.exact}` : "No candle closed exactly 24 hours before the latest one in this snapshot.";
  button.append(element(document, "strong", shortSymbol(entry.symbol), "coin-symbol"), priceNode, changeNode,
    chip(document, state.chip, state.chip === "NO_TRADE" ? "notrade" : state.tone === "error" ? "error" : "muted"));
  button.title = entry.error ? `${entry.symbol}: ${entry.error}` : `${entry.symbol} — ${state.freshness}`;
  button.setAttribute("aria-label", `${entry.symbol}: ${state.chip}${price ? `, last ${price.exact}` : ""}${change ? `, 24h ${change.text}` : ""}${entry.error ? `. ${entry.error}` : ""}`);
  button.addEventListener("click", () => onSelect(instrumentId));
  item.append(button);
  return item;
}

// Compact candlestick chart of the latest candles with backend EMA20/EMA50.
export function renderMiniChart(document, target, snapshot) {
  target.replaceChildren();
  const { candles, error } = snapshotCandles(snapshot);
  if (error || !candles.length) {
    target.append(element(document, "span", error ?? "No candles returned.", "empty-state"));
    return;
  }
  const shown = candles.slice(-MINI_CANDLES);
  const width = 600;
  const height = 200;
  const pad = 8;
  const lines = [];
  for (const [id, className] of [["ema-20", "ema-20"], ["ema-50", "ema-50"]]) {
    const indicator = snapshot.indicators?.[id];
    if (indicator?.status !== "AVAILABLE" || indicatorBindingError(snapshot, id, indicator)) continue;
    const byEnd = new Map(plotValues(indicator.result).map((point) => [Date.parse(point.candleEnd), Number(point.value)]));
    lines.push({ className, label: id.toUpperCase().replace("-", ""), values: shown.map(({ source }) => byEnd.get(Date.parse(source.close_time)) ?? null) });
  }
  const numbers = shown.flatMap(({ values }) => [values.low.numeric, values.high.numeric])
    .concat(lines.flatMap((line) => line.values.filter((value) => value !== null)));
  const min = Math.min(...numbers);
  const max = Math.max(...numbers);
  const span = max - min || Math.max(Math.abs(max) * 0.02, 1);
  const y = (value) => pad + (height - 2 * pad) * (1 - (value - min) / span);
  const step = (width - 2 * pad) / shown.length;
  const x = (index) => pad + step * (index + 0.5);
  const svg = svgNode(document, "svg", { viewBox: `0 0 ${width} ${height}`, preserveAspectRatio: "none", role: "img",
    "aria-label": `${snapshot.symbol} ${snapshot.timeframe}: last ${shown.length} returned candles${lines.length ? ` with ${lines.map((line) => line.label).join(" and ")}` : ""}` });
  shown.forEach(({ values }, index) => {
    const up = values.close.numeric >= values.open.numeric;
    svg.append(svgNode(document, "line", { x1: x(index), x2: x(index), y1: y(values.high.numeric), y2: y(values.low.numeric), class: `candle-wick candle-${up ? "up" : "down"}` }));
    svg.append(svgNode(document, "rect", { x: x(index) - step * 0.32, width: Math.max(1, step * 0.64),
      y: Math.min(y(values.open.numeric), y(values.close.numeric)),
      height: Math.max(1, Math.abs(y(values.open.numeric) - y(values.close.numeric))), class: `candle-body candle-${up ? "up" : "down"}` }));
  });
  for (const line of lines) {
    const points = line.values.flatMap((value, index) => value === null ? [] : [`${x(index)},${y(value)}`]);
    if (points.length > 1) svg.append(svgNode(document, "polyline", { points: points.join(" "), class: `indicator-line ${line.className}` }));
  }
  target.append(svg);
  const legend = element(document, "span", undefined, "mini-legend");
  for (const line of lines) legend.append(element(document, "span", line.label, `legend-${line.className}`));
  legend.append(element(document, "span", "Open in Charts ↗", "mini-open"));
  target.append(legend);
}

function renderFocus(document, entry, symbols, timeframe) {
  const state = todayState(entry);
  document.querySelector("#today-focus-heading").textContent = shortSymbol(entry.symbol);
  const focusChip = document.querySelector("#today-focus-chip");
  focusChip.hidden = false;
  focusChip.textContent = state.chip;
  focusChip.dataset.tone = state.chip === "NO_TRADE" ? "notrade" : state.tone === "error" ? "error" : "muted";
  document.querySelector("#today-focus-meta").textContent = entry.snapshot
    ? `as of ${entry.snapshot.candles.at(-1).close_time} · snapshot ${entry.snapshot.snapshot_id.slice(0, 8)}`
    : `${timeframeLabel(timeframe)} snapshot unavailable`;
  document.querySelector("#today-focus-meta").title = entry.snapshot
    ? `${state.freshness} · snapshot ${entry.snapshot.snapshot_id}`
    : entry.error ?? "";
  const chart = document.querySelector("#today-chart");
  if (entry.snapshot) renderMiniChart(document, chart, entry.snapshot);
  else chart.replaceChildren(element(document, "span", entry.error ?? "No stored snapshot.", "empty-state"));
  chart.disabled = !symbols.length;
  const why = document.querySelector("#today-why");
  why.replaceChildren(...state.reasons.map((reason) => element(document, "li", reason)));
}

function renderDecision(document, entry, fetcher) {
  const note = document.querySelector("#today-decision-note");
  const body = document.querySelector("#today-decision-body");
  body.replaceChildren();
  const eligibility = snapshotDecisionEligibility(entry.snapshot);
  if (!eligibility.ok) {
    note.textContent = entry.snapshot ? eligibility.reason : `No stored snapshot for ${entry.symbol} — ${entry.error ?? "unavailable"}. Decisions need a current, VALID snapshot.`;
    note.dataset.state = "warning";
    return;
  }
  note.textContent = `For ${entry.symbol} · ${entry.snapshot.timeframe} · snapshot ${eligibility.target.snapshot_id.slice(0, 8)} (quality VALID).`;
  note.dataset.state = "valid";
  mountJournal(document, body, null, fetcher, { snapshot: eligibility.target, quick: true, subject: shortSymbol(entry.symbol), history: false });
}

export async function mountToday({ document, desk, fetcher = globalThis.fetch, selectTab = () => {} }) {
  renderVerdictList(document, document.querySelector("#today-verdicts"));
  const list = document.querySelector("#today-rows");
  const status = document.querySelector("#today-status");
  let view = { timeframe: null, results: [], symbols: [], instrumentId: null };
  let sequence = 0;

  const show = () => {
    const index = Math.max(0, view.symbols.findIndex((item) => item.instrument_id === view.instrumentId));
    list.replaceChildren(...view.results.map((entry, position) => renderCoinRow(document, entry,
      view.symbols[position].instrument_id, position === index, (instrumentId) => desk.select({ instrumentId }))));
    if (view.results[index]) {
      renderFocus(document, view.results[index], view.symbols, view.timeframe);
      renderDecision(document, view.results[index], fetcher);
    }
  };

  const load = async () => {
    const current = ++sequence;
    const selection = await desk.selection();
    document.querySelector("#today-timeframe").textContent = timeframeLabel(selection.timeframe);
    status.textContent = `Reading stored ${timeframeLabel(selection.timeframe)} snapshots…`;
    try {
      const [symbols, results] = await Promise.all([desk.symbols(), desk.watchlist(selection.timeframe)]);
      if (current !== sequence) return;
      view = { timeframe: selection.timeframe, results, symbols, instrumentId: selection.instrumentId };
      show();
      renderWatchlistTable(results, selection.timeframe, symbols);
      const failed = results.filter((entry) => !entry.row).length;
      status.textContent = `${results.length} supported pairs · stored ${timeframeLabel(selection.timeframe)} snapshots${failed ? ` · ${failed} unavailable` : ""}. NO_TRADE until a strategy passes its study. Research only — not a trade instruction.`;
    } catch (error) {
      if (current !== sequence) return;
      list.replaceChildren();
      status.textContent = `Today view unavailable — ${error.message}`;
      renderWatchlistFailure(error.message);
    }
  };

  document.querySelector("#today-chart").addEventListener("click", () => selectTab("charts"));
  desk.onChange((selection, change) => {
    if (change.invalidated || selection.timeframe !== view.timeframe) { void load(); return; }
    if (selection.instrumentId !== view.instrumentId) {
      view.instrumentId = selection.instrumentId;
      show();
    }
  });
  await load();
}
