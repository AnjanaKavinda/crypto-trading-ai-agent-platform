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
  spotAnalysisBindingError,
  SPOT_ANALYSIS_IDS,
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
const SPOT_ANALYSIS_LABELS = Object.freeze({
  vwap: "Spot VWAP",
  "volume-profile": "Volume profile",
  "volume-confirmation": "Volume confirmation",
  "price-action-support-resistance": "Price-action candle geometry",
  "spot-market-structure": "Spot market structure",
});
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
    const indicator = snapshot?.indicators?.[id];
    const bindingError = supplied ? indicatorBindingError(snapshot, id, indicator) : null;
    const available = supplied && indicator?.status === "AVAILABLE" && !bindingError;
    const unavailableReason = !supplied
      ? "not supplied in response"
      : indicator?.status === "UNAVAILABLE" && indicator?.reason_code
        ? indicator.reason_code
        : bindingError ?? indicator?.reason_code ?? indicator?.status ?? "unavailable";
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
  const vwapAnalysis = snapshot.spot_analysis?.vwap;
  const vwapBindingError = spotAnalysisBindingError(snapshot, "vwap", vwapAnalysis);
  const vwapPoints = snapshot.data_quality?.status === "VALID" &&
      snapshot.data_quality?.report_status === "VALID" &&
      ["AVAILABLE", "PARTIAL"].includes(vwapAnalysis?.status) &&
      !vwapBindingError && Array.isArray(vwapAnalysis.result?.points)
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
  const width = 1000;
  const left = 70;
  const right = 20;
  const plotWidth = width - left - right;
  const priceTop = 20;
  const priceHeight = 260;
  const panelsTop = 320;
  const panelHeight = 95;
  const panelGap = 25;
  const volumeHeight = 55;
  const volumeMax = Math.max(...candles.map((item) => item.values.volume.numeric));
  const lows = candles.map(({ values }) => values.low.numeric);
  const highs = candles.map(({ values }) => values.high.numeric);
  const enabled = preferences.mode === "beginner" ? DEFAULT_VISIBILITY : preferences.visible;
  const emaSeries = [];
  const bands = [];
  const panelDefinitions = [
    ["atr-14", "ATR", [["atr-line", "value"]]],
    ["realized-volatility-20", "REALIZED VOL", [["realized-volatility-line", "value"]]],
    ["rsi-14", "RSI", [["rsi-line", "value"]]],
    ["macd-12-26-9", "MACD", [["macd-line", "line"], ["macd-signal", "signal"], ["macd-histogram", "histogram"]]],
    ["stochastic-14-3", "STOCHASTIC", [["stochastic-k", "k"], ["stochastic-d", "d"]]],
    ["cci-20", "CCI", [["cci-line", "value"]]],
  ];
  const separatePanels = [];
  for (const id of enabled) {
    const result = snapshot.indicators?.[id]?.result;
    if (snapshot.indicators?.[id]?.status !== "AVAILABLE" ||
        indicatorBindingError(snapshot, id, snapshot.indicators?.[id]) ||
        !result) continue;
    if (id === "ema-20" || id === "ema-50" || id === "ema-500") {
      emaSeries.push([id, plotValues(result)]);
    } else if (id === "bollinger-bands-20") {
      bands.push(...["upper", "middle", "lower"].map((field) => [field, plotValues(result, field)]));
    }
  }
  for (const [id, label, fields] of panelDefinitions) {
    const indicator = snapshot.indicators?.[id];
    if (!enabled.includes(id) || indicator?.status !== "AVAILABLE" ||
        indicatorBindingError(snapshot, id, indicator) || !indicator.result) continue;
    const series = fields.map(([className, field]) => [className, plotValues(indicator.result, field)])
      .filter(([, points]) => points.length > 1);
    if (series.length) separatePanels.push({ label, series });
  }
  const volumeTop = panelsTop + separatePanels.length * (panelHeight + panelGap) + 5;
  const height = volumeTop + volumeHeight + 20;
  const visiblePriceValues = [...lows, ...highs];
  for (const point of vwapPoints) {
    const number = numberForPlot(point.value);
    if (number !== null) visiblePriceValues.push(number);
  }
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
  svgText(svg, 8, volumeTop - 6, "VOLUME");
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
  const vwapLine = makeLine(vwapPoints, candleIndexes, priceMin, priceMax, priceTop, priceHeight, left, plotWidth);
  if (vwapLine) {
    svg.append(svgNode("polyline", { points: vwapLine, class: "indicator-line spot-vwap-line" }));
    svgText(svg, left + 4 * 130, 18, "Spot VWAP", "legend-text");
  }
  for (const [panelIndex, panel] of separatePanels.entries()) {
    const top = panelsTop + panelIndex * (panelHeight + panelGap);
    const numbers = panel.series.flatMap(([, points]) =>
      points.map((point) => numberForPlot(point.value)),
    ).filter((value) => value !== null);
    if (!numbers.length) continue;
    let min = Math.min(...numbers);
    let max = Math.max(...numbers);
    if (min >= 0) min = 0;
    if (max <= 0) max = 0;
    if (min === max) max = min + Math.max(Math.abs(min) * 0.02, 1);
    svgText(svg, 8, top - 6, panel.label);
    panel.series.forEach(([className, points], seriesIndex) => {
      const polyline = makeLine(points, candleIndexes, min, max, top, panelHeight, left, plotWidth);
      if (polyline) svg.append(svgNode("polyline", { points: polyline, class: `indicator-line ${className}` }));
      svgText(svg, left + seriesIndex * 150, top - 6, className.replaceAll("-", " "), "legend-text");
    });
  }
  for (const [index, [id]] of [...emaSeries, ...bands].entries()) {
    svgText(svg, left + index * 130, 18, id === "upper" || id === "middle" || id === "lower" ? `Bollinger ${id}` : id, "legend-text");
  }
  svgText(svg, 160, volumeTop - 6, "Volume · backend values", "legend-text");
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
        ? `The 90-day provider-window policy limits refresh to 2–${maxRefreshCandles} candles for ${timeframe.value}. Stored historical reads remain available up to 501 candles.`
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
    renderSpotAnalyses(null);
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
    renderSpotAnalyses(null);
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
      renderSpotAnalyses(snapshot);
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
  $("#beginner-button").addEventListener("click", () => setPreferences({ ...preferences, mode: "beginner" }));
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
      renderSpotAnalyses(snapshot);
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
