// Presentation geometry only. Every input remains the validated exchange OHLC.
export const CHART_STYLES = Object.freeze([
  { id: "bars", label: "Bars", group: "Price" },
  { id: "candles", label: "Candlesticks", group: "Price" },
  { id: "hollow", label: "Hollow Candles", group: "Price" },
  { id: "line", label: "Line", group: "Line" },
  { id: "step", label: "Step Line", group: "Line" },
].map(Object.freeze));

export function closePath(candles, xOf, yOf, step = false) {
  return candles.map((candle, index) => {
    const x = xOf(index);
    const y = yOf(candle.values.close.numeric);
    return index === 0 ? `M ${x} ${y}` : step ? `H ${x} V ${y}` : `L ${x} ${y}`;
  }).join(" ");
}

export function normaliseToolbarPreferences(saved = {}) {
  const ids = CHART_STYLES.map((style) => style.id);
  const list = (value, allowed, fallback) => Array.isArray(value)
    ? [...new Set(value.filter((id) => allowed.includes(id)))] : fallback;
  return {
    chartStyle: ids.includes(saved.chartStyle) ? saved.chartStyle : "candles",
    favoriteStyles: list(saved.favoriteStyles, ids, []),
    favoriteTimeframes: list(saved.favoriteTimeframes, ["1h", "4h", "1d"], ["1h", "4h", "1d"]),
    favoriteTools: list(saved.favoriteTools, ["vwap"], []),
    volume: saved.volume !== false,
    studyWidths: Object.fromEntries(Object.entries(saved.studyWidths ?? {}).filter(([id, width]) =>
      /^(ema-(20|50|500)|atr-14|bollinger-bands-20|realized-volatility-20|rsi-14|macd-12-26-9|stochastic-14-3|cci-20|vwap)$/.test(id) && [1, 2, 3].includes(width))),
  };
}
