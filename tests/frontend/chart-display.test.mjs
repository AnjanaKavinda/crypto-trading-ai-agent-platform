import assert from "node:assert/strict";
import test from "node:test";
import { closePath, normaliseToolbarPreferences } from "../../apps/web/src/chart-display.mjs";
import { normalisePreferences } from "../../apps/web/src/workspace-state.mjs";

test("display preferences migrate old values and reject unsupported styles, intervals and widths", () => {
  const prefs = normalisePreferences({ mode: "pro", visible: ["ema-20"], chartStyle: "footprint", favoriteStyles: ["line", "line", "renko"],
    favoriteTimeframes: ["1m", "4h", "1s", "1d"], favoriteTools: ["cvd", "vwap"], studyWidths: { "ema-20": 3, "rsi-14": -1, html: "bad" } });
  assert.equal(prefs.chartStyle, "candles");
  assert.deepEqual(prefs.favoriteStyles, ["line"]);
  assert.deepEqual(prefs.favoriteTimeframes, ["4h", "1d"]);
  assert.deepEqual(prefs.favoriteTools, ["vwap"]);
  assert.deepEqual(prefs.studyWidths, { "ema-20": 3 });
  assert.equal(prefs.mode, "pro");
  assert.deepEqual(prefs.visible, ["ema-20"]);
  assert.equal(normaliseToolbarPreferences().volume, true);
  assert.deepEqual(normalisePreferences(null).favoriteStyles, []);
});

test("line and step line use closes; the step holds the prior close until the next timestamp", () => {
  // SYNTHETIC geometry, not market observations.
  const candles = [3, 7, 4].map((close) => ({ values: { open: { numeric: 99 }, close: { numeric: close } } }));
  assert.equal(closePath(candles, (i) => i * 10, (v) => 20 - v), "M 0 17 L 10 13 L 20 16");
  assert.equal(closePath(candles, (i) => i * 10, (v) => 20 - v, true), "M 0 17 H 10 V 13 H 20 V 16");
});
