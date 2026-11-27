// Charts tab of the Trading desk (UR1/UR2/UR3/U5b): full-width chart with one
// timeframe control, the indicator pill bar above it, drawing tools on the
// left and a collapsible details drawer (markers + evidence, Record my
// decision, snapshot provenance). Every value comes from the local research
// API; the browser only draws and formats it.
import { mountJournal, snapshotDecisionEligibility } from "./decision-journal.mjs";
import { markerAnchors, markerFieldDisplay, markersBindingError, MARKER_LABELS, sizingInputs, tradeDetails } from "./strategy-markers.mjs";
import { toolbarPills } from "./indicator-toolbar.mjs";
import { CHART_STYLES, closePath } from "./chart-display.mjs";
import { mountChartToolbar } from "./chart-toolbar.mjs";
import {
  createDrawing,
  DRAWING_LABEL,
  drawingsKey,
  drawingTool,
  fibLevels,
  loadDrawings,
  positionSummary,
  priceRange,
  saveDrawings,
  toolsForMode,
} from "./chart-drawings.mjs";
import {
  axisTimeLabel,
  chartIndexAtPointer,
  candleInspectorText,
  displayDecimals,
  formatDisplayNumber,
  lastPriceTag,
  moveChartSelection,
  normaliseChartWindow,
  panChartWindow,
  priceScale,
  timeAxisIndexes,
  volumeReferenceLine,
  zoomChartWindow,
} from "./chart-interaction.mjs";
import {
  readSnapshot,
  readStrategyMarkers,
  refreshSnapshot,
  MAX_CANDLES,
  MAX_REFRESH_SECONDS,
  refreshRequestWithinBounds,
  TIMEFRAME_SECONDS,
} from "./research-api.mjs";
import {
  INDICATOR_IDS,
  indicatorBindingError,
  latestIndicatorValues,
  loadPreferences,
  plotValues,
  savePreferences,
  shownIndicators,
  snapshotCandles,
  snapshotLabels,
  spotAnalysisBindingError,
  SPOT_ANALYSIS_IDS,
  validateSnapshot,
} from "./workspace-state.mjs";
import { DESK_TIMEFRAMES, timeframeLabel } from "./desk-state.mjs";
import { change24h } from "./today-state.mjs";
import { markerStrategyOptions, parseStrategyKey, verdictBanner } from "./strategy-studies.mjs";
import { movePane, niceTicks, orderedPanes, PANE_DEFINITIONS, paneRange } from "./chart-panes.mjs";
import { plainReading } from "./plain-reading.mjs";

const EDUCATION = Object.freeze({
  "ema-20": {
    title: "EMA 20",
    group: "Trend",
    measure: "Exponential moving average of the closing price over 20 candles; recent closes receive more weight.",
    purpose: "Provides a smoothed, lagging description of recent price direction.",
    regimes: "May be useful for describing sustained trends; less useful in sideways or whipsaw conditions.",
    failures: "Lags abrupt changes, can whipsaw in ranges, and shares price-derived evidence with other moving averages.",
  },
  "ema-50": {
    title: "EMA 50",
    group: "Trend",
    measure: "Exponential moving average of the closing price over 50 candles; recent closes receive more weight.",
    purpose: "Provides a slower, lagging description of the broader price trend.",
    regimes: "May be useful for describing sustained trends; less useful in sideways or rapidly changing conditions.",
    failures: "Lags price changes, can whipsaw in ranges, needs 50 candles for warm-up, and is correlated with other price measures.",
  },
  "ema-500": {
    title: "EMA 500",
    group: "Trend",
    measure: "Exponential moving average of the closing price over 500 candles.",
    purpose: "Describes a very long-window smoothed price trend when sufficient history is returned.",
    regimes: "May help provide broad trend context over long histories; it is not a short-term timing measure.",
    failures: "Needs extensive contiguous history, responds slowly, and can be irrelevant after a regime change.",
  },
  "atr-14": {
    title: "ATR 14",
    group: "Volatility / risk",
    measure: "Average true range over 14 candles, including gaps relative to the prior close.",
    purpose: "Describes recent absolute price-range variability; it does not calculate a risk limit or position size.",
    regimes: "May help compare recent range conditions within the same instrument and timeframe.",
    failures: "Does not indicate direction, is in price units, is lagging, and is not comparable across instruments without context.",
  },
  "bollinger-bands-20": {
    title: "Bollinger Bands 20",
    group: "Volatility / risk",
    measure: "A 20-close mean and bands two population standard deviations above and below that mean.",
    purpose: "Describes recent dispersion around a moving average.",
    regimes: "May provide context during changing volatility; band expansion or compression is descriptive only.",
    failures: "Band contact is not a reversal or breakout guarantee; the bands lag and are derived from the same closes.",
  },
  "realized-volatility-20": {
    title: "Realized volatility 20",
    group: "Volatility / risk",
    measure: "Annualized sample dispersion of 20 close-to-close log returns using the backend's continuous-market convention.",
    purpose: "Summarizes historical return variability, not implied or forecast volatility.",
    regimes: "Useful as historical volatility context when the timeframe and annualization assumptions are understood.",
    failures: "Backward-looking, sensitive to the selected window, and not a forecast, percentile, or risk threshold.",
  },
  "rsi-14": {
    title: "RSI 14",
    group: "Momentum",
    measure: "A bounded momentum oscillator derived from recent gains and losses over 14 candles.",
    purpose: "Describes recent directional momentum, not a probability or standalone reversal signal.",
    regimes: "May be useful as context in range-bound conditions; trending markets can sustain extreme readings.",
    failures: "Can remain elevated or depressed during trends, is window-sensitive, and shares price-derived inputs.",
  },
  "macd-12-26-9": {
    title: "MACD 12/26/9",
    group: "Momentum",
    measure: "Difference between 12- and 26-period exponential averages, its 9-period signal average, and their histogram.",
    purpose: "Summarizes trend momentum at several smoothed horizons.",
    regimes: "May provide descriptive context in sustained trends; it can be noisy in ranges.",
    failures: "Lagging, parameter-dependent, and built from the same price history as moving averages.",
  },
  "stochastic-14-3": {
    title: "Stochastic 14/3",
    group: "Momentum",
    measure: "Compares the close with the recent 14-candle high/low range and smooths the result over 3 periods.",
    purpose: "Describes where recent closes sit within their observed range.",
    regimes: "May be useful for range-context; it can remain extreme in directional markets.",
    failures: "Sensitive to window and range boundaries, can whipsaw, and is not a guaranteed turning point.",
  },
  "cci-20": {
    title: "CCI 20",
    group: "Momentum",
    measure: "Compares a 20-period typical-price value with its mean deviation.",
    purpose: "Describes deviation from a recent typical-price baseline.",
    regimes: "May provide context for cyclical or range behavior; sustained trends can keep readings extreme.",
    failures: "Window-sensitive, price-derived and not a probability or independent confirmation.",
  },
});

const TIMEFRAMES = DESK_TIMEFRAMES;
const PRICE_UNIT_INDICATORS = new Set([
  "ema-20", "ema-50", "ema-500", "bollinger-bands-20", "atr-14", "macd-12-26-9",
]);
const HISTORY_LIMITS = new Set([50, 90, 100, 250, 501]);
const SPOT_ANALYSIS_LABELS = Object.freeze({
  vwap: "Spot VWAP",
  "volume-profile": "Volume profile",
  "volume-confirmation": "Volume confirmation",
  "price-action-support-resistance": "Price-action candle geometry",
  "spot-market-structure": "Spot market structure",
});
// Overlay colours: one source for the line and its legend (UR2).
const OVERLAY_SERIES = Object.freeze({
  "ema-20": [{ className: "ema-20", field: "value", label: "EMA20", color: "#38bdf8" }],
  "ema-50": [{ className: "ema-50", field: "value", label: "EMA50", color: "#e2e8f0" }],
  "ema-500": [{ className: "ema-500", field: "value", label: "EMA500", color: "#facc15" }],
  "bollinger-bands-20": [
    { className: "bollinger-upper", field: "upper", label: "BB upper", color: "#fb923c" },
    { className: "bollinger-middle", field: "middle", label: "BB mid", color: "#94a3b8" },
    { className: "bollinger-lower", field: "lower", label: "BB lower", color: "#4ade80" },
  ],
});
const VWAP_COLOR = "#f472b6";
const VOLUME_AVERAGE_COLOR = "#38bdf8";
const $ = (selector) => document.querySelector(selector);
const element = (tag, text, className) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
};
const SVG_NS = "http://www.w3.org/2000/svg";
const svgNode = (tag, attributes = {}) => {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, String(value));
  return node;
};
const formatter = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "medium", timeZone: "UTC" });
const isoText = (value) => {
  if (typeof value !== "string") return "Not reported";
  const instant = new Date(value);
  return Number.isNaN(instant.valueOf()) ? value : `${formatter.format(instant)} UTC · ${value}`;
};
const stringValue = (value) => typeof value === "string" ? value : value == null ? "Not reported" : String(value);
const pairLabel = (symbol) => String(symbol ?? "").replace(/USDT$/, "/USDT");

// U2j: "Record my decision" binds the journal (C-107v2) to the exact snapshot
// on screen. The quick form is ready as soon as the snapshot is eligible.
function renderDecisionPanel(snapshot) {
  const eligibility = snapshotDecisionEligibility(snapshot);
  $("#decision-body").replaceChildren();
  $("#decision-note").textContent = eligibility.ok
    ? `For ${snapshot.symbol} · ${snapshot.timeframe} · snapshot ${eligibility.target.snapshot_id} (quality VALID).`
    : eligibility.reason;
  $("#decision-note").dataset.state = eligibility.ok ? "valid" : "warning";
  if (!eligibility.ok) return;
  mountJournal(document, $("#decision-body"), null, globalThis.fetch, {
    snapshot: eligibility.target, quick: true, subject: snapshot.symbol.replace(/USDT$/, ""),
  });
}

function setStatus(snapshot, errorMessage) {
  const panel = $("#snapshot-status");
  panel.replaceChildren();
  panel.title = "";
  if (errorMessage) {
    panel.dataset.state = "error";
    panel.append(element("strong", "Research request failed."), element("span", errorMessage, "status-detail"));
    panel.title = errorMessage;
    return;
  }
  const labels = snapshotLabels(snapshot);
  panel.dataset.state = labels.severity;
  panel.append(element("strong", `${labels.quality} · ${labels.temporal}`));
  panel.append(element("span", `Binance Spot · ${snapshot.candles.length} candles · source as of ${displayTime(snapshot.as_of)}`, "status-meta"));
  let detail;
  if (snapshot.temporal_context === "HISTORICAL") {
    detail = "This point-in-time research response is historical and is never represented as current.";
  } else if (labels.quality === "VALID") {
    detail = "Quality is reported VALID for this exact snapshot; this does not establish trading readiness or execution authority.";
  } else {
    detail = `The API reports ${labels.quality}; this is not promoted to valid or current evidence.`;
  }
  if (snapshot.data_quality?.report_status && snapshot.data_quality.report_status !== labels.quality) {
    detail += ` Underlying report status: ${snapshot.data_quality.report_status}.`;
  }
  panel.append(element("span", detail, "status-detail"));
  panel.title = `Snapshot ${snapshot.snapshot_id}. ${detail}`;
}

function indicatorAvailability(snapshot, id) {
  const supplied = Object.hasOwn(snapshot?.indicators ?? {}, id);
  const indicator = snapshot?.indicators?.[id];
  const bindingError = supplied ? indicatorBindingError(snapshot, id, indicator) : null;
  const available = supplied && indicator?.status === "AVAILABLE" && !bindingError;
  const reason = !supplied
    ? "not supplied in response"
    : indicator?.status === "UNAVAILABLE" && indicator?.reason_code
      ? indicator.reason_code
      : bindingError ?? indicator?.reason_code ?? indicator?.status ?? "unavailable";
  return { available, reason };
}

function analysisAvailability(snapshot, id) {
  const analysis = snapshot?.spot_analysis?.[id];
  if (!analysis) return { available: false, reason: "not supplied in response" };
  const bindingError = spotAnalysisBindingError(snapshot, id, analysis);
  if (bindingError) return { available: false, reason: bindingError };
  if (!["AVAILABLE", "PARTIAL"].includes(analysis.status)) {
    return { available: false, reason: analysis.reason_code ?? analysis.status ?? "unavailable" };
  }
  if (id === "vwap" && !analysis.result?.points?.some((point) => point.value?.status === "READY" && numberForPlot(point.value.value) !== null)) {
    return { available: false, reason: "No verified VWAP points for this snapshot." };
  }
  return { available: true };
}

function renderIndicatorToolbar(snapshot, preferences, updatePreferences, onSignals) {
  const toolbar = $("#indicator-toolbar");
  if (!toolbar) return;
  toolbar.replaceChildren();
  const pills = toolbarPills({
    snapshotLoaded: Boolean(snapshot),
    enabled: shownIndicators(preferences),
    mode: preferences.mode,
    signalsOn: preferences.signals,
    volumeOn: preferences.volume,
    availability: (kind, id) => kind === "indicator" ? indicatorAvailability(snapshot, id) : analysisAvailability(snapshot, id),
  });
  for (const pill of preferences.mode === "pro" ? [] : pills) {
    const button = element("button", pill.short, `indicator-pill${pill.live ? "" : " not-ready"}`);
    button.type = "button";
    button.style.setProperty("--pill-color", pill.color);
    button.dataset.pill = pill.short;
    button.title = `${pill.label}${pill.hint ? ` — ${pill.hint}` : ""}\n${pill.group} · ${pill.badge}: ${pill.reason}`;
    button.setAttribute("aria-label", `${pill.label} (${pill.group}), ${pill.badge}. ${pill.reason}`);
    if (pill.pressed !== null) button.setAttribute("aria-pressed", pill.pressed);
    if (!pill.action) {
      if (!pill.live) button.disabled = true;
      else button.setAttribute("aria-disabled", "true");
    } else if (pill.action.type === "toggle") {
      button.addEventListener("click", () => {
        if (pill.action.id === "volume") {
          updatePreferences({ ...preferences, volume: !preferences.volume });
          return;
        }
        const visible = new Set(preferences.visible);
        if (visible.has(pill.action.id)) visible.delete(pill.action.id);
        else visible.add(pill.action.id);
        updatePreferences({ ...preferences, visible: [...visible] });
      });
    } else if (pill.action.type === "signals") {
      button.addEventListener("click", () => onSignals(!preferences.signals));
    } else {
      button.addEventListener("click", () => {
        const card = document.querySelector(`[data-analysis-key="${pill.action.id}"]`);
        const section = $("#analysis-section");
        if (section) section.open = true;
        if (card) {
          card.tabIndex = -1;
          card.scrollIntoView({ block: "start" });
          card.focus({ preventScroll: true });
        }
      });
    }
    toolbar.append(button);
  }
  const hint = $("#pillbar-hint");
  if (hint) {
    hint.textContent = preferences.mode === "pro"
      ? "Pro · display only"
      : `Beginner: ${pills.length} essentials · hover a pill for a plain explanation`;
  }
}

