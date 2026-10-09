import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import { TIMEFRAME_SECONDS } from "../../apps/web/src/research-api.mjs";
import {
  APPROVED_INSTRUMENTS,
  loadWatchlist,
  supportedWatchlistSymbols,
  validateWatchlistSnapshot,
  watchlistRow,
  workspaceHref,
} from "../../apps/web/src/watchlist-state.mjs";
import { workspaceSelection } from "../../apps/web/src/workspace-state.mjs";

const symbols = Object.entries(APPROVED_INSTRUMENTS).map(([instrument_id, symbol]) => ({
  instrument_id,
  symbol,
  venue_id: "BINANCE-SPOT",
  eligibility: "CHECKED_ON_EACH_REFRESH",
}));
const symbolResponse = {
  provider: "binance-spot-public",
  redistribution: "NOT_AUTHORIZED",
  instruments: symbols,
};

function snapshot(instrumentId, symbol, {
  quality = "VALID",
  reportQuality = quality,
  timeframe = "1h",
} = {}) {
  const id = instrumentId.toLowerCase();
  const candle = (marketId, sourceId, closeTime, close, volume) => ({
    market_data_id: marketId,
    source_record_id: sourceId,
    open_time: "2026-10-09T14:00:00Z",
    close_time: closeTime,
    finalization: "FINAL",
    metrics: {
      open: { value: "100", unit: "USDT" },
      high: { value: "120", unit: "USDT" },
      low: { value: "90", unit: "USDT" },
      close: { value: close, unit: "USDT" },
      volume: { value: volume, unit: "BTC" },
    },
  });
  return {
    instrument_id: instrumentId,
    symbol,
    venue_id: "BINANCE-SPOT",
    timeframe,
    as_of: "2026-10-09T15:01:00Z",
    freshness_cutoff: "2026-10-09T15:02:00Z",
    temporal_context: "CURRENT",
    snapshot_id: `snapshot-${id}`,
    data_quality: {
      report_id: `report-${id}`,
      status: quality,
      report_status: reportQuality,
      policy_version: "spot-quality-v1",
      policy_sha256: "a".repeat(64),
      report: {
        report_id: `report-${id}`,
        snapshot_id: `snapshot-${id}`,
        status: reportQuality,
      },
    },
    candles: [
      candle(`market-${id}-later`, `source-${id}-later`, "2026-10-09T15:01:00Z", "101.00", "0"),
      candle(`market-${id}-earlier`, `source-${id}-earlier`, "2026-10-09T15:00:00Z", "99.00", "2.50"),
    ],
    indicators: {},
    lineage: {
      adapter_version: "adapter-v1",
      market_data_ids: [`market-${id}-later`, `market-${id}-earlier`],
      source_record_ids: [`source-${id}-later`, `source-${id}-earlier`],
      sources: [
        { source_record_id: `source-${id}-later`, provider_id: "provider-exact", retrieval_time: "2026-10-09T15:02:00Z" },
        { source_record_id: `source-${id}-earlier`, provider_id: "provider-exact", retrieval_time: "2026-10-09T15:01:00Z" },
      ],
    },
    persisted: true,
    order_flow: {
      status: "UNAVAILABLE",
      reason_code: "REQUIRED_TRADE_AND_BOOK_INPUTS_NOT_AVAILABLE",
      result: null,
    },
  };
}

function fixtureFetch({ overrides = {}, networkFailures = [] } = {}) {
  const calls = [];
  const fetcher = async (url, options) => {
    calls.push({ url, options });
    if (url.endsWith("/symbols")) return { ok: true, json: async () => symbolResponse };
    const instrumentId = decodeURIComponent(new URL(url).pathname.split("/").at(-2));
    if (networkFailures.includes(instrumentId)) throw new Error("provider-shaped secret must not leak");
    if (Object.hasOwn(overrides, instrumentId)) {
      const override = overrides[instrumentId];
      if (override instanceof Error) throw override;
      return override;
    }
    const symbol = APPROVED_INSTRUMENTS[instrumentId];
    return { ok: true, json: async () => snapshot(instrumentId, symbol) };
  };
  return { fetcher, calls };
}

