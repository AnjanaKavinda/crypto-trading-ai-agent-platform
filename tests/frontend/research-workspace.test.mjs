import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import {
  listSupportedSymbols,
  readSnapshot,
  refreshLimitWithinCoverage,
  refreshSnapshot,
} from "../../apps/web/src/research-api.mjs";
import {
  DEFAULT_VISIBILITY,
  displayCandle,
  indicatorBindingError,
  latestIndicatorValues,
  loadPreferences,
  plotValues,
  preferenceKey,
  savePreferences,
  snapshotCandles,
  snapshotLabels,
  validateSnapshot,
} from "../../apps/web/src/workspace-state.mjs";

const API_ORIGIN = "http://127.0.0.1:8000";
const instrumentId = "BTC-USDT-SPOT";
const timeframe = "1m";

function fakeFetch(responses = []) {
  const calls = [];
  const fetcher = async (url, options) => {
    calls.push({ url, options });
    const next = responses.shift() ?? { ok: true, json: async () => ({}) };
    return next;
  };
  return { fetcher, calls };
}

test("initial reads use only the loopback Spot API and supported-symbol response", async () => {
  const symbols = {
    provider: "binance-spot-public",
    redistribution: "NOT_AUTHORIZED",
    instruments: [
      ["BTC-USDT-SPOT", "BTCUSDT"],
      ["ETH-USDT-SPOT", "ETHUSDT"],
      ["BNB-USDT-SPOT", "BNBUSDT"],
      ["SOL-USDT-SPOT", "SOLUSDT"],
      ["XRP-USDT-SPOT", "XRPUSDT"],
    ].map(([instrument_id, symbol]) => ({
      instrument_id, symbol, venue_id: "BINANCE-SPOT", eligibility: "CHECKED_ON_EACH_REFRESH",
    })),
  };
  const client = fakeFetch([
    { ok: true, json: async () => symbols },
    { ok: true, json: async () => ({ candles: [] }) },
  ]);
  const supported = await listSupportedSymbols(client.fetcher);
  await readSnapshot(client.fetcher, { instrumentId, timeframe, limit: 250 });
  assert.deepEqual(supported, symbols);
  assert.deepEqual(client.calls.map(({ options }) => options.method ?? "GET"), ["GET", "GET"]);
  assert.ok(client.calls.every(({ url }) => url.startsWith(`${API_ORIGIN}/api/research/spot/`)));
  assert.ok(client.calls.every(({ options }) => options.credentials === "omit"));
  assert.equal(client.calls[0].url, `${API_ORIGIN}/api/research/spot/symbols`);
  assert.match(client.calls[1].url, /\/BTC-USDT-SPOT\/candles\?timeframe=1m&limit=250$/);
});

test("only an explicit refresh request issues the bounded POST", async () => {
  const client = fakeFetch([{ ok: true, json: async () => ({ snapshot_id: "fixture" }) }]);
  const now = Date.parse("2026-10-09T15:19:36.042Z");
  await refreshSnapshot(client.fetcher, { instrumentId, timeframe, limit: 50, now });
  assert.equal(client.calls.length, 1);
  const [{ url, options }] = client.calls;
  assert.equal(url, `${API_ORIGIN}/api/research/spot/${instrumentId}/refresh`);
  assert.equal(options.method, "POST");
  assert.equal(options.credentials, "omit");
  assert.deepEqual(JSON.parse(options.body), {
    timeframe: "1m",
    coverage_start: "2026-10-09T14:29:00.000Z",
    coverage_end: "2026-10-09T15:19:00.000Z",
    limit: 50,
  });
  assert.equal(Date.parse(JSON.parse(options.body).coverage_end) % 60_000, 0);
});

test("refresh and read selectors reject unbounded or unsupported inputs before fetch", async () => {
  const client = fakeFetch();
  assert.throws(
    () => refreshSnapshot(client.fetcher, { instrumentId, timeframe: "2m", limit: 50 }),
    /Unsupported API timeframe/,
  );
  assert.throws(
    () => readSnapshot(client.fetcher, { instrumentId, timeframe, limit: 502 }),
    /outside the API limit/,
  );
  assert.equal(client.calls.length, 0);
});

test("daily refresh respects the API's 90-day coverage limit", async () => {
  const client = fakeFetch();
  assert.throws(
    () => refreshSnapshot(client.fetcher, { instrumentId, timeframe: "1d", limit: 100 }),
    /90-day coverage limit/,
  );
  assert.equal(client.calls.length, 0);
  assert.equal(refreshLimitWithinCoverage("1d", 90), true);
  assert.equal(refreshLimitWithinCoverage("1d", 100), false);
});

