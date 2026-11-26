import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import { STRATEGY_STUDIES, studyLine, todayState } from "../../apps/web/src/today-state.mjs";
import { loadToday } from "../../apps/web/src/today.mjs";
import { APPROVED_INSTRUMENTS } from "../../apps/web/src/watchlist-state.mjs";

// SYNTHETIC row shaped like watchlistRow() output; not market data.
const row = (overrides = {}) => ({
  instrumentId: "BTC-USDT-SPOT",
  close: "101.00",
  priceUnit: "USDT",
  candleTime: "2026-10-09T16:00:00Z",
  asOf: "2026-10-09T16:00:01Z",
  freshnessCutoff: "2026-10-09T20:00:00Z",
  quality: "VALID",
  temporalContext: "CURRENT",
  ...overrides,
});

test("every coin is NO_TRADE with the recorded study verdicts while no strategy has passed", () => {
  const result = todayState({ symbol: "BTCUSDT", row: row(), error: null });
  assert.equal(result.decision, "NO_TRADE");
  assert.equal(result.data, "VALID");
  assert.equal(result.price, "101.00 USDT");
  assert.match(result.freshness, /freshness cutoff 2026-10-09T20:00:00Z/);
  assert.equal(result.reasons[0], "No strategy has passed its study.");
  assert.ok(result.reasons.includes(studyLine(STRATEGY_STUDIES[0])));
  assert.match(studyLine(STRATEGY_STUDIES[0]), /ema-trend-atr-stop v1.*FAIL \(2026-11-26\).*DOES_NOT_BEAT_CASH/);
  assert.ok(result.reasons.every((reason) => !/BUY|SELL/.test(reason)));
});

test("invalid or missing data is shown but still NO_TRADE", () => {
  const stale = todayState({ symbol: "SOLUSDT", row: row({ quality: "STALE" }), error: null });
  assert.equal(stale.decision, "NO_TRADE");
  assert.equal(stale.data, "STALE");
  assert.equal(stale.tone, "warning");
  assert.match(stale.reasons[0], /Data quality STALE/);

  const missing = todayState({ symbol: "BNBUSDT", row: null, error: "The local research API is unreachable." });
  assert.equal(missing.decision, "NO_TRADE");
  assert.equal(missing.data, "UNAVAILABLE");
  assert.equal(missing.price, null);
  assert.match(missing.reasons[0], /unreachable/);
});

test("a passed study without a connected signal source still fails closed to NO_TRADE", () => {
  const studies = [{ strategy: "synthetic", version: "1", protocol: "p", verdict: "PASS", recordedOn: null, reasons: [] }];
  const result = todayState({ symbol: "BTCUSDT", row: row(), error: null }, studies);
  assert.equal(result.decision, "NO_TRADE");
  assert.match(result.reasons[0], /no signal source is connected/);
});

function fakeDocument() {
  const make = (tag) => {
    const node = {
      tagName: tag, children: [], dataset: {}, textContent: "", className: "", href: "",
      append(...items) { node.children.push(...items); },
      replaceChildren(...items) { node.children = items; },
    };
    return node;
  };
  const nodes = { "#today-rows": make("ul"), "#today-status": make("p") };
  return { nodes, createElement: make, querySelector: (selector) => nodes[selector] ?? null };
}

const text = (node) => [node.textContent, ...node.children.map(text)].join(" ");
const find = (node, predicate) =>
  predicate(node) ? node : node.children.map((child) => find(child, predicate)).find(Boolean);

test("Today reads only 4h snapshots (no strategy markers) and links each coin to its decision panel", async () => {
  const calls = [];
  const fetcher = async (url) => {
    calls.push(url);
    if (url.endsWith("/symbols")) {
      return { ok: true, json: async () => ({
        provider: "binance-spot-public",
        redistribution: "NOT_AUTHORIZED",
        instruments: Object.entries(APPROVED_INSTRUMENTS).map(([instrument_id, symbol]) => ({
          instrument_id, symbol, venue_id: "BINANCE-SPOT", eligibility: "CHECKED_ON_EACH_REFRESH",
        })),
      }) };
    }
    return { ok: false, status: 503, json: async () => ({}) };
  };
  const document = fakeDocument();
  await loadToday(document, fetcher);
  const rows = document.nodes["#today-rows"].children;
  assert.equal(rows.length, 5);
  assert.ok(calls.every((url) => !url.includes("strategy-markers") && !url.includes("/refresh")));
  assert.ok(calls.slice(1).every((url) => new URL(url).searchParams.get("timeframe") === "4h"));
  assert.match(text(rows[0]), /BTCUSDT NO_TRADE/);
  const link = find(rows[0], (node) => node.tagName === "a");
  assert.equal(link.href, "./index.html?instrument=BTC-USDT-SPOT&timeframe=4h#decision-panel");
  assert.match(document.nodes["#today-status"].textContent, /NO_TRADE until a strategy passes its study/);
});

test("the Today panel is on the overview page and states research-only NO_TRADE", async () => {
  const html = await readFile(new URL("../../apps/web/watchlist.html", import.meta.url), "utf8");
  assert.match(html, /<script type="module" src="\.\/src\/today\.mjs"><\/script>/);
  assert.match(html, /id="today-rows"/);
  assert.match(html, /NO_TRADE until a strategy passes its study/);
});
