export function chartIndexAtPointer({
  clientX,
  boundsLeft,
  boundsWidth,
  viewWidth,
  plotLeft,
  plotWidth,
  candleCount,
}) {
  if (
    !Number.isFinite(clientX) ||
    !Number.isFinite(boundsLeft) ||
    !Number.isFinite(boundsWidth) ||
    !Number.isFinite(viewWidth) ||
    !Number.isFinite(plotLeft) ||
    !Number.isFinite(plotWidth) ||
    boundsWidth <= 0 ||
    viewWidth <= 0 ||
    plotWidth <= 0 ||
    !Number.isInteger(candleCount) ||
    candleCount < 1
  ) return null;
  if (candleCount === 1) return 0;
  const viewX = ((clientX - boundsLeft) / boundsWidth) * viewWidth;
  const index = Math.round(((viewX - plotLeft) / plotWidth) * (candleCount - 1));
  return Math.max(0, Math.min(candleCount - 1, index));
}

export function moveChartSelection(currentIndex, key, candleCount) {
  if (!Number.isInteger(candleCount) || candleCount < 1) return null;
  if (key === "Home") return 0;
  if (key === "End") return candleCount - 1;
  if (key !== "ArrowLeft" && key !== "ArrowRight") return null;
  const current = Number.isInteger(currentIndex)
    ? Math.max(0, Math.min(candleCount - 1, currentIndex))
    : candleCount - 1;
  const delta = key === "ArrowLeft" ? -1 : 1;
  return Math.max(0, Math.min(candleCount - 1, current + delta));
}

export function priceAxisTicks(minimum, maximum, divisions = 4) {
  if (
    !Number.isFinite(minimum) ||
    !Number.isFinite(maximum) ||
    maximum <= minimum ||
    !Number.isInteger(divisions) ||
    divisions < 1
  ) return [];
  const span = maximum - minimum;
  return Array.from({ length: divisions + 1 }, (_, index) => {
    const fraction = index / divisions;
    return { fraction, value: maximum - fraction * span };
  });
}

// Display precision only. It is chosen from a reference value's magnitude
// (for prices: the latest returned close), e.g. 2 for BTC, 4 for XRP
// (including below 1.00). The
// exact returned string is never rounded or replaced; it stays on hover.
export function displayDecimals(reference) {
  const magnitude = Math.abs(Number(reference));
  if (!Number.isFinite(magnitude) || magnitude === 0) return 8;
  if (magnitude >= 100) return 2;
  if (magnitude >= 0.1) return 4;
  if (magnitude >= 0.01) return 6;
  return 8;
}

export function formatDisplayNumber(value, decimals) {
  const numeric = typeof value === "number" ? value : Number(value);
  if ((typeof value !== "number" && typeof value !== "string") || value === "" || !Number.isFinite(numeric)) {
    return typeof value === "string" ? value : "—";
  }
  const digits = Number.isInteger(decimals) ? Math.max(0, Math.min(8, decimals)) : 2;
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(numeric);
}

// Crosshair readout at display precision. Prices and price-unit indicators
// (EMA, Bollinger, ATR, VWAP, MACD) use the instrument price decimals;
// other indicator values (RSI, Stochastic, CCI, volatility) use 2.
export function candleReadoutText(candle, indicatorValues = [], priceDecimals = 2) {
  const values = candle?.values;
  const source = candle?.source;
  if (!source || typeof source.open_time !== "string" || !values) return "Candle values are unavailable.";
  const prices = [["O", values.open], ["H", values.high], ["L", values.low], ["C", values.close]];
  if ([...prices, ["V", values.volume]].some(([, metric]) =>
    typeof metric?.exact !== "string" || typeof metric?.unit !== "string")) {
    return "Candle values are unavailable.";
  }
  const indicators = Array.isArray(indicatorValues)
    ? indicatorValues.filter((item) => typeof item?.label === "string" && typeof item?.value === "string")
    : [];
  return [
    source.open_time,
    `${prices.map(([label, metric]) => `${label} ${formatDisplayNumber(metric.exact, priceDecimals)}`).join(" ")} ${values.close.unit}`,
    `Vol ${formatDisplayNumber(values.volume.exact, displayDecimals(values.volume.exact))} ${values.volume.unit}`,
    ...indicators.map(({ label, value, priceUnit }) =>
      `${label}: ${formatDisplayNumber(value, priceUnit ? priceDecimals : 2)}`),
  ].join(" · ");
}

