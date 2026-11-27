// UR2 indicator sub-panes. Each oscillator gets its own pane with its own
// y-axis, reference lines and a legend whose colours match its lines. Display
// geometry only: every plotted value is the backend's returned value.

const pane = (definition) => Object.freeze({
  ...definition,
  series: Object.freeze(definition.series.map((series) => Object.freeze(series))),
  reference: Object.freeze(definition.reference),
});

export const PANE_DEFINITIONS = Object.freeze([
  pane({
    id: "atr-14", key: "atr", title: "ATR 14", priceUnit: true, range: { type: "auto", floor: 0 }, reference: [],
    series: [{ className: "atr-line", field: "value", label: "ATR", color: "#fb923c" }],
  }),
  pane({
    id: "realized-volatility-20", key: "realized-volatility", title: "RVOL 20", range: { type: "auto", floor: 0 }, reference: [],
    series: [{ className: "realized-volatility-line", field: "value", label: "RV20", color: "#fb7185" }],
  }),
  pane({
    id: "rsi-14", key: "rsi", title: "RSI 14", range: { type: "fixed", min: 0, max: 100 }, reference: [30, 70],
    series: [{ className: "rsi-line", field: "value", label: "RSI", color: "#c084fc" }],
  }),
  pane({
    id: "macd-12-26-9", key: "macd", title: "MACD 12/26/9", priceUnit: true, range: { type: "auto", include: [0] }, reference: [0],
    series: [
      { className: "macd-histogram", field: "histogram", label: "Hist", color: "#94a3b8", kind: "bars" },
      { className: "macd-line", field: "line", label: "MACD", color: "#38bdf8" },
      { className: "macd-signal", field: "signal", label: "Signal", color: "#f59e0b" },
    ],
  }),
  pane({
    id: "stochastic-14-3", key: "stochastic", title: "Stoch 14/3", range: { type: "fixed", min: 0, max: 100 }, reference: [20, 80],
    series: [
      { className: "stochastic-k", field: "k", label: "%K", color: "#38bdf8" },
      { className: "stochastic-d", field: "d", label: "%D", color: "#f59e0b" },
    ],
  }),
  pane({
    id: "cci-20", key: "cci", title: "CCI 20", range: { type: "auto", include: [-100, 100] }, reference: [-100, 100],
    series: [{ className: "cci-line", field: "value", label: "CCI", color: "#2dd4bf" }],
  }),
]);

export const PANE_IDS = Object.freeze(PANE_DEFINITIONS.map((definition) => definition.id));

// Y-axis range for one pane from its visible values. Bounded oscillators keep
// their 0–100 scale; others fit the data, always showing their reference lines.
export function paneRange(definition, numbers) {
  const finite = (numbers ?? []).filter(Number.isFinite);
  if (definition.range.type === "fixed") {
    return {
      min: Math.min(definition.range.min, ...finite),
      max: Math.max(definition.range.max, ...finite),
    };
  }
  const values = [...finite, ...(definition.range.include ?? [])];
  if (!values.length) return null;
  let min = Math.min(...values);
  let max = Math.max(...values);
  if (min === max) {
    const pad = Math.max(Math.abs(min) * 0.02, 1);
    return { min: min - pad, max: max + pad };
  }
  const pad = (max - min) * 0.08;
  const floor = definition.range.floor;
  min = Number.isFinite(floor) && min >= floor ? Math.max(floor, min - pad) : min - pad;
  max += pad;
  return { min, max };
}

// "Nice" axis values (1/2/2.5/5 × 10^n steps) inside [min, max].
export function niceTicks(min, max, target = 3) {
  if (!Number.isFinite(min) || !Number.isFinite(max) || !(max > min) || !(target >= 1)) return [];
  const raw = (max - min) / target;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((multiple) => multiple * power).find((value) => value >= raw * 0.999) ?? 10 * power;
  const ticks = [];
  for (let value = Math.ceil(min / step) * step; value <= max + step * 1e-9; value += step) {
    ticks.push(Number(value.toPrecision(12)));
  }
  return ticks;
}

// Panes in the owner's chosen order; unknown or new panes keep the default order.
export function orderedPanes(ids, order = []) {
  const rank = (id) => {
    const index = order.indexOf(id);
    return index < 0 ? order.length + PANE_IDS.indexOf(id) : index;
  };
  return [...ids].sort((a, b) => rank(a) - rank(b));
}

// Move one pane up (-1) or down (+1) within the shown panes; returns the new order.
export function movePane(shownIds, order, id, delta) {
  const current = orderedPanes(shownIds, order);
  const index = current.indexOf(id);
  const target = index + delta;
  if (index < 0 || target < 0 || target >= current.length) return current;
  [current[index], current[target]] = [current[target], current[index]];
  return current;
}
