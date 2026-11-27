// Beginner "Plain reading" strip (UR1): describes the latest candle in plain
// words from the snapshot's backend indicator values (EMA20/EMA50 vs price,
// RSI zone, ATR as the typical move). Comparisons only — it is not a signal.
import { displayDecimals, formatDisplayNumber } from "./chart-interaction.mjs";
import { indicatorBindingError, plotValues } from "./workspace-state.mjs";

export const PLAIN_READING_NOTE =
  "Describes the chart in plain words from the backend's indicator values. Not a signal: only a strategy that passes its study can say “buy”.";

function latestValue(snapshot, id) {
  const indicator = snapshot?.indicators?.[id];
  if (!indicator) return { value: null, reason: "not supplied in response" };
  if (indicator.status !== "AVAILABLE") return { value: null, reason: indicator.reason_code ?? indicator.status ?? "unavailable" };
  const bindingError = indicatorBindingError(snapshot, id, indicator);
  if (bindingError) return { value: null, reason: bindingError };
  const lastCandle = snapshot.candles?.at(-1)?.close_time;
  const point = plotValues(indicator.result).at(-1);
  if (!point || Date.parse(point.candleEnd) !== Date.parse(lastCandle)) {
    return { value: null, reason: "no value at the latest candle" };
  }
  return { value: Number(point.value), exact: point.value };
}

export function plainReading(snapshot) {
  const close = snapshot?.candles?.at(-1)?.metrics?.close;
  const price = Number(close?.value);
  if (!snapshot || !Number.isFinite(price)) return { items: [], note: PLAIN_READING_NOTE };
  const decimals = displayDecimals(close.value);
  const items = [];

  const ema20 = latestValue(snapshot, "ema-20");
  const ema50 = latestValue(snapshot, "ema-50");
  if (ema20.value === null || ema50.value === null) {
    items.push({ key: "trend", tone: "muted", text: `Trend: unavailable — ${(ema20.value === null ? ema20 : ema50).reason}` });
  } else {
    const side = (a, b) => a > b ? "above" : a < b ? "below" : "at";
    const priceSide = side(price, ema50.value);
    const fastSide = side(ema20.value, ema50.value);
    const word = priceSide === "above" && fastSide === "above" ? "up"
      : priceSide === "below" && fastSide === "below" ? "down" : "mixed";
    items.push({
      key: "trend",
      tone: word === "up" ? "up" : word === "down" ? "down" : "muted",
      text: `Trend: ${word} (price ${priceSide} EMA50, EMA20 ${fastSide} EMA50)`,
      exact: `Close ${close.value}, EMA20 ${ema20.exact}, EMA50 ${ema50.exact} ${close.unit}`,
    });
  }

  const rsi = latestValue(snapshot, "rsi-14");
  if (rsi.value === null) {
    items.push({ key: "momentum", tone: "muted", text: `Momentum: RSI unavailable — ${rsi.reason}` });
  } else {
    const zone = rsi.value < 30 ? "below 30 = weak, oversold zone"
      : rsi.value > 70 ? "above 70 = strong, overbought zone" : "between 30 and 70 = normal";
    items.push({ key: "momentum", tone: "muted", text: `Momentum: RSI ${formatDisplayNumber(rsi.value, 1)} (${zone})`, exact: `RSI 14 ${rsi.exact}` });
  }

  const atr = latestValue(snapshot, "atr-14");
  if (atr.value === null) {
    items.push({ key: "volatility", tone: "muted", text: `Volatility: ATR unavailable — ${atr.reason}` });
  } else {
    const percent = (atr.value / price) * 100;
    items.push({
      key: "volatility",
      tone: "muted",
      text: `Volatility: ATR ${formatDisplayNumber(atr.value, decimals)} ${close.unit} (typical move per candle, ${percent.toFixed(2)}% of price)`,
      exact: `ATR 14 ${atr.exact} ${close.unit}`,
    });
  }
  return { items, note: PLAIN_READING_NOTE };
}
