import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  adjacentTab,
  DESK_TABS,
  DESK_TIMEFRAMES,
  deskSelection,
  saveSelection,
  SELECTION_KEY,
  summariseFreshness,
  tabFromHash,
} from "../../apps/web/src/desk-state.mjs";
import { legacyTarget } from "../../apps/web/src/legacy-redirect.mjs";

// Synthetic watchlist results (labelled synthetic; not market data).
const syntheticRow = (quality, candleTime, temporalContext = "CURRENT", asOf = candleTime) => ({
  row: { quality, candleTime, temporalContext, asOf },
});
const symbols = [
  { instrument_id: "BTC-USDT-SPOT", symbol: "BTCUSDT" },
  { instrument_id: "ETH-USDT-SPOT", symbol: "ETHUSDT" },
];
const memoryStorage = () => {
  const values = new Map();
  return { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
};

test("UR1: one page with the four approved tabs; old pages redirect to their tab", async () => {
  assert.deepEqual(DESK_TABS.map((tab) => tab.label), ["Today", "Charts", "Strategy lab", "My results"]);
  const html = await readFile(new URL("../../apps/web/index.html", import.meta.url), "utf8");
  for (const tab of DESK_TABS) {
    assert.match(html, new RegExp(`id="tab-${tab.id}"[^>]*role|role="tab" id="tab-${tab.id}"`));
    assert.match(html, new RegExp(`id="panel-${tab.id}"`));
  }
  assert.doesNotMatch(html, /<iframe/);
  for (const [page, tab] of [["desk", "today"], ["watchlist", "today"], ["evidence", "strategy-lab"], ["signals", "my-results"]]) {
    const source = await readFile(new URL(`../../apps/web/${page}.html`, import.meta.url), "utf8");
    assert.match(source, new RegExp(`data-desk-tab="${tab}"`), page);
    assert.match(source, /src="\.\/src\/legacy-redirect\.mjs"/, page);
  }
  // Deep links keep their query and open the matching tab.
  assert.equal(legacyTarget("strategy-lab", "?package_id=x", ""), "./index.html?package_id=x#strategy-lab");
  assert.equal(legacyTarget("today", "", "#charts"), "./index.html#charts");
  assert.equal(legacyTarget("today", "", "#javascript:alert(1)"), "./index.html#today");
});

test("UR1: header shows Mode RESEARCH, Live trading OFF and one 1h/4h/1D timeframe set", async () => {
  const html = await readFile(new URL("../../apps/web/index.html", import.meta.url), "utf8");
  assert.match(html, /Mode: RESEARCH/);
  assert.match(html, /Live trading: OFF/);
  assert.match(html, /role="tablist"/);
  assert.deepEqual([...DESK_TIMEFRAMES], ["1h", "4h", "1d"]);
  assert.doesNotMatch(html, /1 minute|id="timeframe-select"|id="instrument-select"/);
  assert.doesNotMatch(html, /\[(price|value|n|id|result)\]/, "no placeholder text ships");
});

test("hash routing accepts only known tabs and keyboard navigation wraps", () => {
  assert.equal(tabFromHash("#charts"), "charts");
  assert.equal(tabFromHash("#javascript:alert(1)"), "today");
  assert.equal(tabFromHash(""), "today");
  assert.equal(adjacentTab("today", "ArrowLeft"), "my-results");
  assert.equal(adjacentTab("my-results", "ArrowRight"), "today");
  assert.equal(adjacentTab("charts", "Home"), "today");
  assert.equal(adjacentTab("charts", "End"), "my-results");
});

test("UR3: selected coin and timeframe persist; a valid deep link wins; junk is ignored", () => {
  const storage = memoryStorage();
  assert.deepEqual(deskSelection({ storage, symbols }), { instrumentId: "BTC-USDT-SPOT", timeframe: "4h" });
  saveSelection(storage, { instrumentId: "ETH-USDT-SPOT", timeframe: "1d" });
  assert.deepEqual(deskSelection({ storage, symbols }), { instrumentId: "ETH-USDT-SPOT", timeframe: "1d" });
  assert.deepEqual(deskSelection({ search: "?instrument=BTC-USDT-SPOT&timeframe=1h", storage, symbols }),
    { instrumentId: "BTC-USDT-SPOT", timeframe: "1h" });
  assert.deepEqual(deskSelection({ search: "?instrument=https%3A%2F%2Fexample.invalid&timeframe=1m", storage, symbols }),
    { instrumentId: "ETH-USDT-SPOT", timeframe: "1d" });
  storage.setItem(SELECTION_KEY, "{not json");
  assert.deepEqual(deskSelection({ storage, symbols }), { instrumentId: "BTC-USDT-SPOT", timeframe: "4h" });
});

test("freshness chip reports backend quality and the last refresh time, failing closed", () => {
  const ok = summariseFreshness([
    syntheticRow("VALID", "2026-01-01T01:00:00Z", "CURRENT", "2026-01-01T01:00:05Z"),
    syntheticRow("VALID", "2026-01-01T02:00:00Z", "CURRENT", "2026-01-01T02:00:07Z"),
  ], "4h");
  assert.equal(ok.state, "valid");
  assert.equal(ok.text, "Data: fresh · 4h · 2026-01-01 02:00 UTC");
  assert.match(ok.title, /2 VALID — latest finalized candle 2026-01-01T02:00:00Z/);

  const stale = summariseFreshness([syntheticRow("VALID", "2026-01-01T01:00:00Z"), syntheticRow("STALE", "2026-01-01T00:00:00Z")], "1d");
  assert.equal(stale.state, "warning");
  assert.match(stale.text, /^Data: stale · 1D/);
  assert.match(stale.title, /1 VALID · 1 STALE/);

  const historical = summariseFreshness([syntheticRow("VALID", "2026-01-01T01:00:00Z", "HISTORICAL")], "4h");
  assert.equal(historical.state, "warning");
  assert.match(historical.title, /1 historical/);

  const failed = summariseFreshness([syntheticRow("VALID", "2026-01-01T01:00:00Z"), { row: null, error: "x" }], "4h");
  assert.equal(failed.state, "error");
  assert.match(failed.text, /incomplete/);
  assert.match(failed.title, /1 unavailable/);

  assert.equal(summariseFreshness([], "4h").state, "error");
  assert.equal(summariseFreshness(undefined, "4h").text, "Data: unavailable · 4h");
  assert.match(summariseFreshness([{ row: null }], "4h").text, /unavailable/);
});

test("desk shell is read-only: no refresh, polling or trading actions", async () => {
  const [shell, data] = await Promise.all([
    readFile(new URL("../../apps/web/src/desk-shell.mjs", import.meta.url), "utf8"),
    readFile(new URL("../../apps/web/src/desk-data.mjs", import.meta.url), "utf8"),
  ]);
  for (const source of [shell, data]) {
    assert.doesNotMatch(source, /refreshSnapshot|setInterval|WebSocket|method:\s*["']POST/);
    assert.doesNotMatch(source, /https?:\/\//);
  }
});