test("API failure output is sanitized and does not expose server problem details", async () => {
  const client = fakeFetch([{
    ok: false,
    status: 503,
    json: async () => { throw new Error("SECRET server detail"); },
  }]);
  await assert.rejects(readSnapshot(client.fetcher, { instrumentId, timeframe, limit: 50 }), (error) => {
    assert.match(error.message, /local research API or its configured provider\/storage/);
    assert.doesNotMatch(error.message, /SECRET/);
    return true;
  });
});

test("historical and stale evidence remain explicitly distinct", () => {
  const staleHistorical = {
    temporal_context: "HISTORICAL",
    data_quality: { status: "STALE" },
  };
  assert.deepEqual(snapshotLabels(staleHistorical), {
    temporal: "HISTORICAL — NOT CURRENT",
    quality: "STALE",
    severity: "warning",
  });
  assert.equal(snapshotLabels({
    temporal_context: "CURRENT",
    data_quality: { status: "DEGRADED" },
  }).severity, "error");
  assert.equal(snapshotLabels({
    data_quality: { status: "VALID" },
  }).temporal, "UNKNOWN TEMPORAL CONTEXT");
});

test("candle fixtures preserve exact API strings, scientific notation, and valid zero volume", () => {
  const candle = {
    market_data_id: "market-1",
    source_record_id: "source-1",
    open_time: "2026-10-09T15:00:00Z",
    close_time: "2026-10-09T15:01:00Z",
    finalization: "FINAL",
    metrics: {
      open: { value: "1E-18", unit: "USDT" },
      high: { value: "1.2E-18", unit: "USDT" },
      low: { value: "9E-19", unit: "USDT" },
      close: { value: "1.1E-18", unit: "USDT" },
      volume: { value: "0", unit: "BTC" },
    },
  };
  assert.equal(displayCandle(candle).open.exact, "1E-18");
  assert.equal(displayCandle(candle).volume.exact, "0");
  assert.equal(snapshotCandles({ candles: [candle] }).candles.length, 1);
});

test("partial and invalid candle fixtures render no plausible fallback values", () => {
  const incomplete = {
    finalization: "FINAL",
    metrics: {
      open: { value: "0", unit: "USDT" },
      high: { value: "0", unit: "USDT" },
      low: { value: "0", unit: "USDT" },
      close: { value: "0", unit: "USDT" },
      volume: { value: "0", unit: "BTC" },
    },
  };
  assert.equal(displayCandle(incomplete), null);
  assert.match(snapshotCandles({ candles: [incomplete] }).error, /incomplete or invalid/);
  assert.match(snapshotCandles({ candles: [] }).error, /No candle observations/);
});

