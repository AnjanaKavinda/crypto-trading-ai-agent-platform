import {
  listSupportedSymbols,
  readSnapshot,
  refreshSnapshot,
  MAX_CANDLES,
  MAX_REFRESH_SECONDS,
  refreshRequestWithinBounds,
  TIMEFRAME_SECONDS,
} from "./research-api.mjs";
import {
  DEFAULT_VISIBILITY,
  INDICATOR_IDS,
  indicatorBindingError,
  latestIndicatorValues,
  loadPreferences,
  plotValues,
  savePreferences,
  snapshotCandles,
  snapshotLabels,
  validateSnapshot,
  workspaceSelection,
} from "./workspace-state.mjs";

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

const TIMEFRAMES = Object.keys(TIMEFRAME_SECONDS);
const HISTORY_LIMITS = new Set([50, 90, 100, 250, 501]);
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

function setStatus(snapshot, errorMessage) {
  const panel = $("#snapshot-status");
  panel.replaceChildren();
  if (errorMessage) {
    panel.dataset.state = "error";
    panel.append(element("strong", "Research request failed."));
    panel.append(element("span", errorMessage));
    return;
  }
  const labels = snapshotLabels(snapshot);
  panel.dataset.state = labels.severity;
  const quality = element("strong", `${labels.quality} · ${labels.temporal}`);
  panel.append(quality);
  if (snapshot.temporal_context === "HISTORICAL") {
    panel.append(element("span", "This point-in-time research response is historical and is never represented as current."));
  } else if (labels.quality === "VALID") {
    panel.append(element("span", "Quality is reported VALID for this exact snapshot; this does not establish trading readiness or execution authority."));
  } else {
    panel.append(element("span", `The API reports ${labels.quality}; this is not promoted to valid or current evidence.`));
  }
  if (snapshot.data_quality?.report_status && snapshot.data_quality.report_status !== labels.quality) {
    panel.append(element("span", `Underlying report status: ${snapshot.data_quality.report_status}.`));
  }
}

function renderIndicatorControls(snapshot, preferences, updatePreferences) {
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
    const supplied = Object.hasOwn(snapshot?.indicators ?? {}, id);
    const toggle = element("label", undefined, `indicator-toggle${supplied ? "" : " unavailable"}`);
    toggle.hidden = !queryMatches(id);
    const checkbox = element("input");
    checkbox.type = "checkbox";
    checkbox.checked = preferences.visible.includes(id);
    checkbox.disabled = !supplied;
    checkbox.setAttribute("aria-label", `${descriptor.title}${supplied ? "" : ", unavailable because no result was returned by the API"}`);
    checkbox.addEventListener("change", () => {
      const visible = new Set(preferences.visible);
      if (checkbox.checked) visible.add(id);
      else visible.delete(id);
      updatePreferences({ ...preferences, visible: [...visible] });
    });
    toggle.append(checkbox, element("span", supplied ? descriptor.title : `${descriptor.title} — unavailable (not supplied in response)`));
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
  else if (indicator?.reason_code) card.append(element("p", `Backend reason: ${indicator.reason_code}`));
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
  container.append(card);
}