function renderIndicatorControls(snapshot, preferences, updatePreferences, onSignals) {
  refreshChartMenus();
  renderIndicatorToolbar(snapshot, preferences, updatePreferences, onSignals);
  const details = $("#indicator-details");
  if (details) details.hidden = preferences.mode !== "pro";
  const controls = $("#indicator-controls");
  controls.hidden = preferences.mode !== "pro";
  controls.replaceChildren();
  const search = element("label", undefined, "search-label");
  search.append(element("span", "Search supported response indicators"));
  const input = element("input");
  input.type = "search";
  input.id = "indicator-search";
  input.placeholder = "Search indicator name or purpose";
  input.autocomplete = "off";
  search.append(input);
  controls.append(search);
  const toggles = element("div", undefined, "indicator-toggle-list");
  const queryMatches = (id) => {
    const descriptor = EDUCATION[id];
    const query = input.value.trim().toLowerCase();
    return !query || `${id} ${descriptor.title} ${descriptor.group} ${descriptor.measure} ${descriptor.purpose}`.toLowerCase().includes(query);
  };
  for (const id of INDICATOR_IDS) {
    const descriptor = EDUCATION[id];
    const { available, reason: unavailableReason } = indicatorAvailability(snapshot, id);
    const toggle = element("label", undefined, `indicator-toggle${available ? "" : " unavailable"}`);
    toggle.hidden = !queryMatches(id);
    const checkbox = element("input");
    checkbox.type = "checkbox";
    checkbox.checked = preferences.visible.includes(id);
    checkbox.disabled = !available;
    checkbox.setAttribute("aria-label", `${descriptor.title}${available ? "" : `, unavailable: ${unavailableReason}`}`);
    checkbox.addEventListener("change", () => {
      const visible = new Set(preferences.visible);
      if (checkbox.checked) visible.add(id);
      else visible.delete(id);
      updatePreferences({ ...preferences, visible: [...visible] });
    });
    toggle.append(checkbox, element("span", available ? descriptor.title : `${descriptor.title} — unavailable (${unavailableReason})`));
    toggles.append(toggle);
  }
  input.addEventListener("input", () => {
    for (const [index, id] of INDICATOR_IDS.entries()) toggles.children[index].hidden = !queryMatches(id);
  });
  controls.append(toggles);
}

function addIndicatorCard(container, id, snapshot) {
  const descriptor = EDUCATION[id];
  const indicator = snapshot?.indicators?.[id];
  const bindingError = indicatorBindingError(snapshot, id, indicator);
  const status = bindingError
    ? "UNAVAILABLE"
    : indicator.status;
  const card = element("article", undefined, "indicator-card");
  const heading = element("h4", descriptor.title);
  const badge = element("span", status, "state-badge");
  badge.dataset.state = status;
  heading.append(badge);
  card.append(heading);
  if (status === "AVAILABLE") {
    const latest = latestIndicatorValues(indicator.result);
    if (latest.values.length) {
      for (const [name, value] of latest.values) {
        const output = element("p", undefined, "indicator-value");
        output.append(element("span", `${name}: `), element("strong", value));
        card.append(output);
      }
    } else {
      card.append(element("p", "The backend reports an available series, but its latest point has no available value; no earlier or default value is substituted."));
    }
    for (const state of latest.unavailable) card.append(element("p", `Latest point state: ${state}`));
  } else {
    card.append(element("p", status === "WARMUP"
      ? "The backend has not returned a warmed-up value for this indicator."
      : "No usable value is available from this response."));
  }
  if (bindingError) card.append(element("p", `Display withheld: ${bindingError}.`));
  if (indicator?.reason_code) card.append(element("p", `Backend reason: ${indicator.reason_code}`));
  const result = indicator?.result;
  if (!bindingError && result && typeof result === "object") {
    const parameterEntries = Array.isArray(result.parameters)
      ? result.parameters.flatMap((item) => Array.isArray(item) && item.length === 2 ? [`${item[0]}=${stringValue(item[1])}`] : [])
      : ["period", "fast_period", "slow_period", "signal_period", "k_period", "d_period", "standard_deviation_multiplier"]
        .filter((key) => result[key] !== undefined)
        .map((key) => `${key}=${stringValue(result[key])}`);
    const details = [
      ["Method version", result.calculation_version],
      ["Metadata version", result.metadata_version],
      ["Parameters", parameterEntries.join(", ") || undefined],
      ["Output unit", result.unit],
      ["Price unit", result.price_unit],
      ["Timeframe", result.timeframe],
      ["Result as-of", result.as_of],
      ["Snapshot binding", result.snapshot_id],
      ["Quality report binding", result.quality_report_id],
    ];
    for (const [label, value] of details) {
      if (value !== undefined && value !== null) card.append(element("p", `${label}: ${stringValue(value)}`));
    }
  }
  for (const [label, text] of [
    ["Measures", descriptor.measure],
    ["Why it can matter", descriptor.purpose],
    ["Regimes where it may be useful", descriptor.regimes],
    ["Failure modes and limitations", descriptor.failures],
  ]) {
    const explanation = element("p");
    explanation.append(element("strong", `${label}: `), document.createTextNode(text));
    card.append(explanation);
  }
  if (snapshot) {
    const provenance = element("p", undefined, "indicator-provenance-link");
    const link = element("a", "View this response's snapshot and source provenance");
    link.href = "#snapshot-provenance";
    link.setAttribute(
      "aria-label",
      `View snapshot and source provenance for ${snapshot.symbol} (${snapshot.instrument_id}), ${snapshot.timeframe}; snapshot ${snapshot.snapshot_id}, quality report ${snapshot.data_quality.report_id}`,
    );
    provenance.append(link);
    card.append(provenance);
  }
  container.append(card);
}

function renderIndicators(snapshot, preferences) {
  const groups = $("#indicator-groups");
  groups.replaceChildren();
  const grouped = new Map();
  for (const id of shownIndicators(preferences)) {
    if (!EDUCATION[id]) continue;
    const group = EDUCATION[id].group;
    if (!grouped.has(group)) grouped.set(group, []);
    grouped.get(group).push(id);
  }
  if (!grouped.size) {
    groups.append(element("p", "No indicators are selected for display. The API response and analytical evidence are unchanged.", "empty-state"));
    return;
  }
  for (const [groupName, ids] of grouped) {
    const section = element("section", undefined, "indicator-group");
    section.append(element("h3", groupName));
    const cards = element("div", undefined, "indicator-cards");
    for (const id of ids) addIndicatorCard(cards, id, snapshot);
    section.append(cards);
    groups.append(section);
  }
}

function renderOrderFlow(snapshot) {
  const assessment = snapshot?.order_flow;
  const text = assessment
    ? `${stringValue(assessment.status)} · ${stringValue(assessment.reason_code)}. This API does not supply valid trade/book inputs. Footprint, bid/ask delta, CVD, depth and historical liquidity are never inferred from OHLCV candles.`
    : "No order-flow assessment was supplied by this API response. Footprint, bid/ask delta, CVD, depth and liquidity are not inferred from OHLCV candles.";
  $("#order-flow-reason").textContent = text;
}

function appendAnalysisField(container, label, value) {
  if (value === undefined || value === null) return;
  const row = element("div");
  row.append(element("dt", label), element("dd", stringValue(value)));
  container.append(row);
}

function renderAnalysisMetadata(card, result, snapshot) {
  const metadata = element("dl", undefined, "metadata-grid analysis-metadata");
  const parameters = Array.isArray(result.parameters)
    ? result.parameters.flatMap((item) =>
      Array.isArray(item) && item.length === 2
        ? [`${stringValue(item[0])}=${stringValue(item[1])}`]
        : [],
    ).join(", ")
    : undefined;
  for (const [label, value] of [
    ["Method", result.method_label],
    ["Method version", result.calculation_version ?? result.method_version],
    ["Metadata version", result.metadata_version],
    ["Parameters", parameters],
    ["Price unit", result.price_unit],
    ["Volume unit", result.volume_unit],
    ["Timeframe", result.timeframe],
    ["Anchor mode", result.anchor_mode],
    ["Anchor time", result.anchor_time],
    ["Window start", result.window_start],
    ["Window end", result.window_end],
    ["Result as-of", result.as_of],
    ["Snapshot freshness cutoff", snapshot.freshness_cutoff],
    ["Snapshot quality", snapshot.data_quality?.status],
    ["Snapshot binding", result.snapshot_id],
    ["Quality report binding", result.quality_report_id],
  ]) appendAnalysisField(metadata, label, value);
  if (metadata.childElementCount) card.append(metadata);
  const provenance = element("p", undefined, "indicator-provenance-link");
  const link = element("a", "View this response's snapshot and source lineage");
  link.href = "#snapshot-provenance";
  link.setAttribute(
    "aria-label",
    `View source lineage for ${snapshot.symbol} (${snapshot.instrument_id}), ${snapshot.timeframe}; snapshot ${snapshot.snapshot_id}, quality report ${snapshot.data_quality.report_id}`,
  );
  provenance.append(link);
  card.append(provenance);
}

function addReturnedFields(container, record, fields) {
  if (!record || typeof record !== "object") return;
  for (const [key, label] of fields) {
    if (record[key] !== undefined && record[key] !== null) {
      container.append(element("p", `${label}: ${stringValue(record[key])}`));
    }
  }
}

function renderVwap(card, result) {
  card.append(element(
    "p",
    "Cumulative bar-based typical-price VWAP anchored to the first candle in this returned snapshot. This is an OHLCV approximation, not trade-by-trade or session VWAP.",
  ));
  const table = element("table");
  const head = element("thead");
  const header = element("tr");
  for (const label of ["Candle end", "Point status", "Value", "Reason"]) {
    header.append(element("th", label));
  }
  head.append(header);
  table.append(head);
  const body = element("tbody");
  for (const point of result.points) {
    const value = point?.value;
    const state = value?.status ?? "MISSING";
    const exact = card.dataset.withholdValues !== "true" &&
        state === "READY" && typeof value?.value === "string" &&
        /^-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(value.value) &&
        Number.isFinite(Number(value.value))
      ? `${value.value} ${stringValue(result.price_unit)}`
      : "Not available";
    const row = element("tr");
    row.append(
      element("td", stringValue(point?.candle_end)),
      element("td", stringValue(state)),
      element("td", exact),
      element("td", stringValue(value?.reason)),
    );
    body.append(row);
  }
  table.append(body);
  const scroll = element("div", undefined, "table-scroll");
  scroll.append(table);
  card.append(scroll);
}

function renderVolumeProfile(card, result) {
  card.append(element(
    "p",
    "Candle-assigned typical-price volume-profile proxy. It assigns each candle's volume to a typical-price bin and is not trade-level volume-at-price.",
  ));
  addReturnedFields(card, result, [
    ["status", "Profile result status"],
    ["reason", "Profile result reason"],
  ]);
  if (result.status !== "READY") {
    card.append(element(
      "p",
      `Profile result status is ${stringValue(result.status)}; returned levels are withheld.`,
    ));
    return;
  }
  addReturnedFields(card, result, card.dataset.withholdValues === "true" ? [] : [
    ["poc_bin_index", "Returned POC bin index"],
    ["value_area_low", `Returned VAL (${stringValue(result.price_unit)})`],
    ["value_area_high", `Returned VAH (${stringValue(result.price_unit)})`],
    ["value_area_volume", `Returned value-area volume (${stringValue(result.volume_unit)})`],
    ["value_area_share", "Returned value-area share"],
    ["value_area_bin_indices", "Returned value-area bin indices"],
    ["high_volume_node_bin_indices", "Returned HVN bin indices"],
    ["low_volume_node_bin_indices", "Returned LVN bin indices"],
  ]);
  const pocIndex = result.poc_bin_index;
  const pocBin = Array.isArray(result.bins)
    ? result.bins.find((bin) => bin?.index === pocIndex)
    : null;
  if (pocBin && card.dataset.withholdValues !== "true") {
    addReturnedFields(card, pocBin, [
      ["lower_bound", `POC bin lower bound (${stringValue(result.price_unit)})`],
      ["upper_bound", `POC bin upper bound (${stringValue(result.price_unit)})`],
      ["assigned_volume", `POC bin assigned volume (${stringValue(result.volume_unit)})`],
    ]);
  }
}

