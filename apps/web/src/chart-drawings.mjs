// U4 drawing tools: the owner's own chart annotations. They are stored only
// in this browser, never sent to the API and never treated as evidence.
// Anchors are candle close times plus prices, so drawings survive zoom, pan
// and scale changes.

export const DRAWING_LABEL = "Your annotation — not evidence";

export const DRAWING_TOOLS = Object.freeze([
  { id: "cursor", glyph: "↖", title: "Select / pan", clicks: 0 },
  { id: "cross", glyph: "+", title: "Crosshair (inspect without panning)", clicks: 0 },
  { id: "hline", glyph: "—", title: "Horizontal line: click a price", clicks: 1 },
  { id: "trend", glyph: "╱", title: "Trend line: click two points", clicks: 2 },
  { id: "rect", glyph: "▭", title: "Rectangle zone: click two corners", clicks: 2 },
  { id: "long", glyph: "L", title: "Long position: click entry, stop, target", clicks: 3 },
  { id: "short", glyph: "S", title: "Short position: Spot cannot short — research only. Click entry, stop, target", clicks: 3 },
  { id: "range", glyph: "ΔP", title: "Price range: click two prices for change and %", clicks: 2 },
  { id: "fib", glyph: "FIB", title: "Fibonacci retracement: click swing start, then swing end", clicks: 2 },
  { id: "note", glyph: "T", title: "Text note: type the note, then click the chart", clicks: 1 },
  { id: "clear", glyph: "⌫", title: "Clear my drawings for this market and timeframe", clicks: 0 },
].map((tool) => Object.freeze(tool)));

const DRAWING_TYPES = new Set(DRAWING_TOOLS.filter((tool) => tool.clicks > 0).map((tool) => tool.id));
const CLICKS = Object.fromEntries(DRAWING_TOOLS.map((tool) => [tool.id, tool.clicks]));
const STORAGE_PREFIX = "spot-research.drawings.v1";
const MAX_DRAWINGS = 200;
const MAX_NOTE = 200;

export const FIB_RATIOS = Object.freeze([0, 0.236, 0.382, 0.5, 0.618, 0.786, 1]);

export function drawingTool(id) {
  return DRAWING_TOOLS.find((tool) => tool.id === id) ?? null;
}

export function drawingsKey(instrumentId, timeframe) {
  return `${STORAGE_PREFIX}:${instrumentId}:${timeframe}`;
}

function validAnchor(anchor) {
  return Boolean(anchor) && typeof anchor.time === "string" && Number.isFinite(Date.parse(anchor.time)) &&
    Number.isFinite(anchor.price) && anchor.price > 0;
}

export function validDrawing(drawing) {
  if (!drawing || !DRAWING_TYPES.has(drawing.type) || !Array.isArray(drawing.anchors)) return false;
  if (drawing.anchors.length !== CLICKS[drawing.type] || !drawing.anchors.every(validAnchor)) return false;
  if (drawing.type === "note") {
    return typeof drawing.text === "string" && drawing.text.trim().length > 0 && drawing.text.length <= MAX_NOTE;
  }
  return drawing.text === undefined;
}

export function createDrawing(type, anchors, text) {
  const drawing = { type, anchors: anchors.map(({ time, price }) => ({ time, price })) };
  if (type === "note") drawing.text = String(text ?? "").trim().slice(0, MAX_NOTE);
  return validDrawing(drawing) ? drawing : null;
}

export function loadDrawings(storage, key) {
  try {
    const saved = JSON.parse(storage.getItem(key));
    return Array.isArray(saved) ? saved.filter(validDrawing).slice(0, MAX_DRAWINGS) : [];
  } catch {
    return [];
  }
}

export function saveDrawings(storage, key, drawings) {
  try {
    const safe = drawings.filter(validDrawing).slice(0, MAX_DRAWINGS);
    if (safe.length) storage.setItem(key, JSON.stringify(safe));
    else storage.removeItem(key);
    return true;
  } catch {
    return false;
  }
}

// 0 is the swing end (second click), 1 the swing start (first click).
export function fibLevels(startPrice, endPrice) {
  return FIB_RATIOS.map((ratio) => ({ ratio, price: endPrice + (startPrice - endPrice) * ratio }));
}

export function priceRange(fromPrice, toPrice) {
  const change = toPrice - fromPrice;
  return { change, percent: (change / fromPrice) * 100 };
}

// Entry, stop and target are the owner's clicked prices; R = reward / risk.
// No position size is derived here.
export function positionSummary(type, entry, stop, target) {
  const ordered = type === "long" ? stop < entry && entry < target : target < entry && entry < stop;
  if (!ordered) {
    return {
      valid: false,
      reason: type === "long"
        ? "Long needs stop below entry and target above entry."
        : "Short needs target below entry and stop above entry.",
    };
  }
  const risk = Math.abs(entry - stop);
  const reward = Math.abs(target - entry);
  return {
    valid: true,
    risk,
    reward,
    rMultiple: reward / risk,
    riskPercent: (risk / entry) * 100,
    rewardPercent: (reward / entry) * 100,
  };
}