export function candleInspectorText(candle, indicatorValues = []) {
  const values = candle?.values;
  const source = candle?.source;
  if (!source || typeof source.open_time !== "string" || !values) return "Candle values are unavailable.";
  const fields = [
    ["Open", values.open],
    ["High", values.high],
    ["Low", values.low],
    ["Close", values.close],
    ["Volume", values.volume],
  ];
  if (fields.some(([, metric]) => typeof metric?.exact !== "string" || typeof metric?.unit !== "string")) {
    return "Candle values are unavailable.";
  }
  const returnedIndicators = Array.isArray(indicatorValues)
    ? indicatorValues.filter((value) => typeof value === "string" && value.length > 0)
    : [];
  return [
    source.open_time,
    ...fields.map(([label, metric]) => `${label}: ${metric.exact} ${metric.unit}`),
    ...returnedIndicators,
  ].join(" · ");
}

// ---- Chart workspace view (U2): display geometry only, never new values. ----

export const CHART_SCALE_MODES = Object.freeze(["auto", "log", "percent"]);
export const MIN_VISIBLE_CANDLES = 10;

// The visible window is a contiguous slice of the returned candles. The
// default (null) view shows every returned candle.
export function normaliseChartWindow(view, candleCount) {
  if (!Number.isInteger(candleCount) || candleCount < 1) return null;
  const minimum = Math.min(MIN_VISIBLE_CANDLES, candleCount);
  const count = Number.isInteger(view?.count)
    ? Math.max(minimum, Math.min(candleCount, view.count))
    : candleCount;
  const start = Number.isInteger(view?.start)
    ? Math.max(0, Math.min(candleCount - count, view.start))
    : candleCount - count;
  return { start, count };
}

// factor < 1 zooms in, > 1 zooms out. anchor (0..1) keeps that point of the
// visible window fixed, e.g. the pointer position.
export function zoomChartWindow(view, factor, candleCount, anchor = 1) {
  const current = normaliseChartWindow(view, candleCount);
  if (!current || !Number.isFinite(factor) || factor <= 0) return current;
  const fraction = Number.isFinite(anchor) ? Math.max(0, Math.min(1, anchor)) : 1;
  let count = Math.round(current.count * factor);
  if (count === current.count) count += factor < 1 ? -1 : factor > 1 ? 1 : 0;
  const pivot = current.start + fraction * (current.count - 1);
  const next = normaliseChartWindow({ count, start: 0 }, candleCount);
  return normaliseChartWindow(
    { count: next.count, start: Math.round(pivot - fraction * (next.count - 1)) },
    candleCount,
  );
}

export function panChartWindow(view, deltaCandles, candleCount) {
  const current = normaliseChartWindow(view, candleCount);
  if (!current || !Number.isFinite(deltaCandles)) return current;
  return normaliseChartWindow(
    { count: current.count, start: current.start + Math.round(deltaCandles) },
    candleCount,
  );
}