function renderVolumeConfirmation(card, result) {
  card.append(element(
    "p",
    "Raw and trailing volume observations are descriptive. Contextual event/comparison assessment needs caller context; volume exhaustion remains unavailable without reliable order-flow input.",
  ));
  const table = element("table");
  const head = element("thead");
  const header = element("tr");
  for (const label of [
    "Candle end", "Point status", "Raw volume", "Prior volume sum",
    "Trailing average", "Relative volume", "Reason",
  ]) header.append(element("th", label));
  head.append(header);
  table.append(head);
  const body = element("tbody");
  for (const point of result.points ?? []) {
    const row = element("tr");
    row.append(
      element("td", stringValue(point?.candle_end)),
      element("td", stringValue(point?.status)),
      element("td", card.dataset.withholdValues === "true" || point?.raw_volume == null ? "Not available" : `${point.raw_volume} ${stringValue(result.volume_unit)}`),
      element("td", card.dataset.withholdValues === "true" || point?.prior_volume_sum == null ? "Not available" : stringValue(point.prior_volume_sum)),
      element("td", card.dataset.withholdValues === "true" || point?.trailing_average == null ? "Not available" : stringValue(point.trailing_average)),
      element("td", card.dataset.withholdValues === "true" || point?.relative_volume == null ? "Not available" : stringValue(point.relative_volume)),
      element("td", stringValue(point?.reason)),
    );
    body.append(row);
  }
  table.append(body);
  const scroll = element("div", undefined, "table-scroll");
  scroll.append(table);
  card.append(scroll);
  addReturnedFields(card, result, [["lookback", "Lookback"]]);
  addReturnedFields(card, result.assessment, [
    ["status", "Contextual assessment status"],
    ["reason", "Contextual assessment reason"],
  ]);
  addReturnedFields(card, result.price_volume_comparison, [
    ["status", "Price/volume comparison status"],
    ["reason", "Price/volume comparison reason"],
  ]);
  addReturnedFields(card, result.assessment, [
    ["status", "Contextual assessment status"],
  ]);
  addReturnedFields(card, result.exhaustion_assessment, [
    ["status", "Exhaustion assessment status"],
    ["reason", "Exhaustion assessment reason"],
  ]);
  if (Array.isArray(result.limitations)) {
    for (const limitation of result.limitations) {
      card.append(element("p", `Backend limitation: ${stringValue(limitation)}`));
    }
  }
}

function renderPriceActionGeometry(card, result) {
  card.append(element(
    "p",
    "Only backend-supplied candle geometry is shown. Pattern labels, pivots, and support/resistance zones were not inferred because caller policies were not supplied.",
  ));
  const table = element("table");
  const head = element("thead");
  const header = element("tr");
  for (const label of [
    "Candle end", "Open", "High", "Low", "Close", "Signed body",
    "Absolute body", "Range", "Upper wick", "Lower wick", "Close location",
    "Close-location reason", "Range direction", "Range comparison reason",
  ]) header.append(element("th", label));
  head.append(header);
  table.append(head);
  const body = element("tbody");
  for (const geometry of result.geometry) {
    const row = element("tr");
    row.append(
      element("td", stringValue(geometry.candle_end)),
      ...["open", "high", "low", "close", "signed_body", "absolute_body", "range", "upper_wick", "lower_wick"]
        .map((field) => element("td", card.dataset.withholdValues === "true" ? "Not available" : stringValue(geometry[field]))),
      element("td", card.dataset.withholdValues === "true" || geometry.close_location == null
        ? "Not available" : stringValue(geometry.close_location)),
      element("td", stringValue(geometry.close_location_reason)),
      element("td", stringValue(geometry.range_direction)),
      element("td", stringValue(geometry.range_comparison_reason)),
    );
    body.append(row);
  }
  table.append(body);
  const scroll = element("div", undefined, "table-scroll");
  scroll.append(table);
  card.append(scroll);
  if (Array.isArray(result.limitations)) {
    for (const limitation of result.limitations) {
      card.append(element("p", `Backend limitation: ${stringValue(limitation)}`));
    }
  }
}

function renderSpotAnalyses(snapshot) {
  const target = $("#spot-analysis-cards");
  target.replaceChildren();
  const quality = snapshot?.data_quality?.status;
  const reportStatus = snapshot?.data_quality?.report_status;
  const qualityValid = quality === "VALID" && reportStatus === "VALID";
  const qualityMessage = qualityValid
    ? "Each result below is bound to this response's selected instrument, timeframe, snapshot, quality report, candle lineage, and cutoff."
    : `Analysis values withheld because snapshot quality is ${stringValue(quality)} (underlying report: ${stringValue(reportStatus)}); VALID quality is required.`;
  $("#spot-analysis-status").textContent = qualityMessage;
  $("#spot-analysis-status").dataset.state = qualityValid ? "valid" : quality === "STALE" ? "warning" : "error";
  if (!snapshot) {
    target.append(element("p", "No snapshot is loaded; no Spot analyses are displayed.", "empty-state"));
    return;
  }
  for (const id of SPOT_ANALYSIS_IDS) {
    const analysis = snapshot.spot_analysis?.[id];
    const card = element("article", undefined, "analysis-card");
    card.dataset.analysisKey = id;
    const status = analysis && ["AVAILABLE", "PARTIAL", "WARMUP", "UNAVAILABLE"].includes(analysis.status)
      ? analysis.status
      : analysis ? "UNKNOWN" : "MISSING";
    const heading = element("h3", SPOT_ANALYSIS_LABELS[id]);
    const badge = element("span", status, "state-badge");
    badge.dataset.state = status;
    heading.append(badge);
    card.append(heading);
    if (analysis?.reason_code) {
      card.append(element("p", `Backend reason: ${stringValue(analysis.reason_code)}`));
    } else if (!analysis) {
      card.append(element("p", "This response did not supply this spot_analysis entry."));
    }
    if (!analysis || status === "UNKNOWN") {
      target.append(card);
      continue;
    }
    const result = analysis.result;
    if (result == null) {
      card.append(element("p", "No result payload was supplied; result values are withheld."));
      target.append(card);
      continue;
    }
    if (!qualityValid) {
      card.append(element("p", "Result payload withheld because snapshot quality is not VALID."));
      target.append(card);
      continue;
    }
    const bindingError = spotAnalysisBindingError(snapshot, id, analysis);
    if (bindingError) {
      card.append(element("p", `Result payload withheld: ${bindingError}.`));
      target.append(card);
      continue;
    }
    card.dataset.withholdValues = String(status === "UNAVAILABLE");
    if (status === "UNAVAILABLE") {
      card.append(element("p", "Backend status is UNAVAILABLE; result values are withheld."));
    }
    renderAnalysisMetadata(card, result, snapshot);
    if (id === "vwap") renderVwap(card, result);
    if (id === "volume-profile") renderVolumeProfile(card, result);
    if (id === "volume-confirmation") renderVolumeConfirmation(card, result);
    if (id === "price-action-support-resistance") renderPriceActionGeometry(card, result);
    target.append(card);
  }
}

function svgText(svg, x, y, text, className = "axis-label") {
  const node = svgNode("text", { x, y, class: className });
  node.textContent = text;
  svg.append(node);
  return node;
}

function numberForPlot(exact) {
  const value = Number(exact);
  return Number.isFinite(value) ? value : null;
}

function makeLine(values, candleIndexes, yOf, left, width) {
  const positions = [];
  for (const item of values) {
    const index = candleIndexes.get(Date.parse(item.candleEnd));
    const value = numberForPlot(item.value);
    if (index === undefined || value === null) continue;
    const y = yOf(value);
    if (y === null || !Number.isFinite(y)) continue;
    const x = left + (candleIndexes.size <= 1 ? width / 2 : index * width / (candleIndexes.size - 1));
    positions.push(`${x},${y}`);
  }
  return positions.length > 1 ? positions.join(" ") : "";
}

// Display-only chart view state (visible window, price scale, rendered
// width). It never changes which values are returned; the window resets when
// the snapshot changes.
const chartView = { key: null, window: null, scale: "auto", width: 0 };
const layoutState = { fullscreen: false };
let refreshChartMenus = () => {};
// Set by mountCharts: pane collapse/move actions.
let chartHandlers = { onPane: () => {} };

// U4: the owner's own annotations (browser-only, never evidence or API data).
const drawingState = { tool: "cursor", pending: [] };
const markerState = { response: null, error: null, selected: 0, accountSize: null, riskPct: null, onSelect: null, choice: null };

function currentMarkers(snapshot, preferences) {
  if (!preferences?.signals) return null;
  const response = markerState.response;
  return response && !markersBindingError(response, snapshot) && response.status === "AVAILABLE"
    ? response
    : null;
}

function priceDecimalsFor(snapshot) {
  return displayDecimals(snapshot?.candles?.at(-1)?.metrics?.close?.value);
}

function renderStrategyMarkers(svg, snapshot, candles, xOf, priceY, preferences) {
  const response = currentMarkers(snapshot, preferences);
  if (!response) return;
  const group = svgNode("g", { class: "strategy-markers", "clip-path": "url(#price-pane-clip)" });
  for (const anchor of markerAnchors(response.markers, candles.map(({ source }) => source.open_time))) {
    const { values } = candles[anchor.candleIndex];
    const x = xOf(anchor.candleIndex);
    const buy = anchor.side === "BUY";
    const y = priceY(buy ? values.low.numeric : values.high.numeric);
    if (y === null) continue;
    const tip = buy ? y + 6 : y - 6;
    const base = buy ? tip + 10 : tip - 10;
    const shape = svgNode("polygon", {
      points: `${x},${tip} ${x - 6},${base} ${x + 6},${base}`,
      class: `strategy-marker strategy-marker-${buy ? "buy" : "sell"}${anchor.pending ? " pending" : ""}${anchor.markerIndex === markerState.selected ? " selected" : ""}`,
      "data-marker-index": String(anchor.markerIndex),
      tabindex: "0",
      role: "button",
      "aria-label": `${anchor.side} marker${anchor.pending ? " (pending fill)" : ""} of a FAILED strategy, illustration only — open its evidence`,
    });
    const select = (event) => {
      event.stopPropagation();
      markerState.onSelect?.(anchor.markerIndex);
    };
    shape.addEventListener("click", select);
    shape.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(event); }
    });
    group.append(shape);
  }
  svg.append(group);
}

// A labelled marker value at display precision; the exact backend string is
// kept on hover (U5b).
function labelledValue(field, key, priceDecimals) {
  const wrapper = element("span", undefined, "labelled-value");
  const shown = markerFieldDisplay(key, field.value, priceDecimals);
  const text = element("span", shown.text, "labelled-value-text");
  if (shown.exact !== null) {
    text.title = `Exact value: ${shown.exact}`;
    text.dataset.exact = shown.exact;
  }
  wrapper.append(
    text,
    element("span", MARKER_LABELS[field.label] ?? "Unlabelled", `label-badge label-${String(field.label).toLowerCase()}`),
  );
  if (field.reason) wrapper.append(element("span", field.reason, "labelled-value-reason"));
  return wrapper;
}

function displayTime(value) {
  const shown = markerFieldDisplay("time", value);
  return shown.text;
}

// SIGNALS controls (U5b): off by default; when on, the owner picks the
// strategy and its recorded verdict is shown as a banner on the chart and here.
function markerVerdictBanner(choice) {
  const response = markerState.response;
  const verdict = response?.study_verdict;
  if (verdict && typeof verdict.strategy_sha256 === "string" && /^[a-f0-9]{64}$/.test(verdict.strategy_sha256) && verdict.strategy_sha256 === response.strategy?.content_sha256 && typeof verdict.status === "string") {
    return {
      tone: verdict.status === "FAIL" ? "fail" : "warning",
      title: `${choice.strategy} v${choice.version} — imported ${verdict.status === "FAIL" ? "FAILED" : verdict.status} verdict (${verdict.report_created_at ?? "date unavailable"}). Illustration only, not a trade signal.`,
      summary: `Imported record ${verdict.verdict_id ?? "unavailable"} · ${verdict.protocol_id ?? "protocol unavailable"} v${verdict.protocol_version ?? "?"} · imported ${verdict.recorded_at ?? "date unavailable"}`,
      reasons: Array.isArray(verdict.reasons) ? verdict.reasons : [],
    };
  }
  const recorded = verdictBanner(choice.strategy, choice.version);
  return { ...recorded, summary: `Separately recorded study on #516; not an imported verdict. ${recorded.summary ?? ""} Imported status: ${verdict?.status ?? "awaiting marker response"}${verdict?.reason ? ` — ${verdict.reason}` : ""}.` };
}

function renderMarkerControls(snapshot, preferences, timeframe, { onSignals, onStrategy }) {
  const controls = $("#markers-controls");
  const banner = $("#markers-banner");
  const chartBanner = $("#chart-signal-banner");
  if (!controls || !banner) return;
  controls.replaceChildren();
  banner.replaceChildren();
  if (!preferences.signals) {
    controls.append(element("p", "SIGNALS is off. Choose a strategy and version to inspect its replay and sourced study evidence. Illustration only, not a trade signal.", "card-note"));
    if (chartBanner) chartBanner.hidden = true;
    return;
  }
  const label = element("label", "Strategy");
  const select = element("select");
  select.id = "marker-strategy";
  const prompt = element("option", "Choose strategy / version…");
  prompt.value = "";
  select.append(prompt);
  for (const option of markerStrategyOptions(timeframe)) {
    const identity = `${option.strategy} v${option.version}`;
    const node = element("option", option.usable ? identity : `${identity} — ${option.reason}`);
    node.value = option.value;
    node.disabled = !option.usable;
    select.append(node);
  }
  select.value = markerState.choice?.key ?? "";
  select.addEventListener("change", () => onStrategy(select.value));
  label.append(select);
  const off = element("button", "Hide markers");
  off.type = "button";
  off.id = "signals-off";
  off.addEventListener("click", () => onSignals(false));
  controls.append(label, off);
  const choice = markerState.choice;
  if (!choice) {
    if (chartBanner) chartBanner.hidden = true;
    return;
  }
  const info = markerVerdictBanner(choice);
  const box = element("div", undefined, "verdict-banner");
  box.dataset.tone = info.tone;
  box.setAttribute("role", "note");
  box.append(element("strong", info.title));
  if (info.summary) box.append(element("p", info.summary));
  if (info.reasons.length) {
    const reasons = element("ul");
    for (const reason of info.reasons) reasons.append(element("li", reason));
    box.append(reasons);
  }
  banner.append(box);
  if (chartBanner) {
    chartBanner.hidden = false;
    chartBanner.dataset.tone = info.tone;
    chartBanner.textContent = info.title;
  }
}

