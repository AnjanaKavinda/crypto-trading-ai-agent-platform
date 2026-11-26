// U3 indicator toolbar catalogue. A pill is live only when the backend has
// returned that result for the loaded snapshot; every other pill is disabled
// with the reason. Nothing here calculates or invents a value.

export const PILL_GROUPS = Object.freeze({
  strategy: Object.freeze({ name: "Strategy", color: "#22c55e" }),
  trend: Object.freeze({ name: "Trend overlays", color: "#38bdf8" }),
  momentum: Object.freeze({ name: "Momentum", color: "#c084fc" }),
  volatility: Object.freeze({ name: "Volatility", color: "#fb923c" }),
  volume: Object.freeze({ name: "Volume", color: "#facc15" }),
  structure: Object.freeze({ name: "Structure & context", color: "#2dd4bf" }),
  orderFlow: Object.freeze({ name: "Order flow", color: "#f472b6" }),
});

export const PILL_STATUS_REASONS = Object.freeze({
  CONNECT: "Calculated in the backend; not yet sent to the chart.",
  BUILD: "Planned; not implemented yet.",
  TRADES: "Needs Binance trade history (free) — data decision #355.",
  BOOK: "Needs order-book recording (24/7 or paid vendor) — data decision #355.",
});

export const PILL_STATUS_LABELS = Object.freeze({
  CONNECT: "Connect", BUILD: "To build", TRADES: "Needs trades", BOOK: "Needs order book",
});

// kind: "indicator" toggles a chart overlay/panel; "analysis" jumps to its
// backend analysis card; "fixed" is always drawn; status marks not-ready pills.
export const TOOLBAR_PILLS = Object.freeze([
  { short: "SIGNALS", label: "BUY / SELL markers", group: "strategy", status: "CONNECT", reason: "Strategy markers API is merged (E3); chart markers arrive with U5." },
  { short: "EMA20", label: "EMA 20", group: "trend", kind: "indicator", id: "ema-20" },
  { short: "EMA50", label: "EMA 50", group: "trend", kind: "indicator", id: "ema-50" },
  { short: "EMA500", label: "EMA 500", group: "trend", kind: "indicator", id: "ema-500" },
  { short: "BB", label: "Bollinger Bands 20", group: "trend", kind: "indicator", id: "bollinger-bands-20" },
  { short: "VWAP", label: "VWAP", group: "trend", kind: "analysis", id: "vwap" },
  { short: "SMA", label: "SMA", group: "trend", status: "CONNECT" },
  { short: "WMA", label: "WMA", group: "trend", status: "CONNECT" },
  { short: "ICHI", label: "Ichimoku", group: "trend", status: "BUILD" },
  { short: "RSI", label: "RSI 14", group: "momentum", kind: "indicator", id: "rsi-14" },
  { short: "MACD", label: "MACD 12/26/9", group: "momentum", kind: "indicator", id: "macd-12-26-9" },
  { short: "STOCH", label: "Stochastic 14/3", group: "momentum", kind: "indicator", id: "stochastic-14-3" },
  { short: "CCI", label: "CCI 20", group: "momentum", kind: "indicator", id: "cci-20" },
  { short: "ADX", label: "ADX", group: "momentum", status: "BUILD" },
  { short: "ATR", label: "ATR 14", group: "volatility", kind: "indicator", id: "atr-14" },
  { short: "RVOL", label: "Realized volatility 20", group: "volatility", kind: "indicator", id: "realized-volatility-20" },
  { short: "BBW", label: "Bollinger bandwidth", group: "volatility", status: "CONNECT" },
  { short: "VOL", label: "Volume", group: "volume", kind: "fixed" },
  { short: "VPRO", label: "Volume profile (POC/VAH/VAL)", group: "volume", kind: "analysis", id: "volume-profile" },
  { short: "VCONF", label: "Volume confirmation", group: "volume", kind: "analysis", id: "volume-confirmation" },
  { short: "OBV", label: "OBV", group: "volume", status: "BUILD" },
  { short: "S/R", label: "Support / resistance", group: "structure", kind: "analysis", id: "price-action-support-resistance" },
  { short: "MS", label: "Market structure (BOS/CHoCH)", group: "structure", kind: "analysis", id: "spot-market-structure" },
  { short: "REGIME", label: "Market regime", group: "structure", status: "CONNECT" },
  { short: "SMC", label: "Smart Money Concepts", group: "structure", status: "CONNECT" },
  { short: "FIB", label: "Fibonacci", group: "structure", status: "CONNECT" },
  { short: "WYC", label: "Wyckoff", group: "structure", status: "CONNECT" },
  { short: "CVD", label: "CVD / delta", group: "orderFlow", status: "TRADES" },
  { short: "FOOT", label: "Footprint", group: "orderFlow", status: "TRADES" },
  { short: "XVP", label: "Exact volume profile", group: "orderFlow", status: "TRADES" },
  { short: "HEAT", label: "Heatmap / Bookmap", group: "orderFlow", status: "BOOK" },
  { short: "ABS", label: "Absorption levels", group: "orderFlow", status: "BOOK" },
].map((pill) => Object.freeze(pill)));

// availability(kind, id) -> { available: boolean, reason?: string } for the
// loaded snapshot; enabled = currently shown indicator ids.
export function toolbarPills({ availability, enabled = [], snapshotLoaded = false }) {
  return TOOLBAR_PILLS.map((pill) => {
    const group = PILL_GROUPS[pill.group];
    const base = { short: pill.short, label: pill.label, group: group.name, color: group.color };
    if (pill.status) {
      return { ...base, live: false, action: null, pressed: null,
        badge: PILL_STATUS_LABELS[pill.status], reason: pill.reason ?? PILL_STATUS_REASONS[pill.status] };
    }
    if (!snapshotLoaded) {
      return { ...base, live: false, action: null, pressed: null, badge: "Live",
        reason: "Load a snapshot to use this backend result." };
    }
    if (pill.kind === "fixed") {
      return { ...base, live: true, action: null, pressed: "true", badge: "Live", reason: "Always shown from the returned candles." };
    }
    const state = availability(pill.kind, pill.id);
    if (!state.available) {
      return { ...base, live: false, action: null, pressed: null, badge: "Live",
        reason: `Unavailable for this snapshot: ${state.reason ?? "not supplied in response"}.` };
    }
    if (pill.kind === "analysis") {
      return { ...base, live: true, action: { type: "jump", id: pill.id }, pressed: null, badge: "Live",
        reason: "Backend analysis — click to open its result card." };
    }
    const on = enabled.includes(pill.id);
    return { ...base, live: true, action: { type: "toggle", id: pill.id }, pressed: String(on), badge: "Live",
      reason: on ? "Shown — click to hide." : "Live — click to show." };
  });
}