test("supported-symbol response shows only the five exact approved instruments", () => {
  const allowed = supportedWatchlistSymbols({
    ...symbolResponse,
    instruments: [
      ...symbolResponse.instruments,
      { instrument_id: "DOGE-USDT-SPOT", symbol: "DOGEUSDT", venue_id: "BINANCE-SPOT", eligibility: "CHECKED_ON_EACH_REFRESH" },
    ],
  });
  assert.deepEqual(allowed.map((item) => item.symbol), ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]);
  assert.throws(() => supportedWatchlistSymbols({ ...symbolResponse, provider: "unexpected" }), /contract/);
  assert.throws(() => supportedWatchlistSymbols({ ...symbolResponse, instruments: [] }), /no approved supported/);
  assert.throws(() => supportedWatchlistSymbols({
    ...symbolResponse,
    instruments: [{ ...symbols[0], symbol: "UNEXPECTED" }],
  }), /invalid approved/);
});

test("snapshot rows preserve exact latest candle values and bound provenance", () => {
  const response = snapshot("BTC-USDT-SPOT", "BTCUSDT", { quality: "STALE", reportQuality: "VALID" });
  const row = watchlistRow(response, "BTCUSDT");
  assert.equal(row.close, "101.00");
  assert.equal(row.priceUnit, "USDT");
  assert.equal(row.candleTime, "2026-10-09T15:01:00Z");
  assert.equal(row.volume, "0");
  assert.equal(row.volumeUnit, "BTC");
  assert.equal(row.sourceId, "source-btc-usdt-spot-later");
  assert.equal(row.marketDataId, "market-btc-usdt-spot-later");
  assert.equal(row.snapshotId, "snapshot-btc-usdt-spot");
  assert.equal(row.qualityReportId, "report-btc-usdt-spot");
  assert.equal(row.quality, "STALE");
  assert.equal(row.reportQuality, "VALID");
  assert.equal(row.temporalContext, "CURRENT");
  assert.equal(row.freshnessCutoff, "2026-10-09T15:02:00Z");
  assert.equal(row.change, "Unavailable — not supplied");
  assert.equal(row.analysis, "Not provided");
});

test("historical snapshots require an exact cutoff and remain explicitly historical", () => {
  const historical = snapshot("BTC-USDT-SPOT", "BTCUSDT");
  historical.temporal_context = "HISTORICAL";
  historical.requested_as_of = "2026-10-09T15:02:00Z";
  assert.equal(validateWatchlistSnapshot(historical, {
    instrumentId: "BTC-USDT-SPOT",
    symbol: "BTCUSDT",
    timeframe: "1h",
  }), null);
  assert.equal(watchlistRow(historical, "BTCUSDT").temporalContext, "HISTORICAL");
  historical.requested_as_of = "2026-10-09T15:03:00Z";
  assert.match(validateWatchlistSnapshot(historical, {
    instrumentId: "BTC-USDT-SPOT",
    symbol: "BTCUSDT",
    timeframe: "1h",
  }), /does not match the requested historical cutoff/);
});