function renderMarkersPanel(snapshot, preferences) {
  const body = $("#markers-body");
  if (!body) return;
  body.replaceChildren();
  const response = markerState.response;
  if (!snapshot) {
    body.append(element("p", "No snapshot is loaded; no strategy markers are shown.", "empty-state"));
    return;
  }
  if (!preferences.signals) return;
  if (!markerState.choice) {
    body.append(element("p", "Choose a strategy and version to read its markers. No strategy is selected automatically.", "empty-state"));
    return;
  }
  if (markerState.error || !response) {
    body.append(element("p", markerState.error ?? "Loading strategy markers…", "empty-state"));
    return;
  }
  const bindingError = markersBindingError(response, snapshot);
  if (bindingError) {
    body.append(element("p", `${bindingError} No markers are shown.`, "empty-state"));
    return;
  }
  const decimals = priceDecimalsFor(snapshot);
  const strategy = response.strategy ?? {};
  const scope = element("p", `${strategy.strategy_id ?? "strategy"} v${strategy.version ?? "?"} · strategy sha256 ${String(strategy.content_sha256 ?? "").slice(0, 12)}… · ${response.evidence_scope ?? ""}`, "card-note");
  scope.title = `Strategy sha256 ${strategy.content_sha256 ?? "not reported"}`;
  body.append(scope);
  if (response.status !== "AVAILABLE") {
    body.append(element("p", `Strategy markers ${response.status}: ${response.reason_code ?? "no reason given"}. No markers are shown.`, "empty-state"));
    return;
  }
  body.append(element("p", `${response.markers.length} markers · position ${response.position ?? "unknown"}.`, "markers-summary"));
  if (!response.markers.length) {
    body.append(element("p", "No markers in this snapshot. An empty replay is not a recorded NO_TRADE decision.", "empty-state"));
    return;
  }
  const list = element("div", undefined, "marker-list");
  list.setAttribute("role", "group");
  list.setAttribute("aria-label", "Strategy markers");
  response.markers.forEach((marker, index) => {
    const when = marker.status === "FILLED" ? marker.fill_time?.value : marker.time?.value;
    const button = element("button", `${marker.side === "BUY" ? "▲ BUY" : "▼ SELL"} ${when ? displayTime(when) : ""}${marker.status === "FILLED" ? "" : " · pending"}`, `marker-item marker-item-${String(marker.side).toLowerCase()}`);
    button.type = "button";
    button.dataset.markerIndex = String(index);
    if (when) button.title = `Exact time: ${when}`;
    button.setAttribute("aria-pressed", String(index === markerState.selected));
    button.addEventListener("click", () => markerState.onSelect?.(index));
    list.append(button);
  });
  body.append(list);
  const marker = response.markers[Math.min(markerState.selected, response.markers.length - 1)];
  const detail = element("div", undefined, "marker-detail");
  detail.id = "marker-detail";
  const section = (title, open) => {
    const node = element("details", undefined, "marker-section");
    node.open = open;
    node.append(element("summary", title));
    return node;
  };
  const conditions = section("Conditions", true);
  const conditionList = element("ul", undefined, "condition-list");
  for (const condition of marker.conditions ?? []) {
    const item = element("li");
    item.append(element("strong", `${condition.met ? "✓" : "✗"} ${condition.condition ?? ""}`));
    for (const [key, value] of Object.entries(condition)) {
      if (value && typeof value === "object" && "label" in value) {
        const row = element("div", undefined, "marker-field");
        row.append(element("span", key.replaceAll("_", " "), "marker-field-name"), labelledValue(value, key, decimals));
        item.append(row);
      }
    }
    conditionList.append(item);
  }
  conditions.append(conditionList);
  const trade = section("Trade details", true);
  const table = element("dl", undefined, "marker-fields");
  for (const row of tradeDetails(marker)) {
    const value = element("dd");
    value.append(labelledValue(row, row.key, decimals));
    table.append(element("dt", row.name), value);
  }
  if (marker.position_size?.capped) table.append(element("dt", "Size cap"), element("dd", "Capped at account ÷ entry (Spot, no leverage)."));
  trade.append(table);
  const evidence = section("Evidence", false);
  const facts = element("dl", undefined, "marker-fields");
  const costs = response.costs ?? {};
  for (const [name, value, exact] of [
    ["Snapshot", String(response.snapshot_id ?? "—").slice(0, 8), response.snapshot_id],
    ["Quality report", String(response.quality_report_id ?? "—").slice(0, 8), response.quality_report_id],
    ["Data quality", response.data_quality_status ?? "—", null],
    ["As of", response.as_of ? displayTime(response.as_of) : "—", response.as_of],
    ["Costs", `${markerFieldDisplay("fee_bps_per_side", costs.fee_bps_per_side).text} bps fee + ${markerFieldDisplay("slippage_bps_per_side", costs.slippage_bps_per_side).text} bps slippage per side (${costs.label ?? "unlabelled"})`, costs.basis],
  ]) {
    const dd = element("dd", value);
    if (exact) dd.title = String(exact);
    facts.append(element("dt", name), dd);
  }
  for (const [name, field] of Object.entries(response.not_applicable ?? {})) {
    const value = element("dd");
    value.append(labelledValue(field, name, decimals));
    facts.append(element("dt", name.replaceAll("_", " ")), value);
  }
  evidence.append(facts);
  detail.append(conditions, trade, evidence);
  body.append(detail);
}

function drawingStatusText() {
  const tool = drawingTool(drawingState.tool);
  if (!tool || tool.clicks === 0) return `${tool?.title ?? "Select / pan"} · ${DRAWING_LABEL}.`;
  const steps = {
    long: ["entry", "stop", "target"], short: ["entry", "stop", "target"],
    fib: ["swing start", "swing end"], range: ["from price", "to price"],
  }[tool.id];
  const next = drawingState.pending.length;
  const what = steps ? steps[next] : `point ${next + 1}`;
  return `${tool.title} — click ${what} (${next + 1} of ${tool.clicks}). ${DRAWING_LABEL}.`;
}

function renderDrawings(svg, ctx) {
  const group = svgNode("g", {
    class: "user-drawings",
    "clip-path": "url(#price-pane-clip)",
    "data-drawing-count": String(ctx.drawings.length),
    "aria-label": `${ctx.drawings.length} of your drawings. ${DRAWING_LABEL}.`,
  });
  const titled = (node, text) => {
    const title = svgNode("title");
    title.textContent = `${text} · ${DRAWING_LABEL}`;
    node.prepend(title);
    return node;
  };
  const hLine = (target, y, x1, className) =>
    target.append(svgNode("line", { x1, x2: ctx.right, y1: y, y2: y, class: className }));
  for (const drawing of ctx.drawings) {
    const points = drawing.anchors.map(({ time, price }) => ({ x: ctx.timeX(time), y: ctx.priceY(price), price }));
    if (points.some((point) => point.y === null || !Number.isFinite(point.y))) continue;
    if (drawing.type !== "hline" && points.some((point) => point.x === null)) continue;
    const node = svgNode("g", { class: `user-drawing drawing-${drawing.type}`, "data-drawing-type": drawing.type });
    const [a, b, c] = points;
    let description = "";
    if (drawing.type === "hline") {
      hLine(node, a.y, ctx.left, "drawing-line");
      svgText(node, ctx.right - 4, a.y - 4, ctx.formatPrice(a.price), "drawing-label").setAttribute("text-anchor", "end");
      description = `Horizontal line at ${ctx.formatPrice(a.price)}`;
    } else if (drawing.type === "trend") {
      node.append(svgNode("line", { x1: a.x, x2: b.x, y1: a.y, y2: b.y, class: "drawing-line" }));
      description = `Trend line ${ctx.formatPrice(a.price)} → ${ctx.formatPrice(b.price)}`;
    } else if (drawing.type === "rect") {
      node.append(svgNode("rect", {
        x: Math.min(a.x, b.x), y: Math.min(a.y, b.y),
        width: Math.max(1, Math.abs(b.x - a.x)), height: Math.max(1, Math.abs(b.y - a.y)), class: "drawing-zone",
      }));
      description = `Zone ${ctx.formatPrice(Math.min(a.price, b.price))}–${ctx.formatPrice(Math.max(a.price, b.price))}`;
    } else if (drawing.type === "range") {
      const range = priceRange(a.price, b.price);
      node.append(svgNode("line", { x1: a.x, x2: b.x, y1: a.y, y2: b.y, class: "drawing-line drawing-range" }));
      const sign = range.change >= 0 ? "+" : "−";
      description = `${sign}${ctx.formatPrice(Math.abs(range.change))} (${sign}${Math.abs(range.percent).toFixed(2)}%)`;
      svgText(node, b.x + 4, b.y - 4, description, "drawing-label");
      description = `Price range ${description}`;
    } else if (drawing.type === "fib") {
      for (const level of fibLevels(a.price, b.price)) {
        const y = ctx.priceY(level.price);
        if (y === null || !Number.isFinite(y)) continue;
        hLine(node, y, Math.min(a.x, b.x), "drawing-line drawing-fib-level");
        svgText(node, Math.min(a.x, b.x) + 4, y - 3, `${level.ratio} · ${ctx.formatPrice(level.price)}`, "drawing-label");
      }
      description = `Fibonacci retracement ${ctx.formatPrice(a.price)} → ${ctx.formatPrice(b.price)}`;
    } else if (drawing.type === "long" || drawing.type === "short") {
      const summary = positionSummary(drawing.type, a.price, b.price, c.price);
      const x1 = a.x;
      node.append(
        svgNode("rect", { x: x1, y: Math.min(a.y, c.y), width: Math.max(1, ctx.right - x1), height: Math.max(1, Math.abs(c.y - a.y)), class: "drawing-zone zone-reward" }),
        svgNode("rect", { x: x1, y: Math.min(a.y, b.y), width: Math.max(1, ctx.right - x1), height: Math.max(1, Math.abs(b.y - a.y)), class: "drawing-zone zone-risk" }),
      );
      hLine(node, a.y, x1, "drawing-line");
      const side = drawing.type === "long" ? "Long" : "Short (Spot cannot short — research only)";
      const label = summary.valid
        ? `${side} · R ${summary.rMultiple.toFixed(2)} · risk ${summary.riskPercent.toFixed(2)}% · reward ${summary.rewardPercent.toFixed(2)}%`
        : `${side} · ${summary.reason}`;
      svgText(node, x1 + 4, a.y - 4, label, "drawing-label");
      description = `${label}; entry ${ctx.formatPrice(a.price)}, stop ${ctx.formatPrice(b.price)}, target ${ctx.formatPrice(c.price)}`;
    } else if (drawing.type === "note") {
      svgText(node, a.x, a.y, drawing.text, "drawing-label drawing-note");
      description = `Note: ${drawing.text}`;
    }
    group.append(titled(node, description));
  }
  for (const anchor of ctx.pending) {
    const x = ctx.timeX(anchor.time);
    const y = ctx.priceY(anchor.price);
    if (x !== null && y !== null) group.append(svgNode("circle", { cx: x, cy: y, r: 4, class: "drawing-pending" }));
  }
  svg.append(group);
}

function renderDrawingTools(mode, onChange, onClear) {
  const nav = $("#drawing-tools");
  if (!nav) return;
  nav.replaceChildren();
  const tools = toolsForMode(mode);
  if (!tools.some((tool) => tool.id === drawingState.tool)) {
    drawingState.tool = "cursor";
    drawingState.pending = [];
  }
  for (const tool of tools) {
    const button = element("button", tool.glyph, "drawing-tool");
    button.type = "button";
    button.dataset.drawingTool = tool.id;
    button.title = `${tool.title} — ${DRAWING_LABEL}`;
    button.setAttribute("aria-label", button.title);
    if (tool.id !== "clear") button.setAttribute("aria-pressed", String(drawingState.tool === tool.id));
    button.addEventListener("click", () => {
      drawingState.pending = [];
      if (tool.id === "clear") onClear();
      else drawingState.tool = tool.id;
      renderDrawingTools(mode, onChange, onClear);
      onChange();
    });
    nav.append(button);
  }
  const status = $("#drawing-status");
  if (status) status.textContent = drawingStatusText();
  const note = $("#drawing-note-label");
  if (note) note.hidden = drawingState.tool !== "note";
}

function syncChartView(snapshot, candleCount) {
  const key = `${snapshot.snapshot_id}|${snapshot.instrument_id}|${snapshot.timeframe}|${candleCount}`;
  if (chartView.key !== key) {
    chartView.key = key;
    chartView.window = null;
  }
  return normaliseChartWindow(chartView.window, candleCount);
}

function renderChartToolbar(snapshot, preferences, view, candleCount, scale) {
  const toolbar = element("div", undefined, "chart-toolbar");
  toolbar.setAttribute("role", "toolbar");
  toolbar.setAttribute("aria-label", "Chart view controls (display only)");
  const rerender = (action) => {
    renderChart(snapshot, preferences);
    $(`#chart-container [data-chart-action="${action}"]`)?.focus();
  };
  const button = (action, label, title, onClick, pressed) => {
    const node = element("button", label, "chart-tool");
    node.type = "button";
    node.dataset.chartAction = action;
    node.title = title;
    if (pressed !== undefined) node.setAttribute("aria-pressed", String(pressed));
    node.addEventListener("click", () => { onClick(); rerender(action); });
    return node;
  };
  const zoomGroup = element("span", undefined, "chart-tool-group");
  zoomGroup.setAttribute("role", "group");
  zoomGroup.setAttribute("aria-label", "Zoom and pan");
  const step = Math.max(1, Math.round(view.count / 4));
  zoomGroup.append(
    button("zoom-in", "+", "Zoom in (also mouse wheel or + key on the chart)", () => {
      chartView.window = zoomChartWindow(view, 0.5, candleCount);
    }),
    button("zoom-out", "−", "Zoom out (also mouse wheel or - key on the chart)", () => {
      chartView.window = zoomChartWindow(view, 2, candleCount);
    }),
    button("pan-left", "◀", "Show earlier candles (also drag the chart)", () => {
      chartView.window = panChartWindow(view, -step, candleCount);
    }),
    button("pan-right", "▶", "Show later candles (also drag the chart)", () => {
      chartView.window = panChartWindow(view, step, candleCount);
    }),
    button("reset", "Reset", "Show every returned candle with the Auto scale", () => {
      chartView.window = null;
      chartView.scale = "auto";
    }),
  );
  const range = element(
    "span",
    `Showing candles ${view.start + 1}–${view.start + view.count} of ${candleCount} · scale: ${scale.mode === "percent" ? "%" : scale.mode === "log" ? "Log" : "Auto"}`,
    "chart-view-range",
  );
  range.id = "chart-view-range";
  range.setAttribute("role", "status");
  const scaleGroup = element("span", undefined, "chart-tool-group");
  scaleGroup.setAttribute("role", "group");
  scaleGroup.setAttribute("aria-label", "Price scale");
  for (const [mode, label, title] of [
    ["auto", "Auto", "Linear price scale fitted to the visible candles"],
    ["log", "Log", "Logarithmic price scale"],
    ["percent", "%", "Percent change from the first visible close"],
  ]) {
    scaleGroup.append(button(`scale-${mode}`, label, title, () => { chartView.scale = mode; }, chartView.scale === mode));
  }
  toolbar.append(zoomGroup, range);
  if (scale.reason) toolbar.append(element("span", scale.reason, "chart-view-note"));
  toolbar.append(scaleGroup);
  return toolbar;
}

