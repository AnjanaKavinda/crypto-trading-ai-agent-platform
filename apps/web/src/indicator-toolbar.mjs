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

// kind: "indicator" toggles a chart overlay/pane; "overlay" toggles a backend
// analysis drawn on the price pane; "analysis" jumps to its analysis card;
// "signals" turns replayed strategy markers on/off; "fixed" is always drawn;
// status marks not-ready pills. hint = plain-language hover text.
export const TOOLBAR_PILLS = Object.freeze([
  { short: "SIGNALS", label: "BUY / SELL markers", group: "strategy", kind: "signals", id: "strategy-markers",
    hint: "Choose a strategy and version to inspect its replayed BUY/SELL points and sourced verdict. Illustration only, not a trade signal." },
  { short: "EMA20", label: "EMA 20", group: "trend", kind: "indicator", id: "ema-20",
    hint: "Average of the last 20 closes, recent ones weighted more — the short-term trend." },
  { short: "EMA50", label: "EMA 50", group: "trend", kind: "indicator", id: "ema-50",
    hint: "Average of the last 50 closes — the slower trend. Price above it is often called an uptrend." },
  { short: "EMA500", label: "EMA 500", group: "trend", kind: "indicator", id: "ema-500",
    hint: "Very long average (500 closes) — broad context; needs 500 candles to warm up." },
  { short: "BB", label: "Bollinger Bands 20", group: "trend", kind: "indicator", id: "bollinger-bands-20",
    hint: "A band two standard deviations around the 20-close average — wide bands mean a jumpy market." },
  { short: "VWAP", label: "VWAP", group: "trend", kind: "overlay", id: "vwap",
    hint: "Volume-weighted average price from the first candle of this snapshot (candle approximation)." },
  { short: "SMA", label: "SMA", group: "trend", status: "CONNECT" },
  { short: "WMA", label: "WMA", group: "trend", status: "CONNECT" },
  { short: "ICHI", label: "Ichimoku", group: "trend", status: "BUILD" },
  { short: "RSI", label: "RSI 14", group: "momentum", kind: "indicator", id: "rsi-14",
    hint: "Momentum from 0 to 100: above 70 = strong run-up, below 30 = strong sell-off. Not a reversal signal." },
  { short: "MACD", label: "MACD 12/26/9", group: "momentum", kind: "indicator", id: "macd-12-26-9",
    hint: "Gap between a fast and a slow average, its signal line and the histogram of their difference." },
  { short: "STOCH", label: "Stochastic 14/3", group: "momentum", kind: "indicator", id: "stochastic-14-3",
    hint: "Where the close sits in the last 14 candles' range, 0 to 100." },
  { short: "CCI", label: "CCI 20", group: "momentum", kind: "indicator", id: "cci-20",
    hint: "How far the typical price is from its 20-candle average; ±100 marks unusual moves." },
  { short: "ADX", label: "ADX", group: "momentum", status: "BUILD" },
  { short: "ATR", label: "ATR 14", group: "volatility", kind: "indicator", id: "atr-14",
    hint: "Average true range — how far price typically moves in one candle, in USDT." },
  { short: "RVOL", label: "Realized volatility 20", group: "volatility", kind: "indicator", id: "realized-volatility-20",
    hint: "How much returns varied over the last 20 candles (annualised), not a forecast." },
  { short: "BBW", label: "Bollinger bandwidth", group: "volatility", status: "CONNECT" },
  { short: "VOL", label: "Volume", group: "volume", kind: "fixed",
    hint: "How much of the coin traded in each candle, with its prior-20 average." },
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

// Beginner shows the seven essentials only (UR1).
export const BEGINNER_PILLS = Object.freeze(["SIGNALS", "EMA20", "EMA50", "BB", "RSI", "ATR", "VOL"]);

// availability(kind, id) -> { available: boolean, reason?: string } for the
// loaded snapshot; enabled = currently shown overlay/pane ids.
export function toolbarPills({ availability, enabled = [], snapshotLoaded = false, mode = "pro", signalsOn = false, volumeOn = true }) {
  const pills = mode === "beginner" ? TOOLBAR_PILLS.filter((pill) => BEGINNER_PILLS.includes(pill.short)) : TOOLBAR_PILLS;
  return pills.map((pill) => {
    const group = PILL_GROUPS[pill.group];
    const base = { short: pill.short, label: pill.label, group: group.name, color: group.color, hint: pill.hint ?? null };
    if (pill.status) {
      return { ...base, live: false, action: null, pressed: null,
        badge: PILL_STATUS_LABELS[pill.status], reason: pill.reason ?? PILL_STATUS_REASONS[pill.status] };
    }
    if (!snapshotLoaded) {
      return { ...base, live: false, action: null, pressed: null, badge: "Live",
        reason: "Load a snapshot to use this backend result." };
    }
    if (pill.kind === "signals") {
      return { ...base, live: true, action: { type: "signals" }, pressed: String(signalsOn), badge: "Live",
        reason: signalsOn
          ? "On — replayed strategy markers, illustration only. Click to hide."
          : "Off — choose a strategy and version to inspect its replay and study evidence." };
    }
    if (pill.kind === "fixed") {
      return { ...base, live: true, action: { type: "toggle", id: "volume" }, pressed: String(volumeOn), badge: "Live", reason: "Display volume from the returned candles." };
    }
    const state = availability(pill.kind === "overlay" ? "analysis" : pill.kind, pill.id);
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
