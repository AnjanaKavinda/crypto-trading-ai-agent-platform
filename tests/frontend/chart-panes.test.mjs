import assert from "node:assert/strict";
import test from "node:test";
import { movePane, niceTicks, orderedPanes, PANE_DEFINITIONS, PANE_IDS, paneRange } from "../../apps/web/src/chart-panes.mjs";
import { plainReading } from "../../apps/web/src/plain-reading.mjs";
import { INDICATOR_IDS } from "../../apps/web/src/workspace-state.mjs";

const pane = (id) => PANE_DEFINITIONS.find((item) => item.id === id);

test("UR2: ATR, RVOL, RSI, MACD, Stochastic and CCI each have a pane with reference lines", () => {
  assert.deepEqual(PANE_IDS, ["atr-14", "realized-volatility-20", "rsi-14", "macd-12-26-9", "stochastic-14-3", "cci-20"]);
  for (const id of PANE_IDS) assert.ok(INDICATOR_IDS.includes(id), id);
  assert.deepEqual([...pane("rsi-14").reference], [30, 70]);
  assert.deepEqual([...pane("stochastic-14-3").reference], [20, 80]);
  assert.deepEqual([...pane("cci-20").reference], [-100, 100]);
  assert.deepEqual([...pane("macd-12-26-9").reference], [0]);
  assert.equal(pane("macd-12-26-9").series.find((series) => series.field === "histogram").kind, "bars");
  // Every series has its own colour so legend and line can match.
  for (const definition of PANE_DEFINITIONS) {
    const colours = definition.series.map((series) => series.color);
    assert.equal(new Set(colours).size, colours.length, definition.id);
  }
});

test("UR2: pane ranges keep bounded oscillators at 0–100 and always show reference lines", () => {
  // Synthetic values; not market data.
  assert.deepEqual(paneRange(pane("rsi-14"), [41, 58]), { min: 0, max: 100 });
  const cci = paneRange(pane("cci-20"), [-20, 40]);
  assert.ok(cci.min < -100 && cci.max > 100);
  const macd = paneRange(pane("macd-12-26-9"), [-5, -2]);
  assert.ok(macd.max >= 0, "MACD zero line stays visible");
  const atr = paneRange(pane("atr-14"), [10, 12]);
  assert.ok(atr.min >= 0 && atr.min < 10 && atr.max > 12);
  assert.equal(paneRange(pane("atr-14"), []), null);
});

test("UR2: nice axis ticks and pane ordering", () => {
  assert.deepEqual(niceTicks(0, 100, 3), [0, 50, 100]);
  assert.deepEqual(niceTicks(-130, 130, 3), [-100, 0, 100]);
  assert.deepEqual(niceTicks(1.8, 3.1, 3), [2, 2.5, 3]);
  assert.deepEqual(niceTicks(5, 5), []);
  const shown = ["atr-14", "rsi-14", "macd-12-26-9"];
  assert.deepEqual(orderedPanes(shown, []), shown);
  assert.deepEqual(orderedPanes(shown, ["macd-12-26-9"]), ["macd-12-26-9", "atr-14", "rsi-14"]);
  assert.deepEqual(movePane(shown, [], "rsi-14", -1), ["rsi-14", "atr-14", "macd-12-26-9"]);
  assert.deepEqual(movePane(shown, [], "atr-14", -1), shown, "the top pane cannot move up");
});

function syntheticSnapshot(values) {
  // SYNTHETIC snapshot bound like the backend's; not market data.
  const ids = ["m1", "m2"];
  const candles = ["2026-01-01T04:00:00Z", "2026-01-01T08:00:00Z"].map((close, index) => ({
    market_data_id: ids[index], close_time: close, metrics: { close: { value: values.close, unit: "USDT" } },
  }));
  const indicator = (indicatorId, parameters, value) => ({
    status: "AVAILABLE", reason_code: null,
    result: {
      indicator_id: indicatorId, parameters, snapshot_id: "s", quality_report_id: "q", instrument_id: "BTC-USDT-SPOT",
      venue_id: "BINANCE-SPOT", timeframe: "4h", as_of: "t", metadata_version: "1", calculation_version: "1",
      input_market_data_ids: ids, points: candles.map((candle) => ({ candle_end: candle.close_time, value })),
    },
  });
  return {
    snapshot_id: "s", instrument_id: "BTC-USDT-SPOT", venue_id: "BINANCE-SPOT", timeframe: "4h", as_of: "t",
    data_quality: { status: "VALID", report_status: "VALID", report_id: "q" },
    lineage: { market_data_ids: ids },
    candles,
    indicators: {
      "ema-20": indicator("ema", [["period", 20]], values.ema20),
      "ema-50": indicator("ema", [["period", 50]], values.ema50),
      "rsi-14": indicator("rsi", [["period", 14]], { status: "READY", value: values.rsi, reason: null }),
      "atr-14": indicator("atr-14", [["period", 14]], values.atr),
    },
  };
}

test("UR1: Plain reading describes backend values in words and says it is not a signal", () => {
  const reading = plainReading(syntheticSnapshot({ close: "110.00", ema20: "105.00", ema50: "100.00", rsi: "74.2", atr: "2.20" }));
  assert.deepEqual(reading.items.map((item) => item.text), [
    "Trend: up (price above EMA50, EMA20 above EMA50)",
    "Momentum: RSI 74.2 (above 70 = strong, overbought zone)",
    "Volatility: ATR 2.20 USDT (typical move per candle, 2.00% of price)",
  ]);
  assert.match(reading.note, /Not a signal/);
  assert.match(reading.items[0].exact, /EMA20 105\.00/);
  const down = plainReading(syntheticSnapshot({ close: "90.00", ema20: "95.00", ema50: "100.00", rsi: "25", atr: "1" }));
  assert.match(down.items[0].text, /^Trend: down/);
  assert.match(down.items[1].text, /below 30/);
  const stale = syntheticSnapshot({ close: "90.00", ema20: "95.00", ema50: "100.00", rsi: "25", atr: "1" });
  stale.indicators["ema-50"] = { status: "UNAVAILABLE", reason_code: "STALE_FOR_SERVING_CUTOFF", result: null };
  assert.equal(plainReading(stale).items[0].text, "Trend: unavailable — STALE_FOR_SERVING_CUTOFF");
  assert.deepEqual(plainReading(null).items, []);
});