const CHART_GEOMETRY = Object.freeze({ left: 8, right: 84, priceTop: 6, volume: 76, pane: 112, collapsed: 24, gap: 6, axis: 24 });

// Height of the price pane: the price + volume viewport is at least 60% of the
// window (UR1); in full screen the whole chart fits the window.
function pricePaneHeight(panesHeight) {
  const { volume, gap, axis, priceTop } = CHART_GEOMETRY;
  const viewport = layoutState.fullscreen
    ? window.innerHeight - 230 - panesHeight
    : Math.round(window.innerHeight * 0.6);
  return Math.max(240, viewport - volume - gap - axis - priceTop);
}

function legendText(svg, x, y, parts, className) {
  const node = svgNode("text", { x, y, class: `chart-legend ${className ?? ""}`.trim() });
  for (const part of parts) {
    const span = svgNode("tspan", { class: part.className ?? "" });
    if (part.color) span.setAttribute("fill", part.color);
    if (part.series) span.dataset.series = part.series;
    span.textContent = part.text;
    node.append(span);
  }
  svg.append(node);
  return node;
}

function renderChart(snapshot, preferences) {
  const target = $("#chart-container");
  const response = snapshotCandles(snapshot);
  if (response.error) {
    target.replaceChildren(element("p", response.error, "empty-state"));
    return;
  }
  const allCandles = response.candles;
  const view = syncChartView(snapshot, allCandles.length);
  const candles = allCandles.slice(view.start, view.start + view.count);
  const candleIndexes = new Map(candles.map(({ source }, index) => [Date.parse(source.close_time), index]));
  const inView = (point) => candleIndexes.has(Date.parse(point.candleEnd));
  const enabled = shownIndicators(preferences);
  const qualityValid = snapshot.data_quality?.status === "VALID" && snapshot.data_quality?.report_status === "VALID";
  const vwapAnalysis = snapshot.spot_analysis?.vwap;
  const vwapPoints = enabled.includes("vwap") && qualityValid &&
      ["AVAILABLE", "PARTIAL"].includes(vwapAnalysis?.status) &&
      !spotAnalysisBindingError(snapshot, "vwap", vwapAnalysis) && Array.isArray(vwapAnalysis.result?.points)
    ? vwapAnalysis.result.points.flatMap((point) =>
      point?.value?.status === "READY" &&
        typeof point.value.value === "string" &&
        /^-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(point.value.value) &&
        Number.isFinite(Number(point.value.value)) &&
        candles.some(({ source }) =>
          Date.parse(source.close_time) === Date.parse(point.candle_end))
        ? [{ candleEnd: point.candle_end, value: point.value.value }]
        : [],
    )
    : [];
  const volumeAnalysis = snapshot.spot_analysis?.["volume-confirmation"];
  const volumeReference = qualityValid && !spotAnalysisBindingError(snapshot, "volume-confirmation", volumeAnalysis)
    ? volumeReferenceLine(volumeAnalysis)
    : null;
  const available = (id) => {
    const indicator = snapshot.indicators?.[id];
    return indicator?.status === "AVAILABLE" && !indicatorBindingError(snapshot, id, indicator) && indicator.result;
  };

  // Overlays on the price pane and sub-panes (UR2), each with one colour.
  const overlays = [];
  for (const id of Object.keys(OVERLAY_SERIES)) {
    if (!enabled.includes(id) || !available(id)) continue;
    for (const series of OVERLAY_SERIES[id]) overlays.push({ ...series, id, points: plotValues(snapshot.indicators[id].result, series.field) });
  }
  const paneIds = orderedPanes(PANE_DEFINITIONS.map((definition) => definition.id)
    .filter((id) => enabled.includes(id) && available(id)), preferences.paneOrder);
  const panes = paneIds.map((id) => {
    const definition = PANE_DEFINITIONS.find((item) => item.id === id);
    const series = definition.series
      .map((item) => ({ ...item, points: plotValues(snapshot.indicators[id].result, item.field) }))
      .filter((item) => item.points.length > 1);
    return { definition, series, collapsed: preferences.collapsedPanes.includes(id) };
  }).filter((pane) => pane.series.length);

  const { left, right, priceTop, pane: paneHeight, collapsed: collapsedHeight, gap, axis } = CHART_GEOMETRY;
  const volumeHeight = preferences.volume === false ? 0 : CHART_GEOMETRY.volume;
  const width = Math.max(480, Math.round(target.clientWidth || 960));
  chartView.width = width;
  const plotWidth = width - left - right;
  const panesHeight = panes.reduce((sum, pane) => sum + gap + (pane.collapsed ? collapsedHeight : paneHeight), 0);
  const priceHeight = pricePaneHeight(panesHeight);
  const volumeTop = priceTop + priceHeight + gap;
  let cursor = volumeTop + volumeHeight;
  for (const pane of panes) {
    cursor += gap;
    pane.top = cursor;
    pane.height = pane.collapsed ? collapsedHeight : paneHeight;
    cursor += pane.height;
  }
  const plotBottom = cursor;
  const height = plotBottom + axis;

  const lows = candles.map(({ values }) => values.low.numeric);
  const highs = candles.map(({ values }) => values.high.numeric);
  const visiblePriceValues = [...lows, ...highs];
  for (const point of vwapPoints.filter(inView)) {
    const number = numberForPlot(point.value);
    if (number !== null) visiblePriceValues.push(number);
  }
  for (const overlay of overlays) for (const point of overlay.points.filter(inView)) {
    const number = numberForPlot(point.value);
    if (number !== null) visiblePriceValues.push(number);
  }
  let priceMin = Math.min(...visiblePriceValues);
  let priceMax = Math.max(...visiblePriceValues);
  const padding = priceMax === priceMin ? Math.max(Math.abs(priceMax) * 0.02, 1) : (priceMax - priceMin) * 0.06;
  const logScaleUsable = chartView.scale !== "log" || priceMin - padding > 0;
  priceMin = logScaleUsable ? priceMin - padding : priceMin;
  priceMax += padding;
  const scale = priceScale({
    minimum: priceMin,
    maximum: priceMax,
    mode: chartView.scale,
    base: candles[0].values.close.numeric,
    divisions: Math.max(4, Math.min(10, Math.round(priceHeight / 64))),
  });
  const svg = svgNode("svg", {
    viewBox: `0 0 ${width} ${height}`,
    width,
    height,
    role: "group",
    "aria-labelledby": "chart-svg-title chart-svg-desc",
    "aria-describedby": "chart-inspector",
    "aria-label": `${snapshot.symbol} ${snapshot.timeframe} candle chart. Use left and right arrow keys to inspect candles, plus and minus to zoom.`,
    tabindex: "0",
    focusable: "true",
    "data-price-top": priceTop,
    "data-price-height": priceHeight,
    "data-price-min": priceMin,
    "data-price-max": priceMax,
    "data-chart-style": preferences.chartStyle,
  });
  const title = svgNode("title", { id: "chart-svg-title" });
  title.textContent = `${snapshot.symbol} ${snapshot.timeframe} ${CHART_STYLES.find((style) => style.id === preferences.chartStyle)?.label ?? "Candlesticks"} · exact API OHLC${snapshot.data_quality?.status === "STALE" ? ", stale" : ""}`;
  svg.append(title);
  const description = svgNode("desc", { id: "chart-svg-desc" });
  description.textContent = `${candles.length} returned finalized candles. Hover over a candle or focus the chart and use the arrow keys to inspect exact returned values.`;
  svg.append(description);
  const priceUnit = candles.at(-1).values.close.unit;
  const volumeUnit = candles.at(-1).values.volume.unit;
  const priceDecimals = displayDecimals(allCandles.at(-1).values.close.exact);
  const formatPrice = (value) => formatDisplayNumber(value, priceDecimals);
  const priceY = (value) => {
    const fraction = scale.fractionOf(value);
    return fraction === null ? null : priceTop + fraction * priceHeight;
  };
  const xOf = (index) => left + (candles.length <= 1 ? plotWidth / 2 : index * plotWidth / (candles.length - 1));

  // Pane frames and the shared time axis.
  svg.append(svgNode("line", { x1: width - right, x2: width - right, y1: priceTop, y2: plotBottom, class: "axis-line" }));
  for (const y of [volumeTop - gap / 2, ...panes.map((pane) => pane.top - gap / 2)]) {
    svg.append(svgNode("line", { x1: 0, x2: width, y1: y, y2: y, class: "pane-separator" }));
  }
  for (const { fraction, value, label } of scale.ticks) {
    const y = priceTop + fraction * priceHeight;
    svg.append(svgNode("line", { x1: left, x2: width - right, y1: y, y2: y, class: "gridline" }));
    const tick = svgText(svg, width - right + 8, y + 4, label ?? formatPrice(value), "axis-label price-axis-tick");
    tick.setAttribute("text-anchor", "start");
  }
  for (const index of timeAxisIndexes(candles.length, Math.max(3, Math.min(10, Math.round(plotWidth / 150))))) {
    const x = xOf(index);
    svg.append(svgNode("line", { x1: x, x2: x, y1: priceTop, y2: plotBottom, class: "gridline gridline-time" }));
    const label = svgText(svg, x, height - 7, axisTimeLabel(candles[index].source.open_time, snapshot.timeframe), "axis-label time-axis-tick");
    label.setAttribute("text-anchor", index === 0 ? "start" : index === candles.length - 1 ? "end" : "middle");
  }

  const candleWidth = Math.max(1, Math.min(14, plotWidth / candles.length * 0.66));
  const volumeMax = Math.max(...candles.map((item) => item.values.volume.numeric));
  const volumeInner = volumeHeight - 18;
  const style = preferences.chartStyle ?? "candles";
  if (style === "line" || style === "step") {
    svg.append(svgNode("path", { d: closePath(candles, xOf, priceY, style === "step"), class: "close-price-line" }));
  }
  candles.forEach(({ values }, index) => {
    const x = xOf(index);
    const up = values.close.numeric >= values.open.numeric;
    if (!["line", "step"].includes(style)) {
    const previous = allCandles[view.start + index - 1]?.values.close.numeric ?? values.open.numeric;
    const colorUp = style === "hollow" ? values.close.numeric >= previous : up;
    svg.append(svgNode("line", {
      x1: x, x2: x, y1: priceY(values.high.numeric), y2: priceY(values.low.numeric),
      class: `candle-wick candle-${colorUp ? "up" : "down"}`,
    }));
    if (style === "bars") {
      svg.append(svgNode("path", {
        d: `M ${x - candleWidth / 2} ${priceY(values.open.numeric)} H ${x} M ${x} ${priceY(values.close.numeric)} H ${x + candleWidth / 2}`,
        class: `ohlc-bar candle-${colorUp ? "up" : "down"}`,
      }));
    } else svg.append(svgNode("rect", {
      x: x - candleWidth / 2,
      y: Math.min(priceY(values.open.numeric), priceY(values.close.numeric)),
      width: candleWidth,
      height: Math.max(1, Math.abs(priceY(values.open.numeric) - priceY(values.close.numeric))),
      class: `candle-body candle-${colorUp ? "up" : "down"}${style === "hollow" && up ? " hollow-body" : ""}`,
    }));
    }
    const barHeight = volumeMax > 0 ? (values.volume.numeric / volumeMax) * volumeInner : 0;
    if (volumeHeight) svg.append(svgNode("rect", {
      x: x - candleWidth / 2,
      y: volumeTop + volumeHeight - barHeight,
      width: candleWidth,
      height: barHeight,
      class: `volume-bar volume-${up ? "up" : "down"}`,
    }));
  });
  for (const overlay of overlays) {
    const polyline = makeLine(overlay.points, candleIndexes, priceY, left, plotWidth);
    if (polyline) svg.append(svgNode("polyline", { points: polyline, class: `indicator-line ${overlay.className}`, stroke: overlay.color, style: `stroke-width:${preferences.studyWidths?.[overlay.id] ?? 2}` }));
  }
  const vwapLine = makeLine(vwapPoints, candleIndexes, priceY, left, plotWidth);
  if (vwapLine) svg.append(svgNode("polyline", { points: vwapLine, class: "indicator-line spot-vwap-line", stroke: VWAP_COLOR, style: `stroke-width:${preferences.studyWidths?.vwap ?? 2}` }));
  const volumeY = (value) => volumeTop + volumeHeight - (value / volumeMax) * volumeInner;
  const volumeLine = volumeHeight && volumeReference && volumeMax > 0
    ? makeLine(volumeReference.points, candleIndexes, volumeY, left, plotWidth)
    : "";
  if (volumeLine) svg.append(svgNode("polyline", { points: volumeLine, class: "volume-average-line", stroke: VOLUME_AVERAGE_COLOR }));

  // Legends: colour-matched to their lines, values follow the crosshair.
  const overlayLegend = [
    ...overlays.flatMap((overlay) => [
      { text: `${overlay.label} `, color: overlay.color, className: `legend-label legend-${overlay.className}` },
      { text: "—", color: overlay.color, series: overlay.className, className: "legend-value" },
      { text: "   " },
    ]),
    ...(vwapLine ? [
      { text: "VWAP ", color: VWAP_COLOR, className: "legend-label legend-spot-vwap-line" },
      { text: "—", color: VWAP_COLOR, series: "spot-vwap-line", className: "legend-value" },
    ] : []),
  ];
  if (overlayLegend.length) legendText(svg, left + 6, priceTop + 15, overlayLegend, "overlay-legend");
  if (volumeHeight) legendText(svg, left + 6, volumeTop + 13, [
    { text: `Vol (${volumeUnit}) `, className: "legend-label" },
    { text: "—", series: "volume", className: "legend-value" },
    ...(volumeLine ? [
      { text: `   Prior-${volumeReference.lookback} average volume · backend `, color: VOLUME_AVERAGE_COLOR, className: "legend-label legend-volume-average-line" },
      { text: "—", color: VOLUME_AVERAGE_COLOR, series: "volume-average", className: "legend-value" },
    ] : []),
  ], "volume-legend");

  const stage = element("div", undefined, "chart-stage");
  const paneTools = [];
  for (const pane of panes) {
    const { definition } = pane;
    const group = svgNode("g", {
      class: `indicator-pane pane-${definition.key}${pane.collapsed ? " collapsed" : ""}`,
      "data-pane": definition.id,
      "data-pane-key": definition.key,
      "data-top": pane.top,
      "data-height": pane.height,
      "data-collapsed": String(pane.collapsed),
    });
    const decimals = definition.priceUnit ? priceDecimals : 2;
    if (!pane.collapsed) {
      const numbers = pane.series.flatMap((series) => series.points.filter(inView).map((point) => numberForPlot(point.value)))
        .filter((value) => value !== null);
      const range = paneRange(definition, numbers);
      if (range) {
        group.setAttribute("data-min", range.min);
        group.setAttribute("data-max", range.max);
        const inner = pane.height - 4;
        const y = (value) => pane.top + 2 + inner - ((value - range.min) / (range.max - range.min)) * inner;
        const ticks = niceTicks(range.min, range.max, 3);
        for (const tick of ticks) {
          group.append(svgNode("line", { x1: left, x2: width - right, y1: y(tick), y2: y(tick), class: "gridline pane-gridline" }));
          const label = svgNode("text", { x: width - right + 8, y: y(tick) + 4, class: "axis-label pane-axis-tick" });
          label.textContent = formatDisplayNumber(tick, Math.abs(tick) < 10 && !Number.isInteger(tick) ? decimals : 0);
          group.append(label);
        }
        for (const reference of definition.reference) {
          if (reference < range.min || reference > range.max) continue;
          group.append(svgNode("line", { x1: left, x2: width - right, y1: y(reference), y2: y(reference), class: "pane-reference", "data-reference": reference }));
          if (ticks.includes(reference)) continue;
          const label = svgNode("text", { x: width - right + 8, y: y(reference) + 4, class: "axis-label pane-reference-label" });
          label.textContent = String(reference);
          group.append(label);
        }
        for (const series of pane.series) {
          if (series.kind === "bars") {
            const zero = y(Math.max(range.min, Math.min(range.max, 0)));
            const barWidth = Math.max(1, candleWidth * 0.8);
            for (const point of series.points) {
              const index = candleIndexes.get(Date.parse(point.candleEnd));
              const value = numberForPlot(point.value);
              if (index === undefined || value === null) continue;
              const top = y(value);
              group.append(svgNode("rect", {
                x: xOf(index) - barWidth / 2, y: Math.min(top, zero), width: barWidth, height: Math.max(1, Math.abs(zero - top)),
                class: `${series.className}-bar ${value >= 0 ? "hist-up" : "hist-down"}`,
                "data-candle-end": point.candleEnd, "data-value": point.value,
              }));
            }
          } else {
            const polyline = makeLine(series.points, candleIndexes, y, left, plotWidth);
            if (polyline) group.append(svgNode("polyline", { points: polyline, class: `indicator-line ${series.className}`, stroke: series.color, style: `stroke-width:${preferences.studyWidths?.[definition.id] ?? 2}` }));
          }
        }
      }
    }
    const legend = svgNode("text", { x: left + 6, y: pane.top + 15, class: "chart-legend pane-legend" });
    const titleSpan = svgNode("tspan", { class: "legend-title" });
    titleSpan.textContent = `${definition.title}  `;
    legend.append(titleSpan);
    for (const series of pane.series) {
      const name = svgNode("tspan", { fill: series.color, class: `legend-label legend-${series.className}` });
      name.textContent = `${series.label} `;
      const value = svgNode("tspan", { fill: series.color, class: "legend-value", "data-series": series.className, "data-decimals": decimals });
      value.textContent = "—";
      const spacer = svgNode("tspan");
      spacer.textContent = "   ";
      legend.append(name, value, spacer);
    }
    group.append(legend);
    svg.append(group);
    const tools = element("div", undefined, "pane-tools");
    tools.style.top = `${pane.top + 2}px`;
    tools.style.right = `${right + 4}px`;
    for (const [action, glyph, label] of [
      ["collapse", pane.collapsed ? "▸" : "▾", `${pane.collapsed ? "Expand" : "Collapse"} the ${definition.title} pane`],
      ["up", "↑", `Move the ${definition.title} pane up`],
      ["down", "↓", `Move the ${definition.title} pane down`],
    ]) {
      const button = element("button", glyph, "pane-tool");
      button.type = "button";
      button.dataset.paneAction = action;
      button.dataset.pane = definition.id;
      button.title = label;
      button.setAttribute("aria-label", label);
      if (action === "collapse") button.setAttribute("aria-expanded", String(!pane.collapsed));
      button.addEventListener("click", () => chartHandlers.onPane(action, definition.id, panes.map((item) => item.definition.id)));
      tools.append(button);
    }
    paneTools.push(tools);
  }

  const tag = lastPriceTag(allCandles.at(-1), allCandles.at(-2));
  const tagY = tag ? priceY(tag.value) : null;
  if (tag && tagY !== null) {
    const y = Math.max(priceTop, Math.min(priceTop + priceHeight, tagY));
    const group = svgNode("g", { class: `last-price-tag last-price-${tag.direction}`, "data-last-price": tag.text });
    group.append(
      svgNode("line", { x1: left, x2: width - right, y1: y, y2: y, class: "last-price-line" }),
      svgNode("rect", { x: width - right + 2, y: y - 10, width: right - 4, height: 20, rx: 3, class: "last-price-box" }),
    );
    const text = svgNode("text", { x: width - right + 8, y: y + 4, class: "last-price-text" });
    text.textContent = formatDisplayNumber(tag.text, priceDecimals);
    const exactTitle = svgNode("title");
    exactTitle.textContent = `Exact returned close: ${tag.text} ${priceUnit}`;
    group.append(exactTitle);
    group.setAttribute("role", "img");
    group.setAttribute("aria-label", `Last returned close: ${tag.text} ${priceUnit}${tagY !== y ? " (outside the visible range)" : ""}`);
    group.append(text);
    svg.append(group);
  }

  const clip = svgNode("clipPath", { id: "price-pane-clip" });
  clip.append(svgNode("rect", { x: left, y: priceTop, width: plotWidth, height: priceHeight }));
  svg.append(clip);
  const drawingKey = drawingsKey(snapshot.instrument_id, snapshot.timeframe);
  const globalIndexes = new Map(allCandles.map(({ source }, index) => [Date.parse(source.close_time), index]));
  const timeX = (time) => {
    const index = globalIndexes.get(Date.parse(time));
    return index === undefined ? null : xOf(index - view.start);
  };
  renderDrawings(svg, {
    drawings: loadDrawings(localStorage, drawingKey),
    pending: drawingState.pending,
    timeX, priceY, formatPrice, left, right: width - right,
  });
  renderStrategyMarkers(svg, snapshot, candles, xOf, priceY, preferences);

  const crosshair = svgNode("line", {
    x1: 0, x2: 0, y1: priceTop, y2: plotBottom,
    class: "chart-crosshair", "pointer-events": "none",
  });
  const marker = svgNode("circle", { cx: 0, cy: 0, r: 4, class: "chart-inspection-marker", "pointer-events": "none" });
  svg.append(crosshair, marker);

  const inspector = element("p", "", "chart-inspector");
  inspector.id = "chart-inspector";
  inspector.setAttribute("aria-live", "polite");
  inspector.setAttribute("aria-atomic", "true");
  const legendValues = [...svg.querySelectorAll(".legend-value[data-series]")];
  const seriesValue = new Map();
  for (const overlay of overlays) seriesValue.set(overlay.className, { points: overlay.points, decimals: priceDecimals, label: overlay.label, priceUnit: true });
  if (vwapLine) seriesValue.set("spot-vwap-line", { points: vwapPoints, decimals: priceDecimals, label: "Spot VWAP", priceUnit: true });
  for (const pane of panes) {
    for (const series of pane.series) {
      seriesValue.set(series.className, {
        points: series.points, decimals: pane.definition.priceUnit ? priceDecimals : 2,
        label: `${pane.definition.title} ${series.label}`, priceUnit: Boolean(pane.definition.priceUnit),
      });
    }
  }
  const inspectCandle = (requestedIndex) => {
    const index = Math.max(0, Math.min(candles.length - 1, requestedIndex));
    const candle = candles[index];
    const x = xOf(index);
    crosshair.setAttribute("x1", String(x));
    crosshair.setAttribute("x2", String(x));
    crosshair.setAttribute("visibility", "visible");
    marker.setAttribute("cx", String(x));
    marker.setAttribute("cy", String(priceY(candle.values.close.numeric)));
    marker.setAttribute("visibility", "visible");
    const candleEnd = Date.parse(candle.source.close_time);
    const exactReadouts = [];
    for (const node of legendValues) {
      const key = node.dataset.series;
      if (key === "volume") {
        node.textContent = formatDisplayNumber(candle.values.volume.exact, displayDecimals(candle.values.volume.exact));
        continue;
      }
      if (key === "volume-average") {
        const point = volumeReference?.points.find((item) => Date.parse(item.candleEnd) === candleEnd);
        node.textContent = point ? formatDisplayNumber(point.value, displayDecimals(point.value)) : "—";
        continue;
      }
      const series = seriesValue.get(key);
      const point = series?.points.find((item) => Date.parse(item.candleEnd) === candleEnd);
      node.textContent = point ? formatDisplayNumber(point.value, series.decimals) : "—";
      if (point) exactReadouts.push(`${series.label}: ${point.value}`);
    }
    const values = candle.values;
    const previous = index > 0 ? candles[index - 1].values.close.numeric : null;
    const change = previous ? ((values.close.numeric - previous) / previous) * 100 : null;
    inspector.replaceChildren(
      element("span", `${candle.source.open_time.slice(0, 16).replace("T", " ")} UTC`, "readout-time"),
      ...[["O", values.open], ["H", values.high], ["L", values.low], ["C", values.close]].flatMap(([label, metric]) => [
        element("span", label, "readout-key"), element("span", formatDisplayNumber(metric.exact, priceDecimals), "readout-value"),
      ]),
      ...(change === null ? [] : [element("span", `${change >= 0 ? "+" : "−"}${Math.abs(change).toFixed(2)}%`, `readout-change change-${change >= 0 ? "up" : "down"}`)]),
      element("span", `Vol ${formatDisplayNumber(values.volume.exact, displayDecimals(values.volume.exact))} ${values.volume.unit}`, "readout-volume"),
    );
    const exact = candleInspectorText(candle, exactReadouts);
    inspector.title = `Exact returned values: ${exact}`;
    inspector.dataset.exact = exact;
    svg.dataset.inspectedIndex = String(index);
  };
  const indexAtPointer = (event) => {
    const rect = svg.getBoundingClientRect();
    return chartIndexAtPointer({
      clientX: event.clientX,
      boundsLeft: rect.left,
      boundsWidth: rect.width,
      viewWidth: width,
      plotLeft: left,
      plotWidth,
      candleCount: candles.length,
    });
  };
  let drag = null;
  svg.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || drawingState.tool !== "cursor") return;
    drag = { clientX: event.clientX, width: svg.getBoundingClientRect().width };
  });
  svg.addEventListener("click", (event) => {
    const tool = drawingTool(drawingState.tool);
    if (!tool || tool.clicks === 0) return;
    const rect = svg.getBoundingClientRect();
    if (rect.height <= 0) return;
    const viewY = ((event.clientY - rect.top) / rect.height) * height;
    const index = indexAtPointer(event);
    if (index === null || viewY < priceTop || viewY > priceTop + priceHeight) return;
    const price = scale.valueAt((viewY - priceTop) / priceHeight);
    if (!Number.isFinite(price) || price <= 0) return;
    drawingState.pending.push({ time: candles[index].source.close_time, price });
    if (drawingState.pending.length >= tool.clicks) {
      const drawing = createDrawing(tool.id, drawingState.pending, $("#drawing-note-text")?.value);
      drawingState.pending = [];
      if (drawing) saveDrawings(localStorage, drawingKey, [...loadDrawings(localStorage, drawingKey), drawing]);
    }
    const status = $("#drawing-status");
    if (status) status.textContent = drawingStatusText();
    renderChart(snapshot, preferences);
  });
  svg.addEventListener("pointerup", (event) => {
    const started = drag;
    drag = null;
    if (!started || started.width <= 0) return;
    const viewDx = ((event.clientX - started.clientX) / started.width) * width;
    const delta = -Math.round((viewDx / plotWidth) * Math.max(1, candles.length - 1));
    if (delta === 0) return;
    chartView.window = panChartWindow(view, delta, allCandles.length);
    renderChart(snapshot, preferences);
  });
  svg.addEventListener("pointermove", (event) => {
    if (!drag) inspectCandle(indexAtPointer(event));
  });
  svg.addEventListener("wheel", (event) => {
    if (!event.deltaY) return;
    event.preventDefault();
    const index = indexAtPointer(event);
    const anchor = index === null || candles.length <= 1 ? 1 : index / (candles.length - 1);
    chartView.window = zoomChartWindow(view, event.deltaY < 0 ? 0.8 : 1.25, allCandles.length, anchor);
    renderChart(snapshot, preferences);
  }, { passive: false });
  svg.addEventListener("keydown", (event) => {
    if (["+", "=", "-", "_"].includes(event.key)) {
      event.preventDefault();
      chartView.window = zoomChartWindow(view, ["+", "="].includes(event.key) ? 0.5 : 2, allCandles.length);
      renderChart(snapshot, preferences);
      $("#chart-container svg")?.focus();
      return;
    }
    const current = Number(svg.dataset.inspectedIndex ?? candles.length - 1);
    const next = moveChartSelection(current, event.key, candles.length);
    if (next !== null) {
      event.preventDefault();
      inspectCandle(next);
    }
  });
  inspectCandle(candles.length - 1);
  stage.append(svg, ...paneTools);
  target.replaceChildren(inspector, stage, renderChartToolbar(snapshot, preferences, view, allCandles.length, scale));
}