test("complete snapshots must preserve the exact candle-to-lineage and source binding", () => {
  const candle = {
    market_data_id: "market-1",
    source_record_id: "source-1",
    open_time: "2026-10-09T15:00:00Z",
    close_time: "2026-10-09T15:01:00Z",
    finalization: "FINAL",
    metrics: {
      open: { value: "10", unit: "USDT" },
      high: { value: "12", unit: "USDT" },
      low: { value: "9", unit: "USDT" },
      close: { value: "11", unit: "USDT" },
      volume: { value: "2", unit: "BTC" },
    },
  };
  const snapshot = {
    instrument_id: instrumentId,
    symbol: "BTCUSDT",
    venue_id: "BINANCE-SPOT",
    timeframe,
    as_of: "2026-10-09T15:01:00Z",
    freshness_cutoff: "2026-10-09T15:02:00Z",
    temporal_context: "CURRENT",
    snapshot_id: "snapshot-1",
    data_quality: {
      report_id: "report-1",
      status: "VALID",
      report_status: "VALID",
      policy_version: "personal-binance-spot-ohlcv-v1",
      policy_sha256: "a".repeat(64),
    },
    lineage: {
      source_record_ids: ["source-1"],
      market_data_ids: ["market-1"],
      adapter_version: "binance-spot-adapter-v1",
      sources: [{ source_record_id: "source-1" }],
    },
    persisted: true,
    candles: [candle],
    indicators: {},
    order_flow: { status: "UNAVAILABLE", reason_code: "REQUIRED_TRADE_AND_BOOK_INPUTS_NOT_AVAILABLE" },
  };
  assert.equal(validateSnapshot(snapshot, { instrumentId, timeframe }), null);
  assert.match(validateSnapshot({
    ...snapshot,
    data_quality: { ...snapshot.data_quality, report_status: "STALE" },
  }, { instrumentId, timeframe }), /required snapshot identity or provenance/);
  assert.match(validateSnapshot({
    ...snapshot,
    candles: [{ ...candle, market_data_id: "unbound-market" }],
  }, { instrumentId, timeframe }), /exact snapshot lineage/);

  const result = {
    indicator_id: "rsi",
    parameters: [["period", 14]],
    snapshot_id: snapshot.snapshot_id,
    quality_report_id: snapshot.data_quality.report_id,
    instrument_id: snapshot.instrument_id,
    venue_id: snapshot.venue_id,
    timeframe: snapshot.timeframe,
    as_of: snapshot.as_of,
    metadata_version: "1",
    calculation_version: "fixture-v1",
    input_market_data_ids: ["market-1"],
    points: [{
      candle_end: candle.close_time,
      value: { value: "42.5", status: "READY", reason: null },
    }],
  };
  const rsi = { status: "AVAILABLE", reason_code: null, result };
  assert.equal(indicatorBindingError(snapshot, "rsi-14", rsi), null);
  assert.equal(indicatorBindingError({
    ...snapshot,
    data_quality: { ...snapshot.data_quality, status: "STALE" },
  }, "rsi-14", rsi), "QUALITY_NOT_VALID");
  assert.equal(indicatorBindingError(snapshot, "rsi-14", {
    ...rsi,
    result: { ...result, snapshot_id: "different-snapshot" },
  }), "INDICATOR_PROVENANCE_MISMATCH");
  assert.equal(indicatorBindingError(snapshot, "rsi-14", {
    ...rsi,
    result: { ...result, indicator_id: "cci" },
  }), "INDICATOR_PROVENANCE_MISMATCH");
  assert.deepEqual(latestIndicatorValues(result), {
    values: [["value", "42.5"]],
    unavailable: [],
  });
  assert.deepEqual(latestIndicatorValues({ points: [{
    line: { value: null, status: "WARMUP", reason: "WARMUP" },
    signal: { value: null, status: "UNDEFINED", reason: "ZERO_RANGE" },
  }] }), {
    values: [],
    unavailable: ["line: WARMUP (WARMUP)", "signal: UNDEFINED (ZERO_RANGE)"],
  });
});

test("indicator charts use only returned, non-null backend points", () => {
  const result = { points: [
    { candle_end: "2026-10-09T15:00:00Z", value: null },
    { candle_end: "2026-10-09T15:01:00Z", value: "6.125" },
    { candle_end: "2026-10-09T15:02:00Z", value: "UNDEFINED" },
  ] };
  assert.deepEqual(plotValues(result), [
    { candleEnd: "2026-10-09T15:01:00Z", value: "6.125" },
  ]);
  assert.deepEqual(plotValues({ points: [{ candle_end: "2026-10-09T15:00:00Z", value: null }] }), []);
});

test("preferences are display-only, reset to beginner defaults, and scope by instrument and timeframe", () => {
  const values = new Map();
  const storage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  };
  assert.deepEqual(loadPreferences(storage, instrumentId, timeframe), {
    mode: "beginner",
    visible: [...DEFAULT_VISIBILITY],
  });
  savePreferences(storage, instrumentId, timeframe, {
    mode: "pro",
    visible: ["ema-20", "rsi-14", "unsupported-input"],
  });
  assert.deepEqual(loadPreferences(storage, instrumentId, timeframe), {
    mode: "pro",
    visible: ["ema-20", "rsi-14"],
  });
  assert.notEqual(preferenceKey(instrumentId, timeframe), preferenceKey(instrumentId, "5m"));
  assert.notEqual(preferenceKey(instrumentId, timeframe), preferenceKey("ETH-USDT-SPOT", timeframe));
  savePreferences(storage, instrumentId, timeframe, { mode: "beginner", visible: [...DEFAULT_VISIBILITY] });
  assert.deepEqual(loadPreferences(storage, instrumentId, timeframe).visible, [...DEFAULT_VISIBILITY]);
});

test("workspace source contains no polling or external provider path", async () => {
  const source = await readFile(new URL("../../apps/web/src/app.mjs", import.meta.url), "utf8");
  assert.doesNotMatch(source, /setInterval|WebSocket|binance\.com|api\.binance/i);
  assert.match(source, /refreshButton\.addEventListener\("click"/);
  assert.equal((source.match(/refreshSnapshot\(/g) ?? []).length, 1);
  assert.match(source, /snapshot = null;\s*updateRefreshAvailability\(\)/);
  const refreshStart = source.indexOf("const response = await refreshSnapshot(");
  const staleGuard = source.indexOf("if (sequence !== requestSequence) return;", refreshStart);
  const responseAssignment = source.indexOf("snapshot = response;", refreshStart);
  assert.ok(refreshStart < staleGuard && staleGuard < responseAssignment);
});
