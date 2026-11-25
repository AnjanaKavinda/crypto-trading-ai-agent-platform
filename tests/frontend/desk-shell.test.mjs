import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  adjacentTab,
  DESK_TABS,
  summariseFreshness,
  tabFromHash,
} from "../../apps/web/src/desk-state.mjs";

// Synthetic watchlist results (labelled synthetic; not market data).
const syntheticRow = (quality, candleTime, temporalContext = "CURRENT") => ({
  row: { quality, candleTime, temporalContext },
});

test("desk has the four approved tabs, each folding in an existing page", async () => {
  assert.deepEqual(DESK_TABS.map((tab) => tab.label), ["Today", "Charts", "Strategy lab", "My results"]);
  for (const tab of DESK_TABS) {
    assert.match(tab.page, /^\.\/[a-z]+\.html$/);
    await readFile(new URL(`../../apps/web/${tab.page.slice(2)}`, import.meta.url));
  }
  const pages = new Set(DESK_TABS.map((tab) => tab.page));
  for (const page of ["./index.html", "./watchlist.html", "./evidence.html", "./signals.html"]) {
    assert.ok(pages.has(page), `${page} must stay reachable from the desk`);
  }
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

test("freshness summary reports backend quality only and fails closed", () => {
  const ok = summariseFreshness([
    syntheticRow("VALID", "2026-01-01T01:00:00Z"),
    syntheticRow("VALID", "2026-01-01T02:00:00Z"),
  ]);
  assert.equal(ok.state, "valid");
  assert.match(ok.text, /2 VALID — latest finalized candle 2026-01-01T02:00:00Z/);

  const stale = summariseFreshness([syntheticRow("VALID", "2026-01-01T01:00:00Z"), syntheticRow("STALE", "2026-01-01T00:00:00Z")]);
  assert.equal(stale.state, "warning");
  assert.match(stale.text, /1 VALID · 1 STALE/);

  const historical = summariseFreshness([syntheticRow("VALID", "2026-01-01T01:00:00Z", "HISTORICAL")]);
  assert.equal(historical.state, "warning");
  assert.match(historical.text, /1 historical/);

  const failed = summariseFreshness([syntheticRow("VALID", "2026-01-01T01:00:00Z"), { row: null, error: "x" }]);
  assert.equal(failed.state, "error");
  assert.match(failed.text, /1 unavailable/);

  assert.equal(summariseFreshness([]).state, "error");
  assert.equal(summariseFreshness(undefined).state, "error");
  assert.match(summariseFreshness([{ row: null }]).text, /no finalized candle/);
});

test("desk shell is read-only: no refresh, polling, storage or trading actions", async () => {
  const [html, script] = await Promise.all([
    readFile(new URL("../../apps/web/desk.html", import.meta.url), "utf8"),
    readFile(new URL("../../apps/web/src/desk-shell.mjs", import.meta.url), "utf8"),
  ]);
  assert.match(html, /Mode: RESEARCH/);
  assert.match(html, /Live trading: OFF/);
  assert.match(html, /role="tablist"/);
  assert.doesNotMatch(script, /refreshSnapshot|setInterval|WebSocket|localStorage|method:\s*["']POST/);
  assert.doesNotMatch(html + script, /https?:\/\//);
  for (const page of ["index.html", "watchlist.html", "evidence.html", "signals.html"]) {
    const source = await readFile(new URL(`../../apps/web/${page}`, import.meta.url), "utf8");
    assert.match(source, /href="\.\/desk\.html" target="_top"/);
  }
});