function renderCandles(snapshot) {
  const tbody = $("#candle-rows");
  tbody.replaceChildren();
  const response = snapshotCandles(snapshot);
  if (response.error) {
    const row = element("tr");
    row.append(element("td", response.error));
    row.firstChild.colSpan = 7;
    tbody.append(row);
    return;
  }
  for (const { source, values } of response.candles) {
    const row = element("tr");
    row.append(
      element("td", source.open_time),
      element("td", `${values.open.exact} ${stringValue(values.open.unit)}`),
      element("td", `${values.high.exact} ${stringValue(values.high.unit)}`),
      element("td", `${values.low.exact} ${stringValue(values.low.unit)}`),
      element("td", `${values.close.exact} ${stringValue(values.close.unit)}`),
      element("td", `${values.volume.exact} ${stringValue(values.volume.unit)}`),
      element("td", stringValue(source.market_data_id)),
    );
    tbody.append(row);
  }
}

function renderMetadata(snapshot) {
  const metadata = $("#snapshot-metadata");
  const sources = $("#source-list");
  metadata.replaceChildren();
  sources.replaceChildren();
  if (!snapshot) {
    metadata.append(element("div"));
    metadata.firstChild.append(element("dt", "Instrument / venue"), element("dd", "No snapshot loaded"));
    return;
  }
  const entries = [
    ["Exact instrument / symbol", `${stringValue(snapshot.instrument_id)} · ${stringValue(snapshot.symbol)}`],
    ["Venue", snapshot.venue_id],
    ["Timeframe", snapshot.timeframe],
    ["Returned candles", String(snapshot.candles.length)],
    ["As of", isoText(snapshot.as_of)],
    ["Freshness cutoff", isoText(snapshot.freshness_cutoff)],
    ["Requested as-of cutoff", snapshot.requested_as_of ? isoText(snapshot.requested_as_of) : "None · current read"],
    ["Temporal context", snapshot.temporal_context === "HISTORICAL" ? "HISTORICAL — NOT CURRENT" : snapshot.temporal_context],
    ["Snapshot ID", snapshot.snapshot_id],
    ["Quality report ID", snapshot.data_quality?.report_id],
    ["Quality status", snapshot.data_quality?.status],
    ["Underlying report status", snapshot.data_quality?.report_status],
    ["Quality policy version", snapshot.data_quality?.policy_version],
    ["Quality policy SHA-256", snapshot.data_quality?.policy_sha256],
    ["Comparison assessment", snapshot.data_quality?.comparison_assessment],
    ["Persisted", typeof snapshot.persisted === "boolean" ? String(snapshot.persisted) : undefined],
    ["Adapter version", snapshot.lineage?.adapter_version],
  ];
  for (const [label, value] of entries) {
    const cell = element("div");
    cell.append(element("dt", label), element("dd", stringValue(value)));
    metadata.append(cell);
  }
  const report = snapshot.data_quality?.report;
  if (report && typeof report === "object") {
    for (const key of ["assessed_at", "required_data_cutoff", "snapshot_id", "status"]) {
      if (report[key] === undefined) continue;
      const cell = element("div");
      cell.append(element("dt", `Report ${key}`), element("dd", stringValue(report[key])));
      metadata.append(cell);
    }
  }
  // Raw source-record IDs: count in view, list and copy on demand (UR1).
  const sourceIds = Array.isArray(snapshot.lineage?.source_record_ids) ? snapshot.lineage.source_record_ids : [];
  const details = element("details", undefined, "nested-details source-records");
  details.append(element("summary", `Source records (${sourceIds.length})`));
  const copy = element("button", "Copy source record IDs", "ghost-button");
  copy.type = "button";
  copy.disabled = !sourceIds.length;
  const copied = element("span", "", "card-note");
  copied.setAttribute("role", "status");
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(sourceIds.map(stringValue).join("\n"));
      copied.textContent = `Copied ${sourceIds.length} IDs.`;
    } catch {
      copied.textContent = "Copy is not available here; select the IDs below instead.";
    }
  });
  details.append(copy, copied, element("p", sourceIds.length ? sourceIds.map(stringValue).join(" · ") : "No source record IDs were supplied.", "id-list"));
  for (const source of snapshot.lineage?.sources ?? []) {
    const item = element("div", undefined, "source-item");
    item.append(element("strong", stringValue(source.provider_id ?? source.source_record_id ?? "Source record")));
    const fields = [
      "source_record_id",
      "provider_id",
      "provider_version",
      "provider_event_time",
      "retrieval_time",
      "availability_time",
      "raw_schema_version",
      "adapter_version",
      "content_sha256",
      "licensing_reference",
    ];
    for (const key of fields) {
      if (source[key] === undefined || source[key] === null) continue;
      item.append(element("div", `${key}: ${stringValue(source[key])}`));
    }
    details.append(item);
  }
  sources.append(details);
}

