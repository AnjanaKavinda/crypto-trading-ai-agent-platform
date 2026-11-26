import assert from "node:assert/strict";
import test from "node:test";
import { markerAnchors, markersBindingError, sizingInputs, tradeDetails } from "../../apps/web/src/strategy-markers.mjs";

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
    { name: "Modelled entry fill", label: "RESEARCH_PROPOSAL", value: "101.05", reason: "slippage" },
    { name: "Position size (quantity)", label: "UNAVAILABLE", value: null, reason: "enter account size and risk %" },
  ]);
});
