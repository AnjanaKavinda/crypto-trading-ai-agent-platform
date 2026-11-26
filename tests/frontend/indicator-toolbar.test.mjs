import assert from "node:assert/strict";
import test from "node:test";
import { TOOLBAR_PILLS, toolbarPills } from "../../apps/web/src/indicator-toolbar.mjs";
import { INDICATOR_IDS, SPOT_ANALYSIS_IDS } from "../../apps/web/src/workspace-state.mjs";

const all = () => ({ available: true });

test("every toggle pill maps to a supported indicator and every jump pill to a spot analysis", () => {
  for (const pill of TOOLBAR_PILLS) {
    if (pill.kind === "indicator") assert.ok(INDICATOR_IDS.includes(pill.id), pill.id);
    if (pill.kind === "analysis") assert.ok(SPOT_ANALYSIS_IDS.includes(pill.id), pill.id);
    if (!pill.kind) assert.ok(pill.status, pill.short);
  }
  for (const id of INDICATOR_IDS) assert.ok(TOOLBAR_PILLS.some((pill) => pill.id === id), id);
});

test("live pills toggle and reflect the enabled set; not-ready pills are disabled with reasons", () => {
  const pills = toolbarPills({ snapshotLoaded: true, enabled: ["ema-20"], availability: all });
  const by = Object.fromEntries(pills.map((pill) => [pill.short, pill]));
  assert.deepEqual(by.EMA20.action, { type: "toggle", id: "ema-20" });
  assert.equal(by.EMA20.pressed, "true");
  assert.equal(by.RSI.pressed, "false");
  assert.deepEqual(by.VWAP.action, { type: "jump", id: "vwap" });
  assert.deepEqual(by.SIGNALS.action, { type: "jump", id: "strategy-markers" });
  assert.equal(by.VOL.live, true);
  assert.equal(by.VOL.action, null);
  for (const [short, badge, pattern] of [
    ["SMA", "Connect", /not yet sent/], ["OBV", "To build", /not implemented/],
    ["CVD", "Needs trades", /#355/], ["HEAT", "Needs order book", /#355/],
  ]) {
    assert.equal(by[short].live, false);
    assert.equal(by[short].action, null);
    assert.equal(by[short].badge, badge);
    assert.match(by[short].reason, pattern);
  }
  // Colour is by group.
  assert.equal(by.EMA20.color, by.VWAP.color);
  assert.notEqual(by.EMA20.color, by.RSI.color);
});

test("backend-unavailable or unloaded results never become live pills", () => {
  const pills = toolbarPills({
    snapshotLoaded: true,
    availability: (kind, id) => id === "rsi-14" ? { available: false, reason: "INSUFFICIENT_HISTORY" } : { available: true },
  });
  const rsi = pills.find((pill) => pill.short === "RSI");
  assert.equal(rsi.live, false);
  assert.equal(rsi.action, null);
  assert.match(rsi.reason, /INSUFFICIENT_HISTORY/);
  assert.ok(toolbarPills({ snapshotLoaded: false, availability: all }).every((pill) => pill.action === null));
});