function renderPlainReading(snapshot) {
  const target = $("#plain-reading");
  if (!target) return;
  target.replaceChildren();
  const reading = plainReading(snapshot);
  if (!reading.items.length) {
    target.hidden = true;
    return;
  }
  target.hidden = false;
  const row = element("div", undefined, "plain-reading-row");
  row.append(element("strong", "Plain reading", "plain-reading-title"));
  for (const item of reading.items) {
    const chip = element("span", item.text, "reading-chip");
    chip.dataset.tone = item.tone;
    if (item.exact) chip.title = `Exact backend values: ${item.exact}`;
    row.append(chip);
  }
  target.append(row, element("p", reading.note, "card-note"));
}

// Markets list: the five pairs with last price and 24h change from the shared
// stored-snapshot read (UR1); a search box filters the rows.
function renderMarketsList(symbols, selectedId, timeframe, watch, onChoose) {
  const list = $("#markets-list-items");
  if (!list) return;
  const query = ($("#markets-search")?.value ?? "").trim().toUpperCase().replace("/", "");
  list.replaceChildren();
  for (const item of symbols) {
    const entry = watch?.find((candidate) => candidate.symbol === item.symbol);
    const button = element("button", undefined, "market-item");
    button.type = "button";
    button.dataset.instrumentId = item.instrument_id;
    button.setAttribute("aria-pressed", String(item.instrument_id === selectedId));
    const price = entry?.row ? formatDisplayNumber(entry.row.close, displayDecimals(entry.row.close)) : "—";
    const change = entry?.snapshot ? change24h(entry.snapshot) : null;
    button.append(
      element("span", pairLabel(item.symbol), "market-pair"),
      element("span", price, "market-last"),
      element("span", change?.text ?? "—", `market-change${change ? ` change-${change.direction}` : ""}`),
    );
    button.title = entry?.row
      ? `${item.symbol} · ${item.instrument_id} · exact close ${entry.row.close} ${entry.row.priceUnit} (${entry.row.quality})${change ? ` · 24h ${change.exact}` : ""}`
      : `${item.symbol} · ${item.instrument_id}${entry?.error ? ` · ${entry.error}` : ""}`;
    button.addEventListener("click", () => onChoose(item.instrument_id));
    const row = element("li");
    row.hidden = Boolean(query) && !item.symbol.includes(query);
    row.append(button);
    list.append(row);
  }
  $("#markets-list-count").textContent = `${symbols.length} approved Spot pair${symbols.length === 1 ? "" : "s"} · ${timeframeLabel(timeframe)} stored snapshots.`;
}

