import assert from "node:assert/strict";
import test from "node:test";
import { markerAnchors, markersBindingError, sizingInputs, tradeDetails, markerFieldDisplay } from "../../apps/web/src/strategy-markers.mjs";
import { readStrategyMarkers } from "../../apps/web/src/research-api.mjs";

const snapshot = { instrument_id: "BTC-USDT-SPOT", timeframe: "4h", snapshot_id: "s1" };

test("sizing inputs accept plain positive decimals only", () => {
  assert.deepEqual(sizingInputs("", ""), { ok: true, accountSize: null, riskPct: null });
  assert.deepEqual(sizingInputs("1000", "1.5"), { ok: true, accountSize: "1000", riskPct: "1.5" });
  for (const [account, risk] of [["0", "1"], ["1e3", "1"], ["1000", "0"], ["1000", "101"], ["1000", ""], ["-5", "1"]]) {
    assert.equal(sizingInputs(account, risk).ok, false, `${account}/${risk}`);
  }
});

test("markers must be bound to the loaded snapshot", () => {
  const response = { ...snapshot, status: "AVAILABLE", markers: [] };
  assert.equal(markersBindingError(response, snapshot), null);
  assert.match(markersBindingError({ ...response, snapshot_id: "other" }, snapshot), /snapshot_id/);
  assert.match(markersBindingError({ ...response, status: "UNAVAILABLE", markers: [{}] }, snapshot), /must not carry/);
  assert.match(markersBindingError(null, snapshot), /No strategy-marker/);
});

test("anchors use the fill candle when filled and the signal candle while pending (synthetic times)", () => {
  const times = ["2026-01-01T00:00:00Z", "2026-01-01T04:00:00Z", "2026-01-01T08:00:00Z"];
  const markers = [
    { side: "BUY", status: "FILLED", time: { value: times[0] }, fill_time: { value: times[1] } },
    { side: "BUY", status: "PENDING_FILL", time: { value: times[2] }, fill_time: { value: null } },
    { side: "SELL", status: "FILLED", time: { value: times[0] }, fill_time: { value: "2025-01-01T00:00:00Z" } },
  ];
  assert.deepEqual(markerAnchors(markers, times), [
    { markerIndex: 0, candleIndex: 1, side: "BUY", pending: false },
    { markerIndex: 1, candleIndex: 2, side: "BUY", pending: true },
  ]);
});

test("trade details keep every backend label and reason", () => {
  const rows = tradeDetails({
    modelled_entry_fill: { label: "RESEARCH_PROPOSAL", value: "101.05", reason: "slippage" },
    position_size: { quantity: { label: "UNAVAILABLE", value: null, reason: "enter account size and risk %" } },
    stop: { label: "INVENTED", value: "1" },
  });
  assert.deepEqual(rows, [
    { name: "Modelled entry fill", key: "modelled_entry_fill", label: "RESEARCH_PROPOSAL", value: "101.05", reason: "slippage" },
    { name: "Position size (quantity)", key: "quantity", label: "UNAVAILABLE", value: null, reason: "enter account size and risk %" },
  ]);
});

test("U5b: marker and evidence numbers use display precision and keep the exact value", () => {
  // Synthetic values; not market data.
  assert.deepEqual(markerFieldDisplay("modelled_entry_fill", "60618.7912345", 2), { text: "60,618.79", exact: "60618.7912345" });
  assert.deepEqual(markerFieldDisplay("stop", "0.94771234", 4), { text: "0.9477", exact: "0.94771234" });
  assert.deepEqual(markerFieldDisplay("net_return", "-0.012"), { text: "−1.20%", exact: "-0.012" });
  assert.deepEqual(markerFieldDisplay("net_return", "0.0345"), { text: "+3.45%", exact: "0.0345" });
  assert.deepEqual(markerFieldDisplay("r_multiple", "1.210131"), { text: "1.21 R", exact: "1.210131" });
  assert.deepEqual(markerFieldDisplay("quantity", "2.50000000"), { text: "2.5", exact: "2.50000000" });
  assert.deepEqual(markerFieldDisplay("notional_usdt", "261.1712"), { text: "261.17", exact: "261.1712" });
  assert.deepEqual(markerFieldDisplay("rsi_14", "28.0712", 2), { text: "28.07", exact: "28.0712" });
  assert.deepEqual(markerFieldDisplay("time", "2026-10-15T08:00:00Z"), { text: "2026-10-15 08:00 UTC", exact: "2026-10-15T08:00:00Z" });
  assert.deepEqual(markerFieldDisplay("stop", null), { text: "—", exact: null });
  assert.deepEqual(markerFieldDisplay("reason", "SIGNAL_EXIT"), { text: "SIGNAL_EXIT", exact: null });
});

test("UR5: markers requests always name the strategy and version", async () => {
  const urls = [];
  const fetcher = async (url) => { urls.push(url); return { ok: true, json: async () => ({}) }; };
  await readStrategyMarkers(fetcher, { instrumentId: "BTC-USDT-SPOT", timeframe: "4h", limit: 501, strategy: "range-reversion-4h", version: "1" });
  const query = new URL(urls[0]).searchParams;
  assert.equal(query.get("strategy"), "range-reversion-4h");
  assert.equal(query.get("version"), "1");
  assert.throws(() => readStrategyMarkers(fetcher, { instrumentId: "BTC-USDT-SPOT", timeframe: "4h", limit: 501 }), /registered strategy/);
  assert.throws(() => readStrategyMarkers(fetcher, { instrumentId: "BTC-USDT-SPOT", timeframe: "4h", limit: 501, strategy: "x&y", version: "1" }), /registered strategy/);
  assert.equal(urls.length, 1);
  // An API without this strategy's markers says so (allowlisted code only).
  const missing = async () => ({ ok: false, status: 422, json: async () => ({ code: "STRATEGY_NOT_REGISTERED", detail: "PRIVATE" }) });
  await assert.rejects(
    readStrategyMarkers(missing, { instrumentId: "BTC-USDT-SPOT", timeframe: "4h", limit: 501, strategy: "range-reversion-4h", version: "1" }),
    (error) => /no markers registered for this strategy version/.test(error.message) && !/PRIVATE/.test(error.message),
  );
});
