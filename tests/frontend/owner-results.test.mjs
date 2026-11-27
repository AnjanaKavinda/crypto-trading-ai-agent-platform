import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  percent,
  readOwnerScore,
  renderOwnerResults,
  SCORE_PATH,
  validateScore,
} from "../../apps/web/src/owner-results.mjs";

// Synthetic score response (labelled synthetic; not market data or real results).
function syntheticScore(changes = {}) {
  return {
    protocol: { protocol_id: "owner-results", version: 1, min_trades: 30, max_drawdown: "0.30",
      min_profit_factor: "1.20", no_trade_horizon_days: 7, baselines: ["CASH", "BUY_AND_HOLD"] },
    protocol_sha256: "a".repeat(64),
    verdict: { status: "INCONCLUSIVE", reasons: ["INSUFFICIENT_SAMPLE: 2 closed trades < 30"] },
    trades: {
      counted: 2, wins: 1, win_rate: "0.5", expectancy: "0.0123456", profit_factor: "1.5",
      total_return: "0.02", max_drawdown: "0.01", net_result_usdt: "12.3456",
      bootstrap_lower_bound: null,
      items: [{ outcome_id: "o-1", instrument_id: "BTCUSDT", first_fill_at: "2026-01-01T00:00:00+00:00",
        net_return: "0.03", net_result_usdt: "15", net_result_basis: "STATEMENT",
        decision_recorded_before_first_fill: true }],
      excluded: [{ outcome_id: "o-3", reason: "FEE_UNKNOWN" }],
    },
    baselines: {
      CASH: { status: "AVAILABLE", total_return: "0" },
      BUY_AND_HOLD: { status: "AVAILABLE", basis: "equal-weight hold of each traded coin, first entry to last exit",
        total_return: "0.05", coins: [{ instrument_id: "BTCUSDT", start: "s", end: "e", status: "AVAILABLE", hold_return: "0.05" }] },
    },
    no_trade_decisions: { status: "AVAILABLE", horizon_days: 7, decisions: 2, evaluated: 1,
      standing_aside_better: 1, average_hold_return: "-0.04",
      items: [
        { entry_id: "j-1", instrument_id: "ETHUSDT", declared_at: "d1", horizon_end: "h1", status: "AVAILABLE", hold_return: "-0.04", standing_aside_better: true },
        { entry_id: "j-2", instrument_id: "SOLUSDT", declared_at: "d2", horizon_end: "h2", status: "PENDING" },
      ] },
    trade_facts_verified: false,
    execution_authorized: false,
    ...changes,
  };
}

class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.textContent = ""; this.title = ""; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
}
const document = { createElement: (tag) => new Node(tag) };
const flatten = (node) => [node, ...node.children.flatMap(flatten)];
const texts = (node) => flatten(node).map((n) => n.textContent).join("\n");

test("score validation fails closed on authority, verdict or number tampering", () => {
  assert.equal(validateScore(syntheticScore()).verdict.status, "INCONCLUSIVE");
  for (const changes of [
    { execution_authorized: true },
    { trade_facts_verified: true },
    { verdict: { status: "PROFITABLE", reasons: [] } },
    { protocol_sha256: "x" },
    { trades: { ...syntheticScore().trades, expectancy: 0.01 } },
    { baselines: { CASH: { status: "AVAILABLE", total_return: "0" } } },
  ]) assert.throws(() => validateScore(syntheticScore(changes)), /No score is displayed/);
});

test("renders verdict, trades vs baselines and NO_TRADE comparison with exact values on hover", () => {
  const parent = new Node("div");
  renderOwnerResults(document, parent, syntheticScore());
  const text = texts(parent);
  assert.match(text, /Verdict: INCONCLUSIVE/);
  assert.match(text, /INSUFFICIENT_SAMPLE: 2 closed trades < 30/);
  assert.match(text, /Closed trades counted: 2 of 30 required/);
  assert.match(text, /Expectancy per trade: 1\.23%/);
  assert.match(text, /Net result: 12\.35 USDT/);
  assert.match(text, /Excluded o-3: FEE_UNKNOWN/);
  assert.match(text, /Buy-and-hold: 5\.00%/);
  assert.match(text, /did not beat buy-and-hold/);
  assert.match(text, /Standing aside was better: 1 of 1/);
  assert.match(text, /SOLUSDT · d2: PENDING until h2/);
  const expectancy = flatten(parent).find((n) => n.textContent.startsWith("Expectancy"));
  assert.equal(expectancy.title, "Exact backend value: 0.0123456");
});

test("unavailable baselines and empty history are stated, never filled in", () => {
  const parent = new Node("div");
  const score = syntheticScore({
    verdict: { status: "INCONCLUSIVE", reasons: [] },
    trades: { ...syntheticScore().trades, counted: 0, win_rate: null, expectancy: null, profit_factor: null,
      total_return: null, max_drawdown: null, net_result_usdt: null, items: [], excluded: [] },
    baselines: { CASH: { status: "AVAILABLE", total_return: "0" },
      BUY_AND_HOLD: { status: "UNAVAILABLE", reason: "No counted trades.", coins: [] } },
    no_trade_decisions: { status: "UNAVAILABLE", horizon_days: 7, decisions: 0, evaluated: 0, items: [] },
  });
  renderOwnerResults(document, parent, score);
  const text = texts(parent);
  assert.match(text, /Expectancy per trade: unavailable/);
  assert.match(text, /Buy-and-hold: UNAVAILABLE — No counted trades\./);
  assert.match(text, /No closed trades with a known net result/);
  assert.match(text, /No NO_TRADE decision has completed its horizon yet/);
  assert.doesNotMatch(text, /beat buy-and-hold/);
  assert.equal(percent(null), "unavailable");
});

test("reads with one GET and reports API failure without showing a score", async () => {
  const calls = [];
  const score = await readOwnerScore(async (url, options) => {
    calls.push({ url, options });
    return { ok: true, json: async () => syntheticScore() };
  });
  assert.equal(score.verdict.status, "INCONCLUSIVE");
  assert.equal(calls.length, 1);
  assert.ok(calls[0].url.endsWith(SCORE_PATH));
  assert.equal(calls[0].options.method, "GET");
  await assert.rejects(readOwnerScore(async () => ({ ok: false, status: 503 })), /could not score/);
  await assert.rejects(readOwnerScore(async () => { throw new TypeError("offline"); }), /unavailable/);
});

test("the My results tab hosts the scorecard and the module stays read-only", async () => {
  const [html, script, shell] = await Promise.all([
    readFile(new URL("../../apps/web/index.html", import.meta.url), "utf8"),
    readFile(new URL("../../apps/web/src/owner-results.mjs", import.meta.url), "utf8"),
    readFile(new URL("../../apps/web/src/desk-shell.mjs", import.meta.url), "utf8"),
  ]);
  assert.match(html, /id="panel-my-results"[\s\S]*id="results-body"/);
  assert.match(shell, /import\("\.\/owner-results\.mjs"\)/);
  assert.doesNotMatch(script, /method:\s*["']POST|setInterval|WebSocket|localStorage|innerHTML/);
});