function renderIndicators(snapshot, preferences) {
  const groups = $("#indicator-groups");
  groups.replaceChildren();
  const visible = preferences.mode === "beginner"
    ? DEFAULT_VISIBILITY
    : preferences.visible;
  const grouped = new Map();
  for (const id of visible) {
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

function svgText(svg, x, y, text, className = "axis-label") {
  const node = svgNode("text", { x, y, class: className });
  node.textContent = text;
  svg.append(node);
}

function numberForPlot(exact) {
  const value = Number(exact);
  return Number.isFinite(value) ? value : null;
}

function makeLine(values, candleIndexes, min, max, top, height, left, width) {
  const positions = [];
  const span = max === min ? Math.max(Math.abs(max) * 0.02, 1) : max - min;
  for (const item of values) {
    const index = candleIndexes.get(Date.parse(item.candleEnd));
    const value = numberForPlot(item.value);
    if (index === undefined || value === null) continue;
    const x = left + (candleIndexes.size <= 1 ? width / 2 : index * width / (candleIndexes.size - 1));
    const y = top + height - ((value - min) / span) * height;
    positions.push(`${x},${y}`);
  }
  return positions.length > 1 ? positions.join(" ") : "";
}

function renderChart(snapshot, preferences) {
  const target = $("#chart-container");
  target.replaceChildren();
  const response = snapshotCandles(snapshot);
  if (response.error) {
    target.append(element("p", response.error, "empty-state"));
    return;
  }
  const candles = response.candles;
  const width = 1000;
  const height = 520;
  const left = 70;
  const right = 20;
  const plotWidth = width - left - right;
  const priceTop = 20;
  const priceHeight = 260;
  const atrTop = 320;
  const atrHeight = 95;
  const volumeTop = 445;
  const volumeHeight = 55;
  const volumeMax = Math.max(...candles.map((item) => item.values.volume.numeric));
  const closes = candles.map(({ values }) => values.close.numeric);
  const lows = candles.map(({ values }) => values.low.numeric);
  const highs = candles.map(({ values }) => values.high.numeric);
  const enabled = preferences.mode === "beginner" ? DEFAULT_VISIBILITY : preferences.visible;
  const emaSeries = [];
  const bands = [];
  const atrSeries = [];
  for (const id of enabled) {
    const result = snapshot.indicators?.[id]?.result;
    if (snapshot.indicators?.[id]?.status !== "AVAILABLE" ||
        indicatorBindingError(snapshot, id, snapshot.indicators?.[id]) ||
        !result) continue;
    if (id === "ema-20" || id === "ema-50") {
      emaSeries.push([id, plotValues(result)]);
    } else if (id === "bollinger-bands-20") {
      bands.push(...["upper", "middle", "lower"].map((field) => [field, plotValues(result, field)]));
    } else if (id === "atr-14") {
      atrSeries.push(...plotValues(result));
    }
  }
  const visiblePriceValues = [...lows, ...highs];
  for (const [, points] of emaSeries) for (const point of points) {
    const number = numberForPlot(point.value);
    if (number !== null) visiblePriceValues.push(number);
  }
  for (const [, points] of bands) for (const point of points) {
    const number = numberForPlot(point.value);
    if (number !== null) visiblePriceValues.push(number);
  }
  let priceMin = Math.min(...visiblePriceValues);
  let priceMax = Math.max(...visiblePriceValues);
  const padding = priceMax === priceMin ? Math.max(Math.abs(priceMax) * 0.02, 1) : (priceMax - priceMin) * 0.06;
  priceMin -= padding;
  priceMax += padding;
  const candleIndexes = new Map(candles.map(({ source }, index) => [Date.parse(source.close_time), index]));
  const svg = svgNode("svg", {
    viewBox: `0 0 ${width} ${height}`,
    role: "img",
    "aria-labelledby": "chart-svg-title chart-svg-desc",
    focusable: "false",
  });
  const title = svgNode("title", { id: "chart-svg-title" });
  title.textContent = `${snapshot.symbol} ${snapshot.timeframe} exact API candles, volume${snapshot.data_quality?.status === "STALE" ? ", stale" : ""}`;
  svg.append(title);
  const description = svgNode("desc", { id: "chart-svg-desc" });
  description.textContent = `${candles.length} returned finalized candles. Chart scales are visual only; exact returned values are available in the table below.`;
  svg.append(description);
  for (let i = 0; i <= 4; i += 1) {
    const y = priceTop + i * priceHeight / 4;
    svg.append(svgNode("line", { x1: left, x2: width - right, y1: y, y2: y, class: "gridline" }));
  }
  svgText(svg, 8, 16, "PRICE");
  svgText(svg, 8, 309, "ATR");
  svgText(svg, 8, 439, "VOLUME");
  const priceSpan = priceMax - priceMin;
  const candleWidth = Math.max(1, Math.min(8, plotWidth / candles.length * 0.62));
  candles.forEach(({ source, values }, index) => {
    const x = left + (candles.length <= 1 ? plotWidth / 2 : index * plotWidth / (candles.length - 1));
    const y = (value) => priceTop + priceHeight - ((value - priceMin) / priceSpan) * priceHeight;
    const up = values.close.numeric >= values.open.numeric;
    svg.append(svgNode("line", {
      x1: x, x2: x, y1: y(values.high.numeric), y2: y(values.low.numeric),
      class: `candle-wick candle-${up ? "up" : "down"}`,
    }));
    svg.append(svgNode("rect", {
      x: x - candleWidth / 2,
      y: Math.min(y(values.open.numeric), y(values.close.numeric)),
      width: candleWidth,
      height: Math.max(1, Math.abs(y(values.open.numeric) - y(values.close.numeric))),
      class: `candle-body candle-${up ? "up" : "down"}`,
    }));
    const volumeBarHeight = volumeMax > 0 ? (values.volume.numeric / volumeMax) * volumeHeight : 0;
    svg.append(svgNode("rect", {
      x: x - candleWidth / 2,
      y: volumeTop + volumeHeight - volumeBarHeight,
      width: candleWidth,
      height: volumeBarHeight,
      class: "volume-bar",
    }));
    if (index === 0 || index === candles.length - 1 || index === Math.floor(candles.length / 2)) {
      svgText(svg, x - 34, height - 4, isoText(source.open_time).split(" · ")[0], "axis-label");
    }
  });
  for (const [id, points] of [...emaSeries, ...bands]) {
    const polyline = makeLine(points, candleIndexes, priceMin, priceMax, priceTop, priceHeight, left, plotWidth);
    const lineClass = ["upper", "middle", "lower"].includes(id) ? `bollinger-${id}` : id;
    if (polyline) svg.append(svgNode("polyline", { points: polyline, class: `indicator-line ${lineClass}` }));
  }
  if (atrSeries.length) {
    const numbers = atrSeries.map((point) => numberForPlot(point.value)).filter((value) => value !== null);
    if (numbers.length) {
      const max = Math.max(...numbers);
      const atrMax = max === 0 ? 1 : max;
      const polyline = makeLine(atrSeries, candleIndexes, 0, atrMax, atrTop, atrHeight, left, plotWidth);
      if (polyline) svg.append(svgNode("polyline", { points: polyline, class: "indicator-line atr-line" }));
    }
  }
  for (const [index, [id]] of [...emaSeries, ...bands].entries()) {
    svgText(svg, left + index * 130, 18, id === "upper" || id === "middle" || id === "lower" ? `Bollinger ${id}` : id, "legend-text");
  }
  if (atrSeries.length) svgText(svg, 160, 309, "ATR 14 · backend values", "legend-text");
  svgText(svg, 160, 439, "Volume · backend values", "legend-text");
  target.append(svg);
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
    metadata.firstChild.append(element("dt", "Instrument / venue"), element("dd", "Not yet available"));
    return;
  }
  const entries = [
    ["Exact instrument / symbol", `${stringValue(snapshot.instrument_id)} · ${stringValue(snapshot.symbol)}`],
    ["Venue", snapshot.venue_id],
    ["Timeframe", snapshot.timeframe],
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
  const sourceIds = Array.isArray(snapshot.lineage?.source_record_ids) ? snapshot.lineage.source_record_ids : [];
  sources.append(element("h3", `Source records (${sourceIds.length})`));
  sources.append(element("p", sourceIds.length ? sourceIds.map(stringValue).join(" · ") : "No source record IDs were supplied."));
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
    sources.append(item);
  }
}

async function bootstrap() {
  const instrument = $("#instrument-select");
  const timeframe = $("#timeframe-select");
  const history = $("#history-select");
  const cutoff = $("#as-of-input");
  const refreshButton = $("#refresh-button");
  const controlError = $("#control-error");
  let symbols = [];
  let snapshot = null;
  let requestSequence = 0;
  let refreshInFlight = false;
  let preferences = { mode: "beginner", visible: [...DEFAULT_VISIBILITY] };

  const selectedHistory = () => {
    const limit = Number(history.value);
    return HISTORY_LIMITS.has(limit) ? limit : 250;
  };
  const updateRefreshAvailability = () => {
    const limit = selectedHistory();
    const timeframeSeconds = TIMEFRAME_SECONDS[timeframe.value];
    const maxRefreshCandles = timeframeSeconds
      ? Math.min(MAX_CANDLES, Math.floor(MAX_REFRESH_SECONDS / timeframeSeconds))
      : 0;
    const outsideBounds = !refreshRequestWithinBounds(timeframe.value, limit);
    refreshButton.disabled = refreshInFlight || Boolean(cutoff.value) || outsideBounds ||
      !symbols.some((item) => item.instrument_id === instrument.value);
    $("#refresh-note").textContent = cutoff.value
      ? "Historical cutoffs are read-only. Clear the cutoff before requesting a current explicit refresh."
      : outsideBounds
        ? `Refresh allows 2–${maxRefreshCandles} candles for ${timeframe.value}; reads may use up to 501.`
        : "Refresh is never automatic. This action requests a bounded public Spot update.";
  };
  const renderPreferences = () => {
    $("#view-mode").textContent = preferences.mode === "pro" ? "Pro view" : "Beginner view";
    $("#beginner-button").setAttribute("aria-pressed", String(preferences.mode === "beginner"));
    $("#pro-button").setAttribute("aria-pressed", String(preferences.mode === "pro"));
    renderIndicatorControls(snapshot, preferences, setPreferences);
    renderIndicators(snapshot, preferences);
    if (snapshot) renderChart(snapshot, preferences);
  };
  const setPreferences = (next) => {
    preferences = next;
    savePreferences(localStorage, instrument.value, timeframe.value, preferences);
    renderPreferences();
  };
  const loadSelectedPreferences = () => {
    preferences = loadPreferences(localStorage, instrument.value, timeframe.value);
    renderPreferences();
  };

  const showFailure = (error, sequence) => {
    if (sequence !== requestSequence) return;
    snapshot = null;
    setStatus(null, error.message);
    $("#chart-container").replaceChildren(element("p", error.message, "empty-state"));
    renderCandles(null);
    renderMetadata(null);
    renderIndicatorControls(null, preferences, setPreferences);
    renderIndicators(null, preferences);
    renderOrderFlow(null);
  };

  const loadSnapshot = async () => {
    const sequence = ++requestSequence;
    controlError.hidden = true;
    snapshot = null;
    updateRefreshAvailability();
    const statusPanel = $("#snapshot-status");
    statusPanel.dataset.state = "warning";
    statusPanel.replaceChildren(
      element("strong", `Loading ${instrument.value} · ${timeframe.value}.`),
      element("span", "Previous snapshot cleared; this read cannot trigger provider collection."),
    );
    $("#chart-container").replaceChildren(element("p", "Loading exact API candle data…", "empty-state"));
    renderCandles(null);
    renderMetadata(null);
    renderIndicatorControls(null, preferences, setPreferences);
    $("#indicator-groups").replaceChildren(element("p", "Loading backend indicator results…", "empty-state"));
    renderOrderFlow(null);
    const instrumentId = instrument.value;
    const selectedTimeframe = timeframe.value;
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
      const response = await readSnapshot(globalThis.fetch, {
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
      setStatus(snapshot);
      renderChart(snapshot, preferences);
      renderCandles(snapshot);
      renderMetadata(snapshot);
      renderIndicatorControls(snapshot, preferences, setPreferences);
      renderIndicators(snapshot, preferences);
      renderOrderFlow(snapshot);
    } catch (error) {
      showFailure(error, sequence);
    }
  };

  const loadSymbols = async () => {
    document.querySelector(".retry-symbols")?.remove();
    $("#snapshot-status").dataset.state = "warning";
    $("#snapshot-status").replaceChildren(element("strong", "Loading supported instruments."), element("span", "Read-only local symbol-list request."));
    try {
      const response = await listSupportedSymbols(globalThis.fetch);
      if (response?.provider !== "binance-spot-public" || response?.redistribution !== "NOT_AUTHORIZED") {
        throw new Error("The API did not return the approved local Spot symbol contract.");
      }
      symbols = Array.isArray(response?.instruments) ? response.instruments.filter((item) =>
        typeof item?.instrument_id === "string" && typeof item?.symbol === "string" &&
        item?.venue_id === "BINANCE-SPOT" && item?.eligibility === "CHECKED_ON_EACH_REFRESH",
      ) : [];
      if (!symbols.length) throw new Error("The API returned no supported instruments.");
      instrument.replaceChildren();
      for (const item of symbols) {
        const option = element("option", `${item.symbol} · ${item.instrument_id}`);
        option.value = item.instrument_id;
        instrument.append(option);
      }
      instrument.disabled = false;
      const selection = workspaceSelection(window.location.search, symbols, TIMEFRAMES);
      instrument.value = selection.instrumentId;
      timeframe.value = selection.timeframe;
      updateRefreshAvailability();
      loadSelectedPreferences();
      await loadSnapshot();
    } catch {
      setStatus(null, "The supported-instrument list could not be loaded from the local research API.");
      $("#instrument-note").textContent = "Retry the safe read-only symbol-list request; no provider refresh has occurred.";
      const retry = element("button", "Retry supported-symbol read", "retry-symbols");
      retry.type = "button";
      retry.addEventListener("click", loadSymbols);
      $("#instrument-note").append(retry);
    }
  };

  instrument.addEventListener("change", () => { snapshot = null; loadSelectedPreferences(); void loadSnapshot(); });
  timeframe.addEventListener("change", () => { snapshot = null; loadSelectedPreferences(); void loadSnapshot(); });
  history.addEventListener("change", () => { void loadSnapshot(); });
  cutoff.addEventListener("change", () => { void loadSnapshot(); });
  $("#beginner-button").addEventListener("click", () => setPreferences({ mode: "beginner", visible: [...DEFAULT_VISIBILITY] }));
  $("#pro-button").addEventListener("click", () => setPreferences({ ...preferences, mode: "pro" }));
  $("#reset-button").addEventListener("click", () => setPreferences({ mode: "beginner", visible: [...DEFAULT_VISIBILITY] }));
  refreshButton.addEventListener("click", async () => {
    if (refreshInFlight || !instrument.value || cutoff.value) return;
    const selectedInstrument = symbols.find((item) => item.instrument_id === instrument.value);
    if (!selectedInstrument) return;
    const sequence = ++requestSequence;
    const instrumentId = instrument.value;
    const symbol = selectedInstrument.symbol;
    const selectedTimeframe = timeframe.value;
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
      setStatus(snapshot);
      renderChart(snapshot, preferences);
      renderCandles(snapshot);
      renderMetadata(snapshot);
      renderIndicatorControls(snapshot, preferences, setPreferences);
      renderIndicators(snapshot, preferences);
      renderOrderFlow(snapshot);
    } catch (error) {
      showFailure(error, sequence);
    } finally {
      refreshInFlight = false;
      refreshButton.textContent = "Explicitly refresh from provider";
      updateRefreshAvailability();
    }
  });
  await loadSymbols();
}

if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", () => { void bootstrap(); }, { once: true });
}
