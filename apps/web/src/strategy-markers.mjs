// U5: strategy markers and their evidence, exactly as returned by
// GET /api/research/spot/{instrument}/strategy-markers. Nothing is calculated
// here; values are shown with the label the backend gave them.

export const MARKER_LABELS = Object.freeze({
  VERIFIED_FACT: "Verified fact",
  RESEARCH_PROPOSAL: "Research proposal",
  NOT_APPLICABLE: "Not applicable",
  UNAVAILABLE: "Unavailable",
});

const DECIMAL = /^(?:0|[1-9]\d*)(?:\.\d+)?$/;

// Owner sizing inputs: plain positive decimals; risk % at most 100.
export function sizingInputs(accountText, riskText) {
  const account = String(accountText ?? "").trim();
  const risk = String(riskText ?? "").trim();
  if (!account && !risk) return { ok: true, accountSize: null, riskPct: null };
  if (!DECIMAL.test(account) || Number(account) <= 0) {
    return { ok: false, error: "Account size must be a positive USDT amount, e.g. 1000." };
  }
  if (!DECIMAL.test(risk) || Number(risk) <= 0 || Number(risk) > 100) {
    return { ok: false, error: "Risk % must be above 0 and at most 100, e.g. 1." };
  }
  return { ok: true, accountSize: account, riskPct: risk };
}

// The markers response must belong to the loaded snapshot.
export function markersBindingError(response, snapshot) {
  if (!response || typeof response !== "object") return "No strategy-marker response.";
  if (!snapshot) return "No snapshot is loaded.";
  for (const key of ["instrument_id", "timeframe", "snapshot_id"]) {
    if (response[key] !== snapshot[key]) return `Strategy markers do not match the loaded snapshot (${key}).`;
  }
  if (!["AVAILABLE", "UNAVAILABLE", "WARMUP"].includes(response.status) || !Array.isArray(response.markers)) {
    return "Strategy-marker response is not in the expected form.";
  }
  if (response.status !== "AVAILABLE" && response.markers.length) {
    return "Unavailable strategy markers must not carry markers.";
  }
  return null;
}

// Where each marker is drawn: BUY at its fill candle (signal candle while
// pending), SELL at its fill candle; candles matched by exact open time.
export function markerAnchors(markers, openTimes) {
  const index = new Map(openTimes.map((time, position) => [Date.parse(time), position]));
  return markers.flatMap((marker, markerIndex) => {
    if (!["BUY", "SELL"].includes(marker?.side)) return [];
    const time = marker.status === "FILLED" ? marker.fill_time?.value : marker.time?.value;
    const candleIndex = typeof time === "string" ? index.get(Date.parse(time)) : undefined;
    if (candleIndex === undefined) return [];
    return [{ markerIndex, candleIndex, side: marker.side, pending: marker.status !== "FILLED" }];
  });
}

// Flatten a marker's labelled fields for the Trade details list.
export function tradeDetails(marker) {
  const rows = [];
  const add = (name, field, key) => {
    if (field && typeof field === "object" && Object.hasOwn(MARKER_LABELS, field.label)) {
      rows.push({ name, key, label: field.label, value: field.value ?? null, reason: field.reason ?? null });
    }
  };
  for (const [key, name] of [
    ["time", "Signal candle"], ["fill_time", "Fill candle"], ["entry_open", "Entry candle open"],
    ["modelled_entry_fill", "Modelled entry fill"], ["stop_distance", "Stop distance"], ["stop", "Stop"],
    ["modelled_exit_fill", "Modelled exit fill"], ["net_return", "Net return"], ["r_multiple", "R multiple"],
  ]) add(name, marker?.[key], key);
  const size = marker?.position_size;
  if (size) {
    add("Position size (quantity)", size.quantity, "quantity");
    add("Risk amount (USDT)", size.risk_amount_usdt, "risk_amount_usdt");
    add("Notional (USDT)", size.notional_usdt, "notional_usdt");
    add("Loss at stop (USDT)", size.loss_at_stop_usdt, "loss_at_stop_usdt");
  }
  return rows;
}

// U5b: display precision for every number in the marker and evidence panel.
// The exact backend string is returned alongside for the hover title; nothing
// is rounded in the record itself.
const NUMERIC = /^-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;
const ISO_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;
const TWO_DP_KEYS = /(^|_)(rsi|adx|stochastic|cci|r_multiple)(_|$)/;

function trimmed(value, decimals) {
  return new Intl.NumberFormat("en-US", { minimumFractionDigits: 0, maximumFractionDigits: decimals }).format(value);
}

export function markerFieldDisplay(key, value, priceDecimals = 2) {
  if (value === null || value === undefined || value === "") return { text: "—", exact: null };
  const exact = String(value);
  if (ISO_TIME.test(exact) && Number.isFinite(Date.parse(exact))) {
    return { text: `${new Date(exact).toISOString().slice(0, 16).replace("T", " ")} UTC`, exact };
  }
  if (!NUMERIC.test(exact) || !Number.isFinite(Number(exact))) return { text: exact, exact: null };
  const number = Number(exact);
  const name = String(key ?? "").toLowerCase();
  const fixed = (decimals) => new Intl.NumberFormat("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals }).format(number);
  if (name === "net_return") {
    return { text: `${number >= 0 ? "+" : "−"}${new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Math.abs(number * 100))}%`, exact };
  }
  if (name === "r_multiple") return { text: `${fixed(2)} R`, exact };
  if (name === "quantity") return { text: trimmed(number, 8), exact };
  if (name.endsWith("_usdt") || name.endsWith("_bps_per_side")) return { text: fixed(name.endsWith("_bps_per_side") ? 0 : 2), exact };
  if (TWO_DP_KEYS.test(name)) return { text: fixed(2), exact };
  return { text: fixed(Math.max(0, Math.min(8, priceDecimals))), exact };
}
