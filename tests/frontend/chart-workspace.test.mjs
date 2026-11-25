import assert from "node:assert/strict";
import test from "node:test";
import {
  axisTimeLabel,
  CHART_TIMEFRAME_PILLS,
  lastPriceTag,
  normaliseChartWindow,
  panChartWindow,
  priceScale,
  timeAxisIndexes,
  volumeReferenceLine,
  zoomChartWindow,
} from "../../apps/web/src/chart-interaction.mjs";

test("default chart window shows every returned candle", () => {
  assert.deepEqual(normaliseChartWindow(null, 250), { start: 0, count: 250 });
  assert.deepEqual(normaliseChartWindow({ start: 900, count: 3 }, 250), { start: 240, count: 10 });
  assert.deepEqual(normaliseChartWindow(null, 4), { start: 0, count: 4 });
  assert.equal(normaliseChartWindow(null, 0), null);
});

test("zoom keeps the anchor and stays within the returned candles", () => {
  assert.deepEqual(zoomChartWindow(null, 0.5, 200), { start: 100, count: 100 });
  assert.deepEqual(zoomChartWindow(null, 0.5, 200, 0), { start: 0, count: 100 });
  assert.deepEqual(zoomChartWindow({ start: 50, count: 100 }, 2, 200), { start: 0, count: 200 });
  assert.deepEqual(zoomChartWindow({ start: 0, count: 10 }, 0.5, 200), { start: 0, count: 10 });
});

test("pan moves the window without leaving the returned range", () => {
  assert.deepEqual(panChartWindow({ start: 100, count: 50 }, -30, 200), { start: 70, count: 50 });
  assert.deepEqual(panChartWindow({ start: 100, count: 50 }, 500, 200), { start: 150, count: 50 });
  assert.deepEqual(panChartWindow({ start: 10, count: 50 }, -500, 200), { start: 0, count: 50 });
});

test("auto scale is linear and percent ticks are labelled from the base close", () => {
  const auto = priceScale({ minimum: 100, maximum: 200 });
  assert.equal(auto.mode, "auto");
  assert.equal(auto.fractionOf(200), 0);
  assert.equal(auto.fractionOf(150), 0.5);
  assert.deepEqual(auto.ticks.map((tick) => tick.value), [200, 175, 150, 125, 100]);
  const percent = priceScale({ minimum: 100, maximum: 200, mode: "percent", base: 100 });
  assert.deepEqual(percent.ticks.map((tick) => tick.label), ["+100.00%", "+75.00%", "+50.00%", "+25.00%", "+0.00%"]);
});

test("log scale spaces decades evenly and fails back to auto for non-positive values", () => {
  const log = priceScale({ minimum: 10, maximum: 1000, mode: "log" });
  assert.equal(log.mode, "log");
  assert.equal(log.fractionOf(100), 0.5);
  assert.equal(log.fractionOf(-1), null);
  const fallback = priceScale({ minimum: -5, maximum: 10, mode: "log" });
  assert.equal(fallback.mode, "auto");
  assert.match(fallback.reason, /above zero/);
  assert.equal(priceScale({ minimum: 5, maximum: 5 }), null);
});

test("time axis indexes cover both ends and the UTC label depends on timeframe", () => {
  assert.deepEqual(timeAxisIndexes(101, 4), [0, 25, 50, 75, 100]);
  assert.deepEqual(timeAxisIndexes(3, 5), [0, 1, 2]);
  assert.deepEqual(timeAxisIndexes(1), [0]);
  assert.equal(axisTimeLabel("2026-11-25T04:00:00Z", "4h"), "11-25 04:00");
  assert.equal(axisTimeLabel("2026-11-25T00:00:00Z", "1d"), "2026-11-25");
  assert.equal(axisTimeLabel("not a time", "1h"), "");
});

test("last-price tag uses the exact returned close and its direction", () => {
  const candle = (open, close) => ({
    values: { open: { numeric: Number(open) }, close: { exact: close, numeric: Number(close) } },
  });
  assert.deepEqual(lastPriceTag(candle("10", "9.50"), candle("9", "10.00")), { text: "9.50", value: 9.5, direction: "down" });
  assert.deepEqual(lastPriceTag(candle("9", "9.50")), { text: "9.50", value: 9.5, direction: "up" });
  assert.equal(lastPriceTag({ values: { close: { numeric: 1 } } }), null);
});

test("timeframe pills keep only 1h/4h/1d live and give reasons for the rest", () => {
  assert.deepEqual(CHART_TIMEFRAME_PILLS.filter((pill) => pill.live).map((pill) => pill.value), ["1h", "4h", "1d"]);
  for (const pill of CHART_TIMEFRAME_PILLS.filter((item) => !item.live)) assert.match(pill.reason, /not served/);
});

test("volume reference line uses only READY backend trailing averages (synthetic values)", () => {
  const analysis = {
    status: "PARTIAL",
    result: {
      lookback: 20,
      points: [
        { candle_end: "2026-01-01T00:01:00Z", status: "UNAVAILABLE", trailing_average: null },
        { candle_end: "2026-01-01T00:02:00Z", status: "READY", trailing_average: "1.5000" },
        { candle_end: "2026-01-01T00:03:00Z", status: "READY", trailing_average: "2.25" },
        { candle_end: "2026-01-01T00:04:00Z", status: "READY", trailing_average: "NaN" },
      ],
    },
  };
  assert.deepEqual(volumeReferenceLine(analysis), {
    lookback: 20,
    points: [
      { candleEnd: "2026-01-01T00:02:00Z", value: "1.5000" },
      { candleEnd: "2026-01-01T00:03:00Z", value: "2.25" },
    ],
  });
  assert.equal(volumeReferenceLine({ ...analysis, status: "UNAVAILABLE" }), null);
  assert.equal(volumeReferenceLine({ status: "AVAILABLE", result: { lookback: "20", points: analysis.result.points } }), null);
  assert.equal(volumeReferenceLine(undefined), null);
});