test("each supported instrument remains independent across success, malformed binding, stale and provider errors", async () => {
  const mismatched = snapshot("ETH-USDT-SPOT", "ETHUSDT");
  mismatched.timeframe = "4h";
  const { fetcher, calls } = fixtureFetch({
    overrides: {
      "ETH-USDT-SPOT": { ok: true, json: async () => mismatched },
      "SOL-USDT-SPOT": { ok: true, json: async () => snapshot("SOL-USDT-SPOT", "SOLUSDT", { quality: "STALE", reportQuality: "VALID" }) },
      "XRP-USDT-SPOT": { ok: true, json: async () => snapshot("XRP-USDT-SPOT", "XRPUSDT", { quality: "DEGRADED" }) },
    },
    networkFailures: ["BNB-USDT-SPOT"],
  });
  const results = await loadWatchlist(fetcher, "1h");
  assert.equal(results.length, 5);
  assert.equal(results[0].row.close, "101.00");
  assert.match(results[1].error, /lacks required snapshot identity or provenance/);
  assert.match(results[2].error, /unreachable/);
  assert.equal(results[3].row.quality, "STALE");
  assert.equal(results[4].row.quality, "DEGRADED");
  assert.equal(calls.length, 6);
  assert.ok(calls.slice(1).every(({ url }) => new URL(url).searchParams.get("timeframe") === "1h"));
  assert.ok(calls.every(({ url, options }) =>
    url.startsWith("http://127.0.0.1:8000/api/research/spot/") &&
    (options.method ?? "GET") === "GET" &&
    !url.includes("/refresh"),
  ));
});

test("timeframes and workspace links are restricted to validated supported values", async () => {
  const { fetcher, calls } = fixtureFetch();
  await assert.rejects(loadWatchlist(fetcher, "2m"), /supported by the local research API/);
  assert.equal(calls.length, 0);
  assert.ok(Object.hasOwn(TIMEFRAME_SECONDS, "1h"));
  assert.equal(
    workspaceHref("BTC-USDT-SPOT", "1h", symbols),
    "./index.html?instrument=BTC-USDT-SPOT&timeframe=1h",
  );
  assert.equal(workspaceHref("https://example.invalid", "1h", symbols), null);
  assert.equal(workspaceHref("BTC-USDT-SPOT", "2m", symbols), null);
  assert.deepEqual(workspaceSelection(
    "?instrument=BTC-USDT-SPOT&timeframe=4h&redirect=https%3A%2F%2Fexample.invalid",
    symbols,
    Object.keys(TIMEFRAME_SECONDS),
  ), { instrumentId: "BTC-USDT-SPOT", timeframe: "4h" });
  assert.deepEqual(workspaceSelection(
    "?instrument=https%3A%2F%2Fexample.invalid&timeframe=2m",
    symbols,
    Object.keys(TIMEFRAME_SECONDS),
  ), { instrumentId: "BTC-USDT-SPOT", timeframe: "1m" });
  assert.deepEqual(workspaceSelection(
    "?instrument=BTC-USDT-SPOT&instrument=ETH-USDT-SPOT&timeframe=1h",
    symbols,
    Object.keys(TIMEFRAME_SECONDS),
  ), { instrumentId: "BTC-USDT-SPOT", timeframe: "1h" });
});

test("overview navigation and controls cannot issue refresh or external requests", async () => {
  const [page, script] = await Promise.all([
    readFile(new URL("../../apps/web/watchlist.html", import.meta.url), "utf8"),
    readFile(new URL("../../apps/web/src/watchlist.mjs", import.meta.url), "utf8"),
  ]);
  assert.match(page, /<select id="timeframe-select"/);
  assert.match(page, /<th scope="col">Quality \/ temporal status<\/th>/);
  assert.match(page, /href="\.\/index\.html"/);
  assert.match(page, /<label>Timeframe\s*<select/);
  assert.match(script, /if \(!symbols\.length\) symbolsPromise = undefined/);
  assert.doesNotMatch(script, /refreshSnapshot|addEventListener\(["']focus|setInterval|WebSocket/);
  const styles = await readFile(new URL("../../apps/web/styles.css", import.meta.url), "utf8");
  assert.match(styles, /:focus-visible/);
  assert.match(styles, /@media \(max-width: 850px\)/);
  const { fetcher, calls } = fixtureFetch();
  await loadWatchlist(fetcher, "1m");
  assert.equal(calls.length, 6);
  assert.ok(calls.every(({ url }) => url.startsWith("http://127.0.0.1:8000/")));
});
