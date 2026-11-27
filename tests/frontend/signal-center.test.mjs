import assert from "node:assert/strict";
import test from "node:test";
import { readForwardStage } from "../../apps/web/src/forward-api.mjs";
import {
  coinSignal, FORWARD_CANDIDATES, forwardRecordError, GLOSSARY, positionSize, WHAT_COULD_GO_WRONG,
} from "../../apps/web/src/signal-center-state.mjs";

// SYNTHETIC forward records shaped like GET /api/research/forward/{strategy}; not market data.
const [trend, range] = FORWARD_CANDIDATES;
const record = (candidate, stage, reason, signals = {}) => ({
  label: "SIMULATED RESEARCH EVIDENCE - NOT AN ORDER",
  strategy: { strategy_id: candidate.strategy, version: Number(candidate.version), content_sha256: "a".repeat(64) },
  protocol: { prospective_start: "2026-11-26T00:00:00Z" },
  signals: { BTCUSDT: [], ...signals },
  stage, reason,
  forward: { label: "SIMULATED", closed_trades: 0, win_rate: null, expectancy: null, max_drawdown: "0", review_point: { trades: 15, date: "2027-05-26T00:00:00Z", reached: false } },
  authority: { qualification_authorized: false, approval_authorized: false, execution_authorized: false },
});
const openSignal = {
  status: "OPEN", signal_candle_open_time: "2026-12-01T00:00:00Z",
  simulated_entry_fill: { label: "SIMULATED", value: "100.00" }, simulated_initial_stop: { label: "SIMULATED", value: "95.00" },
};

test("U5c: today's FAIL records give every coin 🔴 with the reason; Beginner never names the failed strategy", () => {
  const stages = [
    { candidate: trend, record: record(trend, "FAIL", "HISTORICAL_FAIL"), error: null },
    { candidate: range, record: null, error: "The API could not build this forward record from the stored snapshots. [FORWARD_SNAPSHOT_NOT_VALID]" },
  ];
  const beginner = coinSignal("BTCUSDT", stages, "beginner");
  assert.equal(beginner.state, "red");
  assert.equal(beginner.title, "No signal — stay out");
  assert.match(beginner.reasons.join(" "), /No strategy has passed its study/);
  assert.match(beginner.reasons.join(" "), /fails closed to no signal/);
  assert.doesNotMatch(beginner.reasons.join(" "), /trend-daily-regime/);
  const pro = coinSignal("BTCUSDT", stages, "pro");
  assert.match(pro.reasons.join(" "), /trend-daily-regime v1 failed its historical study/);
  assert.match(pro.reasons.join(" "), /range-reversion-4h v1: forward record unavailable — .*FORWARD_SNAPSHOT_NOT_VALID/);
  assert.equal(pro.signal, null);
});

test("U5c: 🟡 only from FORWARD_TESTING, 🟢 only from FORWARD_PASS with a live signal for that coin", () => {
  const testing = coinSignal("BTCUSDT", [{ candidate: trend, record: record(trend, "FORWARD_TESTING", "REVIEW_POINT_NOT_REACHED"), error: null }]);
  assert.equal(testing.state, "yellow");
  assert.equal(testing.title, "Forward-testing — paper only");
  const passNoSignal = coinSignal("BTCUSDT", [{ candidate: trend, record: record(trend, "FORWARD_PASS", "PREREGISTERED_FORWARD_CRITERIA_MET"), error: null }]);
  assert.equal(passNoSignal.state, "red");
  const pass = coinSignal("BTCUSDT", [{ candidate: trend, record: record(trend, "FORWARD_PASS", "PREREGISTERED_FORWARD_CRITERIA_MET", { BTCUSDT: [openSignal] }), error: null }]);
  assert.equal(pass.state, "green");
  assert.equal(pass.signal, openSignal);
  // A record claiming authority or of the wrong strategy is refused (fail closed).
  assert.match(forwardRecordError({ ...record(trend, "FORWARD_PASS", "x"), authority: { execution_authorized: true } }, trend), /authority/);
  assert.match(forwardRecordError(record(range, "FAIL", "HISTORICAL_FAIL"), trend), /another strategy/);
  assert.equal(forwardRecordError(record(trend, "FAIL", "HISTORICAL_FAIL"), trend), null);
});

test("U5c: position size uses exact decimals, default 1% risk, capped at what the account can buy", () => {
  assert.deepEqual(positionSize({ account: "1000", riskPct: "1", entry: "100.00", stop: "95.00" }),
    { ok: true, quantity: "2.00000000", riskAmount: "10.00", capped: false });
  assert.deepEqual(positionSize({ account: "1000", riskPct: "10", entry: "100", stop: "99.9" }),
    { ok: true, quantity: "10.00000000", riskAmount: "100.00", capped: true });
  assert.deepEqual(positionSize({ account: "1000", riskPct: "1", entry: "0.3", stop: "0.1" }),
    { ok: true, quantity: "50.00000000", riskAmount: "10.00", capped: false });
  assert.match(positionSize({ account: "", riskPct: "1", entry: "100", stop: "95" }).reason, /account size/);
  assert.match(positionSize({ account: "1000", riskPct: "0", entry: "100", stop: "95" }).reason, /Risk per trade/);
  assert.match(positionSize({ account: "1000", riskPct: "1", entry: "100", stop: "101" }).reason, /not below the entry/);
});

test("U5c: plain-language risks for every state and a glossary entry for every term", () => {
  for (const state of ["red", "yellow", "green"]) assert.ok(WHAT_COULD_GO_WRONG[state].length >= 2, state);
  for (const name of ["Forward testing", "Simulated", "Expectancy", "Win rate", "Max drawdown", "Stop", "Position size", "Risk %", "Review point"]) {
    assert.ok(GLOSSARY[name]?.length > 20, name);
  }
});

test("U5c: forward reads are GET-only with an allowlisted problem code", async () => {
  const calls = [];
  const fetcher = async (url, options) => {
    calls.push({ url, method: options.method });
    return { ok: false, status: 422, json: async () => ({ code: "FORWARD_SNAPSHOT_NOT_VALID", detail: "PRIVATE" }) };
  };
  await assert.rejects(readForwardStage(fetcher, "trend-daily-regime", "1"),
    (error) => /\[FORWARD_SNAPSHOT_NOT_VALID\]/.test(error.message) && !/PRIVATE/.test(error.message));
  assert.match(calls[0].url, /\/api\/research\/forward\/trend-daily-regime\?version=1$/);
  assert.equal(calls[0].method, "GET");
  await assert.rejects(readForwardStage(fetcher, "../x", "1"), /registered forward strategy/);
  assert.equal(calls.length, 1);
});