export async function mountCharts({ desk }) {
  const history = $("#history-select");
  const cutoff = $("#as-of-input");
  const refreshButton = $("#refresh-button");
  const controlError = $("#control-error");
  const workspace = $("#charts-workspace");
  let symbols = [];
  let snapshot = null;
  let requestSequence = 0;
  let markerRequestSequence = 0;
  let refreshInFlight = false;
  let preferences = loadPreferences(localStorage);
  let watch = null;
  const selected = { instrumentId: null, timeframe: null };

  const selectedHistory = () => {
    const limit = Number(history.value);
    return HISTORY_LIMITS.has(limit) ? limit : MAX_CANDLES;
  };
  const updateRefreshAvailability = () => {
    const limit = selectedHistory();
    const timeframeSeconds = TIMEFRAME_SECONDS[selected.timeframe];
    const maxRefreshCandles = timeframeSeconds
      ? Math.min(MAX_CANDLES, Math.floor(MAX_REFRESH_SECONDS / timeframeSeconds))
      : 0;
    const outsideBounds = !refreshRequestWithinBounds(selected.timeframe, limit);
    refreshButton.disabled = refreshInFlight || Boolean(cutoff.value) || outsideBounds ||
      !symbols.some((item) => item.instrument_id === selected.instrumentId);
    $("#refresh-note").textContent = cutoff.value
      ? "Historical cutoffs are read-only. Clear the cutoff before requesting a current explicit refresh."
      : outsideBounds
        ? `The 90-day provider-window policy limits refresh to 2–${maxRefreshCandles} candles for ${selected.timeframe}. Stored historical reads remain available up to 501 candles.`
        : "Refresh is never automatic. This action requests a bounded public Spot update.";
  };

  const resolveChoice = (timeframe) => {
    const options = markerStrategyOptions(timeframe);
    const wanted = options.find((option) => option.value === preferences.strategy);
    const key = wanted?.usable ? wanted.value : null;
    const option = options.find((item) => item.value === key);
    const parsed = parseStrategyKey(key);
    return option && parsed
      ? { key, strategy: parsed.strategy, version: parsed.version, usable: option.usable, reason: option.reason }
      : null;
  };
  const renderMarkerArea = (loaded) => {
    renderMarkerControls(loaded, preferences, selected.timeframe, { onSignals: setSignals, onStrategy: setStrategy });
    renderMarkersPanel(loaded, preferences);
  };
  const renderPreferences = (redraw = true) => {
    $("#beginner-button").setAttribute("aria-pressed", String(preferences.mode === "beginner"));
    $("#pro-button").setAttribute("aria-pressed", String(preferences.mode === "pro"));
    workspace.dataset.mode = preferences.mode;
    renderIndicatorControls(snapshot, preferences, setPreferences, setSignals);
    renderIndicators(snapshot, preferences);
    renderDrawingTools(preferences.mode, redrawChart, clearDrawings);
    markerState.choice = resolveChoice(selected.timeframe);
    renderMarkerArea(snapshot);
    if (snapshot && redraw) renderChart(snapshot, preferences);
  };
  const setPreferences = (next, redraw = true) => {
    preferences = next;
    savePreferences(localStorage, preferences);
    renderPreferences(redraw);
    // Other tabs (the Signal Center) follow the Beginner|Pro choice.
    document.dispatchEvent(new CustomEvent("desk:preferences"));
  };
  const redrawChart = () => { if (snapshot) renderChart(snapshot, preferences); };
  const clearDrawings = () => {
    if (snapshot) saveDrawings(localStorage, drawingsKey(snapshot.instrument_id, snapshot.timeframe), []);
  };

  let markerAsOf;
  const loadMarkers = async (loaded, { asOf } = {}) => {
    const sequence = requestSequence;
    const markerSequence = ++markerRequestSequence;
    markerState.response = null;
    markerState.error = null;
    markerState.selected = 0;
    markerState.choice = resolveChoice(loaded.timeframe);
    if (!preferences.signals) {
      renderMarkerArea(loaded);
      renderIndicatorControls(loaded, preferences, setPreferences, setSignals);
      renderChart(loaded, preferences);
      return;
    }
    const choice = markerState.choice;
    if (!choice?.usable) {
      markerState.error = choice?.reason ?? "No strategy is registered for markers on this timeframe.";
      renderMarkerArea(loaded);
      renderChart(loaded, preferences);
      return;
    }
    renderMarkerArea(loaded);
    try {
      const response = await readStrategyMarkers(globalThis.fetch, {
        instrumentId: loaded.instrument_id,
        timeframe: loaded.timeframe,
        limit: Math.min(MAX_CANDLES, Math.max(2, loaded.candles?.length ?? 2)),
        asOf,
        accountSize: markerState.accountSize,
        riskPct: markerState.riskPct,
        strategy: choice.strategy,
        version: choice.version,
      });
      if (markerSequence !== markerRequestSequence || sequence !== requestSequence || snapshot !== loaded || !preferences.signals || markerState.choice?.key !== choice.key) return;
      let bindingError = markersBindingError(response, loaded);
      if (!bindingError && (response.strategy?.strategy_id !== choice.strategy || String(response.strategy?.version) !== String(choice.version))) {
        bindingError = "Strategy markers do not match the requested strategy and version.";
      }
      markerState.response = bindingError ? null : response;
      markerState.error = bindingError;
    } catch (error) {
      if (markerSequence !== markerRequestSequence || sequence !== requestSequence || snapshot !== loaded || !preferences.signals || markerState.choice?.key !== choice.key) return;
      markerState.error = `Strategy markers could not be loaded: ${error.message} No markers are shown.`;
    }
    renderMarkerArea(loaded);
    renderIndicatorControls(loaded, preferences, setPreferences, setSignals);
    renderChart(loaded, preferences);
  };
  const setSignals = (on) => {
    preferences = { ...preferences, signals: on };
    savePreferences(localStorage, preferences);
    renderPreferences();
    if (on) { setDrawer(true); $("#marker-strategy")?.focus({ preventScroll: true }); }
    if (snapshot) void loadMarkers(snapshot, { asOf: markerAsOf });
  };
  const setStrategy = (key) => {
    if (key !== "" && !parseStrategyKey(key)) return;
    preferences = { ...preferences, strategy: key || null };
    savePreferences(localStorage, preferences);
    if (snapshot) void loadMarkers(snapshot, { asOf: markerAsOf });
  };
  markerState.onSelect = (index) => {
    markerState.selected = index;
    renderMarkersPanel(snapshot, preferences);
    if (snapshot) renderChart(snapshot, preferences);
    setDrawer(true);
    $("#marker-detail")?.scrollIntoView({ block: "nearest" });
  };
  chartHandlers = {
    onPane: (action, id, shownIds) => {
      if (action === "collapse") {
        const collapsed = new Set(preferences.collapsedPanes);
        if (collapsed.has(id)) collapsed.delete(id);
        else collapsed.add(id);
        setPreferences({ ...preferences, collapsedPanes: [...collapsed] });
      } else {
        setPreferences({ ...preferences, paneOrder: movePane(shownIds, preferences.paneOrder, id, action === "up" ? -1 : 1) });
      }
      $(`#chart-container [data-pane-action="${action}"][data-pane="${id}"]`)?.focus();
    },
  };
  $("#sizing-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const parsed = sizingInputs($("#sizing-account").value, $("#sizing-risk").value);
    $("#sizing-error").hidden = parsed.ok;
    if (!parsed.ok) {
      $("#sizing-error").textContent = parsed.error;
      return;
    }
    markerState.accountSize = parsed.accountSize;
    markerState.riskPct = parsed.riskPct;
    if (snapshot) void loadMarkers(snapshot, { asOf: markerAsOf });
  });

  const renderLoaded = (loaded) => {
    setStatus(loaded);
    renderDecisionPanel(loaded);
    renderChart(loaded, preferences);
    renderPlainReading(loaded);
    renderCandles(loaded);
    renderMetadata(loaded);
    renderIndicatorControls(loaded, preferences, setPreferences, setSignals);
    renderIndicators(loaded, preferences);
    renderOrderFlow(loaded);
    renderSpotAnalyses(loaded);
  };

  const showFailure = (error, sequence) => {
    if (sequence !== requestSequence) return;
    snapshot = null;
    setStatus(null, error.message);
    renderDecisionPanel(null);
    markerState.response = null;
    markerState.error = null;
    renderMarkerArea(null);
    $("#chart-container").replaceChildren(element("p", error.message, "empty-state"));
    renderPlainReading(null);
    renderCandles(null);
    renderMetadata(null);
    renderIndicatorControls(null, preferences, setPreferences, setSignals);
    renderIndicators(null, preferences);
    renderOrderFlow(null);
    renderSpotAnalyses(null);
  };

  const loadSnapshot = async () => {
    const sequence = ++requestSequence;
    ++markerRequestSequence;
    controlError.hidden = true;
    snapshot = null;
    updateRefreshAvailability();
    markerState.response = null;
    markerState.error = null;
    renderMarkerArea(null);
    renderDecisionPanel(null);
    const statusPanel = $("#snapshot-status");
    statusPanel.dataset.state = "warning";
    statusPanel.replaceChildren(
      element("strong", `Loading ${selected.instrumentId} · ${selected.timeframe}.`),
      element("span", "Previous snapshot cleared; this read cannot trigger provider collection.", "status-detail"),
    );
    $("#chart-container").replaceChildren(element("p", "Loading exact API candle data…", "empty-state"));
    renderPlainReading(null);
    renderCandles(null);
    renderMetadata(null);
    renderIndicatorControls(null, preferences, setPreferences, setSignals);
    $("#indicator-groups").replaceChildren(element("p", "Loading backend indicator results…", "empty-state"));
    renderOrderFlow(null);
    renderSpotAnalyses(null);
    const instrumentId = selected.instrumentId;
    const selectedTimeframe = selected.timeframe;
    const limit = selectedHistory();
    if (!symbols.some((item) => item.instrument_id === instrumentId)) {
      showFailure(new Error("Select an instrument returned by the local API allowlist."), sequence);
      return;
    }
    const selectedSymbol = symbols.find((item) => item.instrument_id === instrumentId).symbol;
    if (!TIMEFRAMES.includes(selectedTimeframe)) {
      showFailure(new Error("This timeframe is not supported by the local research API."), sequence);
      return;
    }
    let asOf;
    if (cutoff.value) {
      const instant = new Date(cutoff.value);
      if (!Number.isFinite(instant.valueOf())) {
        controlError.textContent = "Enter a valid historical cutoff.";
        controlError.hidden = false;
        return;
      }
      asOf = instant.toISOString();
    }
    updateRefreshAvailability();
    try {
      // The default current read (501 candles) is shared with Today, the
      // header and the markets list; other bounds and cutoffs read directly.
      let response = null;
      if (limit === MAX_CANDLES && !asOf) {
        const cached = await desk.entry({ instrument_id: instrumentId, symbol: selectedSymbol }, selectedTimeframe);
        if (sequence !== requestSequence) return;
        response = cached.snapshot;
      }
      response ??= await readSnapshot(globalThis.fetch, {
        instrumentId, timeframe: selectedTimeframe, limit, asOf,
      });
      if (sequence !== requestSequence) return;
      const validationError = validateSnapshot(response, {
        instrumentId,
        symbol: selectedSymbol,
        timeframe: selectedTimeframe,
        requestedAsOf: asOf,
      });
      if (validationError) throw new Error(validationError);
      snapshot = response;
      markerState.response = null;
      renderLoaded(snapshot);
      markerAsOf = asOf;
      void loadMarkers(snapshot, { asOf });
    } catch (error) {
      showFailure(error, sequence);
    }
  };

  const syncSelectionLists = () => {
    for (const button of document.querySelectorAll("#markets-list-items [data-instrument-id]")) {
      button.setAttribute("aria-pressed", String(button.dataset.instrumentId === selected.instrumentId));
    }
    for (const button of document.querySelectorAll("#timeframe-pills [data-timeframe]")) {
      button.setAttribute("aria-pressed", String(button.dataset.timeframe === selected.timeframe));
    }
    const symbol = symbols.find((item) => item.instrument_id === selected.instrumentId)?.symbol;
    $("#chart-heading").textContent = symbol ? pairLabel(symbol) : "Chart";
    refreshChartMenus();
  };
  const loadMarketPrices = async () => {
    const timeframe = selected.timeframe;
    renderMarketsList(symbols, selected.instrumentId, timeframe, watch, (value) => desk.select({ instrumentId: value }));
    try {
      const results = await desk.watchlist(timeframe);
      if (timeframe !== selected.timeframe) return;
      watch = results;
    } catch {
      watch = null;
    }
    renderMarketsList(symbols, selected.instrumentId, timeframe, watch, (value) => desk.select({ instrumentId: value }));
  };

  const loadSymbols = async () => {
    document.querySelector(".retry-symbols")?.remove();
    $("#snapshot-status").dataset.state = "warning";
    $("#snapshot-status").replaceChildren(element("strong", "Loading supported instruments."), element("span", "Read-only local symbol-list request.", "status-detail"));
    try {
      const response = await desk.symbolsResponse();
      if (response?.provider !== "binance-spot-public" || response?.redistribution !== "NOT_AUTHORIZED") {
        throw new Error("The API did not return the approved local Spot symbol contract.");
      }
      symbols = Array.isArray(response?.instruments) ? response.instruments.filter((item) =>
        typeof item?.instrument_id === "string" && typeof item?.symbol === "string" &&
        item?.venue_id === "BINANCE-SPOT" && item?.eligibility === "CHECKED_ON_EACH_REFRESH",
      ) : [];
      if (!symbols.length) throw new Error("The API returned no supported instruments.");
      const selection = await desk.selection();
      selected.instrumentId = symbols.some((item) => item.instrument_id === selection.instrumentId)
        ? selection.instrumentId : symbols[0].instrument_id;
      selected.timeframe = TIMEFRAMES.includes(selection.timeframe) ? selection.timeframe : TIMEFRAMES[0];
      syncSelectionLists();
      updateRefreshAvailability();
      renderPreferences();
      const loading = loadSnapshot();
      void loadMarketPrices();
      await loading;
    } catch {
      setStatus(null, "The supported-instrument list could not be loaded from the local research API.");
      const retry = element("button", "Retry supported-symbol read", "retry-symbols");
      retry.type = "button";
      retry.addEventListener("click", loadSymbols);
      $("#chart-container").replaceChildren(element("p", "Supported instruments could not be read; no chart values are shown.", "empty-state"), retry);
    }
  };

  // Shared coin/timeframe (UR3): every tab and reload agrees.
  desk.onChange((selection, change) => {
    if (change.invalidated) {
      void loadMarketPrices();
      return;
    }
    if (!symbols.length) return;
    const timeframeChanged = selection.timeframe !== selected.timeframe;
    const changed = timeframeChanged || selection.instrumentId !== selected.instrumentId;
    if (!changed) return;
    selected.instrumentId = selection.instrumentId;
    selected.timeframe = selection.timeframe;
    syncSelectionLists();
    snapshot = null;
    void loadSnapshot();
    if (timeframeChanged) {
      watch = null;
      void loadMarketPrices();
    }
  });

  // Layout controls: markets list, details drawer, full screen.
  const setDrawer = (open) => {
    workspace.dataset.drawer = open ? "open" : "closed";
    const toggle = $("#drawer-toggle");
    toggle.setAttribute("aria-expanded", String(open));
    toggle.textContent = open ? "Hide details ▸" : "◂ Show details";
  };
  $("#drawer-toggle").addEventListener("click", () => {
    setDrawer(workspace.dataset.drawer !== "open");
    redrawChart();
  });
  $("#markets-toggle").addEventListener("click", () => {
    const open = workspace.dataset.markets !== "open";
    workspace.dataset.markets = open ? "open" : "closed";
    $("#markets-toggle").setAttribute("aria-expanded", String(open));
    $("#markets-toggle").textContent = open ? "◂ Markets" : "▸ Markets";
    redrawChart();
  });
  $("#markets-search").addEventListener("input", () => {
    renderMarketsList(symbols, selected.instrumentId, selected.timeframe, watch, (value) => desk.select({ instrumentId: value }));
  });
  let drawerBeforeFullscreen = "open";
  const applyFullscreen = (on) => {
    if (layoutState.fullscreen === on) return;
    layoutState.fullscreen = on;
    workspace.classList.toggle("is-fullscreen", on);
    document.body.classList.toggle("chart-fullscreen", on);
    const button = $("#fullscreen-button");
    button.setAttribute("aria-pressed", String(on));
    button.textContent = on ? "✕ Exit full screen" : "⛶ Full screen";
    if (on) {
      drawerBeforeFullscreen = workspace.dataset.drawer;
      setDrawer(false);
    } else {
      setDrawer(drawerBeforeFullscreen === "open");
    }
    redrawChart();
  };
  $("#fullscreen-button").addEventListener("click", async () => {
    if (layoutState.fullscreen) {
      if (document.fullscreenElement) await document.exitFullscreen().catch(() => {});
      applyFullscreen(false);
      return;
    }
    applyFullscreen(true);
    try {
      if (workspace.requestFullscreen) await workspace.requestFullscreen();
    } catch {
      // The fixed-overlay fallback (.is-fullscreen) stays in place.
    }
  });
  document.addEventListener("fullscreenchange", () => {
    if (!document.fullscreenElement && layoutState.fullscreen) applyFullscreen(false);
    else redrawChart();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !layoutState.fullscreen) return;
    if (document.fullscreenElement) void document.exitFullscreen().catch(() => {});
    applyFullscreen(false);
    $("#fullscreen-button").focus({ preventScroll: true });
  });
  if (typeof ResizeObserver === "function") {
    new ResizeObserver(() => {
      const width = Math.round($("#chart-container").clientWidth);
      if (snapshot && width > 0 && Math.abs(width - chartView.width) > 2) renderChart(snapshot, preferences);
    }).observe($("#chart-container"));
  }

  // Provenance links open the drawer section they point to.
  document.addEventListener("click", (event) => {
    if (!event.target.closest?.("a[href=\"#snapshot-provenance\"]")) return;
    setDrawer(true);
    const section = $("#snapshot-provenance");
    section.open = true;
    section.querySelector(".nested-details").open = true;
  });
  refreshChartMenus = mountChartToolbar({ document,
    state: () => ({ snapshot, preferences, selected, symbols }),
    update: setPreferences, select: (choice) => desk.select(choice), signals: setSignals,
    availability: (kind, id) => kind === "analysis" ? analysisAvailability(snapshot, id) : indicatorAvailability(snapshot, id),
  });
  history.addEventListener("change", () => { void loadSnapshot(); });
  cutoff.addEventListener("change", () => { void loadSnapshot(); });
  $("#beginner-button").addEventListener("click", () => setPreferences({ ...preferences, mode: "beginner" }));
  $("#pro-button").addEventListener("click", () => setPreferences({ ...preferences, mode: "pro" }));
  refreshButton.addEventListener("click", async () => {
    if (refreshInFlight || !selected.instrumentId || cutoff.value) return;
    const selectedInstrument = symbols.find((item) => item.instrument_id === selected.instrumentId);
    if (!selectedInstrument) return;
    const sequence = ++requestSequence;
    const instrumentId = selected.instrumentId;
    const symbol = selectedInstrument.symbol;
    const selectedTimeframe = selected.timeframe;
    refreshInFlight = true;
    updateRefreshAvailability();
    refreshButton.disabled = true;
    refreshButton.textContent = "Bounded refresh in progress…";
    controlError.hidden = true;
    try {
      const response = await refreshSnapshot(globalThis.fetch, {
        instrumentId,
        timeframe: selectedTimeframe,
        limit: selectedHistory(),
      });
      if (sequence !== requestSequence) return;
      const validationError = validateSnapshot(response, { instrumentId, symbol, timeframe: selectedTimeframe });
      if (validationError) throw new Error(validationError);
      snapshot = response;
      markerState.response = null;
      renderLoaded(snapshot);
      markerAsOf = undefined;
      void loadMarkers(snapshot);
      desk.seed(selectedInstrument, selectedTimeframe, response);
    } catch (error) {
      showFailure(error, sequence);
    } finally {
      refreshInFlight = false;
      refreshButton.textContent = "Explicitly refresh from provider";
      updateRefreshAvailability();
    }
  });
  renderPreferences();
  await loadSymbols();
}
