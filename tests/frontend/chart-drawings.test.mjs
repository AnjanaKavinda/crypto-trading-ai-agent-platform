// U4 drawing helpers. All prices and times below are SYNTHETIC test values.
import assert from "node:assert/strict";
import test from "node:test";
import {
  createDrawing,
  DRAWING_TOOLS,
  drawingsKey,
  fibLevels,
  loadDrawings,
  positionSummary,
  priceRange,
  saveDrawings,
} from "../../apps/web/src/chart-drawings.mjs";
import { priceScale } from "../../apps/web/src/chart-interaction.mjs";

const T1 = "2026-01-01T04:00:00Z";
const T2 = "2026-01-01T08:00:00Z";

function memoryStorage() {
  const data = new Map();
  return {
    getItem: (key) => (data.has(key) ? data.get(key) : null),
    setItem: (key, value) => data.set(key, String(value)),
    removeItem: (key) => data.delete(key),
    data,
  };
}

test("toolbar lists every prototype tool and labels short as research only", () => {
  assert.deepEqual(DRAWING_TOOLS.map((tool) => tool.id),
    ["cursor", "cross", "hline", "trend", "rect", "long", "short", "range", "fib", "note", "clear"]);
  assert.match(DRAWING_TOOLS.find((tool) => tool.id === "short").title, /Spot cannot short — research only/);
});

test("drawings are anchored to candle times and prices and validated", () => {
  assert.deepEqual(createDrawing("hline", [{ time: T1, price: 100 }]), { type: "hline", anchors: [{ time: T1, price: 100 }] });
  assert.equal(createDrawing("trend", [{ time: T1, price: 100 }]), null, "needs two anchors");
  assert.equal(createDrawing("hline", [{ time: "not a time", price: 100 }]), null);
  assert.equal(createDrawing("hline", [{ time: T1, price: -1 }]), null);
  assert.equal(createDrawing("note", [{ time: T1, price: 100 }], "  "), null, "empty note");
  assert.equal(createDrawing("note", [{ time: T1, price: 100 }], "breakout?").text, "breakout?");
  assert.equal(createDrawing("cursor", []), null);
});

test("storage is per market and timeframe, versioned, and tolerant of bad data", () => {
  const storage = memoryStorage();
  const key = drawingsKey("BTC-USDT-SPOT", "4h");
  assert.equal(key, "spot-research.drawings.v1:BTC-USDT-SPOT:4h");
  assert.notEqual(key, drawingsKey("BTC-USDT-SPOT", "1h"));
  const fib = createDrawing("fib", [{ time: T1, price: 120 }, { time: T2, price: 100 }]);
  assert.equal(saveDrawings(storage, key, [fib, { type: "evil" }]), true);
  assert.deepEqual(loadDrawings(storage, key), [fib]);
  storage.setItem(key, "{not json");
  assert.deepEqual(loadDrawings(storage, key), []);
  saveDrawings(storage, key, []);
  assert.equal(storage.data.has(key), false);
  const throwing = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } };
  assert.deepEqual(loadDrawings(throwing, key), []);
  assert.equal(saveDrawings(throwing, key, [fib]), false);
});

test("fibonacci levels run from swing end (0) to swing start (1)", () => {
  const levels = fibLevels(200, 100);
  assert.deepEqual(levels.map((level) => level.ratio), [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1]);
  assert.equal(levels[0].price, 100);
  assert.equal(levels[3].price, 150);
  assert.equal(levels.at(-1).price, 200);
  assert.ok(Math.abs(levels[4].price - 161.8) < 1e-9);
});

test("price range and position R multiple use the clicked prices only", () => {
  assert.deepEqual(priceRange(100, 110), { change: 10, percent: 10 });
  assert.deepEqual(priceRange(200, 150), { change: -50, percent: -25 });
  const long = positionSummary("long", 100, 95, 115);
  assert.equal(long.valid, true);
  assert.equal(long.rMultiple, 3);
  assert.equal(long.riskPercent, 5);
  assert.equal(positionSummary("long", 100, 105, 115).valid, false);
  const short = positionSummary("short", 100, 104, 92);
  assert.equal(short.rMultiple, 2);
  assert.match(positionSummary("short", 100, 95, 110).reason, /target below entry/);
});

test("price scale inverts back to the clicked price in auto and log modes", () => {
  for (const mode of ["auto", "log", "percent"]) {
    const scale = priceScale({ minimum: 50, maximum: 200, mode, base: 100 });
    for (const value of [50, 75.5, 123, 200]) {
      assert.ok(Math.abs(scale.valueAt(scale.fractionOf(value)) - value) < 1e-9, `${mode} ${value}`);
    }
  }
});