// Returns a projection for the price pane. "auto" is linear in price, "log"
// is linear in log10(price) and "percent" is linear in change from the first
// visible close (base). Log falls back to auto when any value is not > 0.
export function priceScale({ minimum, maximum, mode = "auto", base, divisions = 4 }) {
  if (!Number.isFinite(minimum) || !Number.isFinite(maximum) || maximum <= minimum) return null;
  let effective = CHART_SCALE_MODES.includes(mode) ? mode : "auto";
  let reason = null;
  if (effective === "log" && minimum <= 0) {
    effective = "auto";
    reason = "Log scale needs every plotted value above zero; showing Auto.";
  }
  if (effective === "percent" && !(Number.isFinite(base) && base > 0)) {
    effective = "auto";
    reason = "Percent scale needs a positive first visible close; showing Auto.";
  }
  const transform = effective === "log"
    ? (value) => Math.log10(value)
    : (value) => value;
  const low = transform(minimum);
  const high = transform(maximum);
  const fractionOf = (value) => {
    if (!Number.isFinite(value) || (effective === "log" && value <= 0)) return null;
    return (high - transform(value)) / (high - low);
  };
  const ticks = Array.from({ length: divisions + 1 }, (_, index) => {
    const fraction = index / divisions;
    const scaled = high - fraction * (high - low);
    const value = effective === "log" ? 10 ** scaled : scaled;
    const label = effective === "percent"
      ? `${value / base >= 1 ? "+" : ""}${((value / base - 1) * 100).toFixed(2)}%`
      : null;
    return { fraction, value, label };
  });
  const valueAt = (fraction) => {
    if (!Number.isFinite(fraction)) return null;
    const scaled = high - fraction * (high - low);
    return effective === "log" ? 10 ** scaled : scaled;
  };
  return { mode: effective, reason, fractionOf, valueAt, ticks };
}

// Evenly spaced candle indexes for the date axis and vertical grid lines.
export function timeAxisIndexes(visibleCount, divisions = 4) {
  if (!Number.isInteger(visibleCount) || visibleCount < 1) return [];
  if (visibleCount === 1) return [0];
  const steps = Math.max(1, Math.min(divisions, visibleCount - 1));
  return [...new Set(Array.from({ length: steps + 1 }, (_, index) =>
    Math.round(index * (visibleCount - 1) / steps)))];
}

// The last-price tag shows the exact returned close of the latest candle.
export function lastPriceTag(candle, previousCandle) {
  const close = candle?.values?.close;
  if (typeof close?.exact !== "string" || !Number.isFinite(close.numeric)) return null;
  const reference = previousCandle?.values?.close?.numeric ?? candle.values.open?.numeric;
  const direction = Number.isFinite(reference) && close.numeric < reference ? "down" : "up";
  return { text: close.exact, value: close.numeric, direction };
}

// UTC date-axis label: date only for daily candles, date and time otherwise.
export function axisTimeLabel(isoTime, timeframe) {
  const instant = typeof isoTime === "string" ? new Date(isoTime) : null;
  if (!instant || Number.isNaN(instant.valueOf())) return "";
  const text = instant.toISOString();
  return timeframe === "1d" ? text.slice(0, 10) : `${text.slice(5, 10)} ${text.slice(11, 16)}`;
}

// The one timeframe control (UR1): only the timeframes the research protocol
// uses. 1 minute and weekly/monthly candles are not offered.
export const CHART_TIMEFRAME_PILLS = Object.freeze([
  Object.freeze({ value: "1h", label: "1h", live: true }),
  Object.freeze({ value: "4h", label: "4h", live: true }),
  Object.freeze({ value: "1d", label: "1D", live: true }),
]);

const DECIMAL_TEXT = /^(?:\d+(?:\.\d*)?|\.\d+)$/;

// Backend trailing volume average from the volume-confirmation analysis. It is
// the average of the `lookback` candles before each candle (current excluded),
// exactly as returned; nothing is recalculated in the browser.
export function volumeReferenceLine(analysis) {
  const result = analysis?.result;
  if (!["AVAILABLE", "PARTIAL"].includes(analysis?.status) || !Number.isInteger(result?.lookback) ||
      result.lookback < 1 || !Array.isArray(result.points)) return null;
  const points = result.points.flatMap((point) =>
    point?.status === "READY" && typeof point.candle_end === "string" &&
      typeof point.trailing_average === "string" && DECIMAL_TEXT.test(point.trailing_average)
      ? [{ candleEnd: point.candle_end, value: point.trailing_average }]
      : []);
  return points.length > 1 ? { lookback: result.lookback, points } : null;
}
