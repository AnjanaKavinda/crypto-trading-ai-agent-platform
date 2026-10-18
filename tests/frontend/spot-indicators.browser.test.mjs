import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { extname, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { once } from "node:events";
import test from "node:test";
import { TIMEFRAME_SECONDS } from "../../apps/web/src/research-api.mjs";
import { DEFAULT_VISIBILITY, INDICATOR_IDS } from "../../apps/web/src/workspace-state.mjs";

const require = createRequire(new URL("../../apps/web/package.json", import.meta.url));
const { chromium } = require("playwright");
const webRoot = resolve(fileURLToPath(new URL("../../apps/web/", import.meta.url)));
const instrumentId = "BTC-USDT-SPOT";
const symbol = "BTCUSDT";
const candleCount = 501;
const qualityReportId = "fixture-report-btc-1m";
const snapshotId = "fixture-snapshot-btc-1m";

function decimal(value) {
  return value.toFixed(4);
}

function createSnapshot({ timeframe = "1m", count = candleCount } = {}) {
  const candleCount = count;
  const intervalMs = TIMEFRAME_SECONDS[timeframe] * 1000;
  const firstOpen = Date.UTC(2026, 9, 16, 0, 0, 0) - candleCount * intervalMs;
  const candles = Array.from({ length: candleCount }, (_, index) => {
    const openTime = new Date(firstOpen + index * intervalMs).toISOString();
    const closeTime = new Date(firstOpen + (index + 1) * intervalMs).toISOString();
    const open = 100 + index * 0.01;
    return {
      market_data_id: `fixture-market-${index}`,
      source_record_id: "fixture-source-btc",
      open_time: openTime,
      close_time: closeTime,
      finalization: "FINAL",
      metrics: {
        open: { value: decimal(open), unit: "USDT" },
        high: { value: decimal(open + 1), unit: "USDT" },
        low: { value: decimal(open - 1), unit: "USDT" },
        close: { value: decimal(open + 0.25), unit: "USDT" },
        volume: { value: decimal(1 + index / 10), unit: "BTC" },
      },
    };
  });
  const marketDataIds = candles.map((candle) => candle.market_data_id);
  const asOf = candles.at(-1).close_time;
  const points = (valueFor) => candles.map((candle, index) => ({
    candle_end: candle.close_time,
    ...valueFor(index),
  }));
  const result = (indicatorId, parameters, indicatorPoints, fields = {}) => ({
    indicator_id: indicatorId,
    ...fields,
    parameters,
    snapshot_id: snapshotId,
    quality_report_id: qualityReportId,
    instrument_id: instrumentId,
    venue_id: "BINANCE-SPOT",
    timeframe,
    as_of: asOf,
    metadata_version: "1",
    calculation_version: "fixture-calculation-v1",
    input_market_data_ids: marketDataIds,
    points: indicatorPoints,
  });
  const ema20 = points((index) => ({ value: decimal(100.2 + index * 0.01) }));
  const ema50 = points((index) => ({ value: decimal(100.1 + index * 0.009) }));
  const bollinger = points((index) => {
    const middle = 100 + index * 0.01;
    return {
      middle: decimal(middle),
      upper: decimal(middle + 1.5),
      lower: decimal(middle - 1.5),
      bandwidth: "0.0300",
    };
  });
  const atr = points((index) => ({ value: decimal(0.2 + index * 0.0005) }));
  const realizedVolatility = points((index) => ({ value: decimal(0.1 + index * 0.0002) }));
  const ready = (value) => ({ status: "READY", value: decimal(value), reason: null });
  const rsi = points((index) => ({ value: ready(40 + index * 0.02) }));
  const macd = points((index) => ({
    line: ready(-0.5 + index * 0.002),
    signal: ready(-0.4 + index * 0.0015),
    histogram: ready(-0.1 + index * 0.0005),
  }));
  const stochastic = points((index) => ({
    k: ready(30 + index * 0.03),
    d: ready(35 + index * 0.02),
  }));
  const cci = points((index) => ({ value: ready(-100 + index * 0.4) }));
  const analysisResult = (indicatorId, fields) => ({
    indicator_id: indicatorId,
    metadata_version: "1",
    calculation_version: `${indicatorId}-fixture-v1`,
    method_label: `${indicatorId} backend fixture method`,
    timeframe,
    instrument_id: instrumentId,
    venue_id: "BINANCE-SPOT",
    snapshot_id: snapshotId,
    quality_report_id: qualityReportId,
    as_of: asOf,
    window_start: candles[0].open_time,
    window_end: asOf,
    input_market_data_ids: marketDataIds,
    ...fields,
  });
  const volumeProfileBins = Array.from({ length: 24 }, (_, index) => ({
    index,
    lower_bound: decimal(99 + index),
    upper_bound: decimal(100 + index),
    includes_upper_bound: index === 23,
    assigned_volume: decimal(index + 1),
  }));
  const spotAnalysis = {
    vwap: {
      status: "AVAILABLE",
      reason_code: null,
      result: analysisResult("vwap", {
        parameters: [["anchor-mode", "snapshot-start"]],
        price_unit: "USDT",
        volume_unit: "BTC",
        anchor_mode: "first-candle",
        anchor_time: candles[0].open_time,
        points: candles.map((candle, index) => ({
          candle_end: candle.close_time,
          value: { value: decimal(100 + index * 0.01), status: "READY", reason: null },
        })),
      }),
    },
    "volume-profile": {
      status: "AVAILABLE",
      reason_code: null,
      result: analysisResult("volume-profile", {
        parameters: [["bin-count", 24], ["value-area-percent", 70]],
        price_unit: "USDT",
        volume_unit: "BTC",
        status: "READY",
        reason: null,
        bins: volumeProfileBins,
        poc_bin_index: 12,
        value_area_bin_indices: [8, 9, 10, 11, 12, 13, 14],
        value_area_low: "107.0000",
        value_area_high: "114.0000",
        value_area_volume: "84.0000",
        value_area_share: "0.7000",
        high_volume_node_bin_indices: [12],
        low_volume_node_bin_indices: [0, 23],
      }),
    },
    "volume-confirmation": {
      status: "PARTIAL",
      reason_code: "CONTEXTUAL_ASSESSMENTS_NOT_CONFIGURED",
      result: analysisResult("volume-confirmation", {
        parameters: [["lookback", 20]],
        price_unit: "USDT",
        volume_unit: "BTC",
        lookback: 20,
        points: candles.map((candle, index) => ({
          candle_end: candle.close_time,
          raw_volume: decimal(1 + index / 10),
          prior_volume_sum: index < 20 ? null : "20.0000",
          trailing_average: index < 20 ? null : "1.0000",
          relative_volume: index < 20 ? null : "1.1000",
          status: index < 20 ? "UNAVAILABLE" : "READY",
          reason: index < 20 ? "INSUFFICIENT_PRIOR_CANDLES" : null,
        })),
        assessment: { status: "INDETERMINATE", reason: "MISSING_EVENT_CONTEXT" },
        price_volume_comparison: { status: "INDETERMINATE", reason: "MISSING_COMPARISON_CONTEXT" },
        exhaustion_assessment: {
          status: "DATA_UNAVAILABLE",
          reason: "RELIABLE_ORDER_FLOW_NOT_SUPPLIED",
        },
        limitations: ["Caller context is not configured."],
      }),
    },
    "price-action-support-resistance": {
      status: "PARTIAL",
      reason_code: "CALLER_POLICIES_NOT_SUPPLIED",
      result: analysisResult("price-action-support-resistance", {
        method_version: "spot-price-action-geometry-fixture-v1",
        price_unit: "USDT",
        source_record_ids: ["fixture-source-btc"],
        range_baseline_policy: null,
        pattern_policy: null,
        support_resistance_policy: null,
        geometry: candles.map((candle, index) => ({
          market_data_id: candle.market_data_id,
          candle_time: candle.open_time,
          candle_end: candle.close_time,
          signed_body: "0.2500",
          range: "2.0000",
          upper_wick: "0.7500",
          lower_wick: "1.0000",
          close_location: "0.6250",
          close_location_reason: null,
          range_direction: null,
          range_comparison_reason: "NO_CALLER_BASELINE",
          patterns: [],
        })),
        pivots: [],
        zones: [],
        limitations: ["Caller policies were not supplied."],
      }),
    },
    "spot-market-structure": {
      status: "UNAVAILABLE",
      reason_code: "CALLER_PIVOT_AND_BREAK_POLICIES_NOT_SUPPLIED",
      result: null,
    },
  };

  return {
    instrument_id: instrumentId,
    symbol,
    venue_id: "BINANCE-SPOT",
    timeframe,
    as_of: asOf,
    freshness_cutoff: asOf,
    temporal_context: "CURRENT",
    snapshot_id: snapshotId,
    data_quality: {
      report_id: qualityReportId,
      status: "VALID",
      report_status: "VALID",
      policy_version: "personal-binance-spot-ohlcv-v1",
      policy_sha256: "a".repeat(64),
      report: {
        report_id: qualityReportId,
        snapshot_id: snapshotId,
        status: "VALID",
      },
    },
    lineage: {
      source_record_ids: ["fixture-source-btc"],
      market_data_ids: marketDataIds,
      adapter_version: "binance-spot-adapter-v1",
      sources: [{
        source_record_id: "fixture-source-btc",
        provider_id: "fixture-public-spot",
        retrieval_time: asOf,
      }],
    },
    persisted: true,
    candles,
    indicators: {
      "ema-20": {
        status: "AVAILABLE",
        reason_code: null,
        result: result("ema", [["period", 20]], ema20, { period: 20 }),
      },
      "ema-50": {
        status: "AVAILABLE",
        reason_code: null,
        result: result("ema", [["period", 50]], ema50, { period: 50 }),
      },
      "ema-500": {
        status: "AVAILABLE",
        reason_code: null,
        result: result("ema", [["period", 500]], ema50, { period: 500 }),
      },
      "bollinger-bands-20": {
        status: "AVAILABLE",
        reason_code: null,
        result: result("bollinger-bands", [
          ["period", 20],
          ["standard_deviation_multiplier", "2"],
        ], bollinger, { period: 20, standard_deviation_multiplier: "2" }),
      },
      "atr-14": {
        status: "AVAILABLE",
        reason_code: null,
        result: result("atr-14", [["period", 14]], atr, { period: 14 }),
      },
      "realized-volatility-20": {
        status: "AVAILABLE",
        reason_code: null,
        result: result("realized-volatility", [["period", 20]], realizedVolatility, { period: 20 }),
      },
      "rsi-14": {
        status: "AVAILABLE",
        reason_code: null,
        result: result("rsi", [["period", 14]], rsi, { period: 14 }),
      },
      "macd-12-26-9": {
        status: "AVAILABLE",
        reason_code: null,
        result: result("macd", [["fast-period", 12], ["slow-period", 26], ["signal-period", 9]], macd),
      },
      "stochastic-14-3": {
        status: "AVAILABLE",
        reason_code: null,
        result: result("stochastic", [["k-period", 14], ["d-period", 3]], stochastic),
      },
      "cci-20": {
        status: "AVAILABLE",
        reason_code: null,
        result: result("cci", [["period", 20]], cci, { period: 20 }),
      },
    },
    spot_analysis: spotAnalysis,
    order_flow: {
      status: "UNAVAILABLE",
      reason_code: "REQUIRED_TRADE_AND_BOOK_INPUTS_NOT_AVAILABLE",
      result: null,
    },
  };
}

const snapshot = createSnapshot();
let browser;
let server;
let origin;

async function serveAsset(request, response) {
  const pathname = decodeURIComponent(new URL(request.url, "http://127.0.0.1").pathname);
  const relativePath = pathname === "/" ? "index.html" : pathname.slice(1);
  const filePath = resolve(webRoot, relativePath);
  if (!filePath.startsWith(`${webRoot}${sep}`)) {
    response.writeHead(403).end();
    return;
  }
  try {
    const content = await readFile(filePath);
    const contentType = {
      ".html": "text/html; charset=utf-8",
      ".css": "text/css; charset=utf-8",
      ".mjs": "text/javascript; charset=utf-8",
    }[extname(filePath)] ?? "application/octet-stream";
    response.writeHead(200, { "content-type": contentType });
    response.end(content);
  } catch {
    response.writeHead(404).end();
  }
}

test.before(async () => {
  server = createServer((request, response) => {
    void serveAsset(request, response);
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  origin = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ headless: true });
});

test.after(async () => {
  await browser?.close();
  if (server?.listening) await new Promise((resolveClose) => server.close(resolveClose));
});

async function openWorkspace({ storedSnapshot, allowRefresh = false, visible } = {}) {
  const page = await browser.newPage();
  const apiRequests = [];
  let stored = storedSnapshot ?? snapshot;
  if (visible) {
    await page.addInitScript(({ key, value }) => localStorage.setItem(key, value), {
      key: `spot-research.presentation.v1:${instrumentId}:${stored.timeframe}`,
      value: JSON.stringify({ mode: "pro", visible }),
    });
  }
  await page.route("http://127.0.0.1:8000/api/research/spot/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    apiRequests.push({ method: request.method(), pathname: url.pathname, limit: url.searchParams.get("limit"), timeframe: url.searchParams.get("timeframe") });
    const headers = { "access-control-allow-origin": "*" };
    if (url.pathname.endsWith("/symbols")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        headers,
        body: JSON.stringify({
          provider: "binance-spot-public",
          redistribution: "NOT_AUTHORIZED",
          instruments: [{
            instrument_id: instrumentId,
            symbol,
            venue_id: "BINANCE-SPOT",
            eligibility: "CHECKED_ON_EACH_REFRESH",
          }],
        }),
      });
      return;
    }
    if (url.pathname.endsWith("/candles")) {
      if (url.searchParams.get("timeframe") !== stored.timeframe) {
        await route.fulfill({ status: 404, contentType: "application/problem+json", headers, body: "{}" });
        return;
      }
      if (Number(url.searchParams.get("limit")) >= stored.candles.length) {
        await route.fulfill({ status: 200, contentType: "application/json", headers, body: JSON.stringify(stored) });
        return;
      }
      await route.fulfill({
        status: 422,
        contentType: "application/problem+json",
        headers,
        body: JSON.stringify({
          type: "urn:trading-platform:problem:spot-candle-limit-exceeded",
          title: "Snapshot exceeds requested candle limit",
          status: 422,
          code: "SPOT_CANDLE_LIMIT_EXCEEDED",
          detail: "PRIVATE server diagnostic <script>must not appear</script>",
        }),
      });
      return;
    }
    if (url.pathname.endsWith("/refresh") && allowRefresh && request.method() === "POST") {
      const body = request.postDataJSON();
      assert.ok(body.limit * TIMEFRAME_SECONDS[body.timeframe] <= 90 * 86400);
      assert.ok(body.limit <= 501);
      stored = createSnapshot({ timeframe: body.timeframe, count: body.limit });
      await route.fulfill({ status: 200, contentType: "application/json", headers, body: JSON.stringify(stored) });
      return;
    }
    await route.fulfill({ status: 405, contentType: "application/json", headers, body: "{}" });
  });
  await page.goto(`${origin}/index.html?instrument=${instrumentId}&timeframe=${stored.timeframe}`);
  return { page, apiRequests };
}

function expectedPriceRange() {
  const values = [];
  for (const candle of snapshot.candles) {
    values.push(Number(candle.metrics.low.value), Number(candle.metrics.high.value));
  }
  values.push(...snapshot.spot_analysis.vwap.result.points.map((point) => Number(point.value.value)));
  for (const id of ["ema-20", "ema-50", "ema-500"]) {
    values.push(...snapshot.indicators[id].result.points.map((point) => Number(point.value)));
  }
  for (const point of snapshot.indicators["bollinger-bands-20"].result.points) {
    values.push(Number(point.upper), Number(point.middle), Number(point.lower));
  }
  let min = Math.min(...values);
  let max = Math.max(...values);
  const padding = max === min ? Math.max(Math.abs(max) * 0.02, 1) : (max - min) * 0.06;
  min -= padding;
  max += padding;
  return { min, span: max - min };
}

async function readSeries(page) {
  return page.locator("#chart-container polyline.indicator-line").evaluateAll((lines) =>
    lines.map((line) => ({
      series: [...line.classList].filter((name) => name !== "indicator-line").join(" "),
      points: (line.getAttribute("points") ?? "").trim().split(/\s+/).filter(Boolean).map((pair) =>
        pair.split(",").map(Number),
      ),
    })),
  );
}

async function waitForLoadedSnapshot(page) {
  await page.locator("#chart-container svg").waitFor({ state: "visible" });
  await page.locator("#snapshot-status").waitFor();
}

test("spot analyses render backend results bound to the exact snapshot and candle timestamps", async () => {
  const fixture = createSnapshot({ count: 50 });
  const { page, apiRequests } = await openWorkspace({ storedSnapshot: fixture });
  try {
    await waitForLoadedSnapshot(page);
    const vwap = page.locator('[data-analysis-key="vwap"]');
    assert.match(await vwap.innerText(), /AVAILABLE/);
    assert.match(await vwap.innerText(), /bar-based typical-price VWAP/);
    assert.match(await vwap.innerText(), /first-candle/);
    assert.match(await vwap.innerText(), new RegExp(snapshotId));
    const vwapRows = vwap.locator("tbody tr");
    assert.equal(await vwapRows.count(), fixture.candles.length);
    assert.ok((await vwapRows.first().innerText()).includes(fixture.candles[0].close_time));
    assert.ok((await vwapRows.first().innerText()).includes("100.0000 USDT"));
    const vwapLine = page.locator("#chart-container polyline.spot-vwap-line");
    assert.equal(await vwapLine.count(), 1);
    const plottedVwapPoints = await vwapLine.getAttribute("points");
    assert.equal(plottedVwapPoints.trim().split(/\s+/).length, fixture.candles.length);

    const profile = page.locator('[data-analysis-key="volume-profile"]');
    for (const detail of [
      "Candle-assigned typical-price volume-profile proxy",
      "bin-count=24",
      "value-area-percent=70",
      "Returned POC bin index: 12",
      "Returned VAL (USDT): 107.0000",
      "Returned VAH (USDT): 114.0000",
      "POC bin assigned volume (BTC): 13.0000",
    ]) assert.ok((await profile.innerText()).includes(detail), detail);

    const confirmation = page.locator('[data-analysis-key="volume-confirmation"]');
    assert.match(await confirmation.innerText(), /PARTIAL.*CONTEXTUAL_ASSESSMENTS_NOT_CONFIGURED/s);
    assert.match(await confirmation.innerText(), /INSUFFICIENT_PRIOR_CANDLES/);
    assert.match(await confirmation.innerText(), /MISSING_COMPARISON_CONTEXT/);
    assert.match(await confirmation.innerText(), /RELIABLE_ORDER_FLOW_NOT_SUPPLIED/);
    assert.ok((await confirmation.locator("tbody tr").first().innerText()).includes("UNAVAILABLE"));

    const priceAction = page.locator('[data-analysis-key="price-action-support-resistance"]');
    assert.match(await priceAction.innerText(), /CALLER_POLICIES_NOT_SUPPLIED/);
    assert.match(await priceAction.innerText(), /Only backend-supplied candle geometry/);
    assert.match(await priceAction.innerText(), /NO_CALLER_BASELINE/);
    assert.doesNotMatch(await priceAction.locator("tbody").innerText(), /engulfing|pivot|support|resistance/i);
    assert.doesNotMatch(await priceAction.locator("tbody").innerText(), /patterns|zones/i);

    const structure = page.locator('[data-analysis-key="spot-market-structure"]');
    assert.match(await structure.innerText(), /UNAVAILABLE/);
    assert.match(await structure.innerText(), /CALLER_PIVOT_AND_BREAK_POLICIES_NOT_SUPPLIED/);
    assert.match(await structure.innerText(), /No result payload was supplied/);

    assert.match(await page.locator("#spot-analysis-status").innerText(), /selected instrument, timeframe, snapshot, quality report, candle lineage, and cutoff/);
    assert.equal(apiRequests.filter((request) => request.method === "POST").length, 0);
  } finally {
    await page.close();
  }
});

for (const scenario of [
  {
    name: "PARTIAL",
    mutate(analysis) {
      analysis.status = "PARTIAL";
      analysis.reason_code = "ZERO_CUMULATIVE_VOLUME";
      analysis.result.points[0].value = {
        value: null,
        status: "UNDEFINED",
        reason: "ZERO_CUMULATIVE_VOLUME",
      };
    },
    expectedValue: "Not available",
  },
  {
    name: "WARMUP",
    mutate(analysis) {
      analysis.status = "WARMUP";
      analysis.reason_code = "INSUFFICIENT_WARMUP";
      for (const point of analysis.result.points) {
        point.value = { value: null, status: "UNDEFINED", reason: "INSUFFICIENT_WARMUP" };
      }
    },
    expectedValue: "Not available",
  },
  {
    name: "UNAVAILABLE",
    mutate(analysis) {
      analysis.status = "UNAVAILABLE";
      analysis.reason_code = "ZERO_CUMULATIVE_VOLUME";
      analysis.result = null;
    },
    expectedValue: "No result payload was supplied",
  },
]) {
  test(`spot VWAP ${scenario.name} preserves backend state and withholds unavailable values`, async () => {
    const fixture = createSnapshot({ count: 50 });
    scenario.mutate(fixture.spot_analysis.vwap);
    const { page, apiRequests } = await openWorkspace({ storedSnapshot: fixture });
    try {
      await waitForLoadedSnapshot(page);
      const card = page.locator('[data-analysis-key="vwap"]');
      assert.match(await card.innerText(), new RegExp(scenario.name));
      assert.match(await card.innerText(), /ZERO_CUMULATIVE_VOLUME|INSUFFICIENT_WARMUP/);
      assert.match(await card.innerText(), new RegExp(scenario.expectedValue));
      assert.equal(
        await page.locator("#chart-container polyline.spot-vwap-line").count(),
        scenario.name === "PARTIAL" ? 1 : 0,
      );
      if (scenario.name !== "UNAVAILABLE") {
        assert.match(await card.innerText(), /UNDEFINED.*ZERO_CUMULATIVE_VOLUME|UNDEFINED.*INSUFFICIENT_WARMUP/s);
      }
      assert.equal(apiRequests.filter((request) => request.method === "POST").length, 0);
    } finally {
      await page.close();
    }
  });
}

for (const quality of ["STALE", "INVALID"]) {
  test(`spot analyses with ${quality.toLowerCase()} quality withhold all result values`, async () => {
    const fixture = createSnapshot({ count: 50 });
    fixture.data_quality.status = quality;
    if (quality === "INVALID") {
      fixture.data_quality.report_status = "INVALID";
      fixture.data_quality.report.status = "INVALID";
      fixture.persisted = false;
    }
    fixture.spot_analysis["spot-market-structure"] = {
      status: "UNAVAILABLE",
      reason_code: quality === "STALE" ? "STALE_FOR_SERVING_CUTOFF" : "QUALITY_NOT_VALID",
      result: null,
    };
    const { page, apiRequests } = await openWorkspace({ storedSnapshot: fixture });
    try {
      await waitForLoadedSnapshot(page);
      assert.match(await page.locator("#spot-analysis-status").innerText(), new RegExp(quality));
      assert.equal(await page.locator("#chart-container polyline.spot-vwap-line").count(), 0);
      for (const id of [
        "vwap", "volume-profile", "volume-confirmation",
        "price-action-support-resistance", "spot-market-structure",
      ]) {
        const card = page.locator(`[data-analysis-key="${id}"]`);
        if (id === "spot-market-structure") {
          assert.match(await card.innerText(), new RegExp(
            quality === "STALE" ? "STALE_FOR_SERVING_CUTOFF" : "QUALITY_NOT_VALID",
          ));
        } else {
          assert.match(await card.innerText(), /Result payload withheld because snapshot quality is not VALID/);
        }
        assert.equal(await card.locator("table").count(), 0);
      }
      assert.equal(apiRequests.filter((request) => request.method === "POST").length, 0);
    } finally {
      await page.close();
    }
  });
}

test("spot analysis rejects mismatched snapshot provenance or candle timestamps", async () => {
  for (const corrupt of [
    (fixture) => { fixture.spot_analysis.vwap.result.indicator_id = "volume-profile"; },
    (fixture) => { fixture.spot_analysis.vwap.result.snapshot_id = "another-snapshot"; },
    (fixture) => {
      fixture.spot_analysis.vwap.result.points[0].candle_end =
        fixture.candles[1].close_time;
    },
  ]) {
    const fixture = createSnapshot({ count: 50 });
    corrupt(fixture);
    const { page } = await openWorkspace({ storedSnapshot: fixture });
    try {
      await waitForLoadedSnapshot(page);
      assert.match(
        await page.locator('[data-analysis-key="vwap"]').innerText(),
        /Result payload withheld: ANALYSIS_(?:PROVENANCE|CANDLE_BINDING)_MISMATCH/,
      );
      assert.equal(await page.locator("#chart-container polyline.spot-vwap-line").count(), 0);
    } finally {
      await page.close();
    }
  }
});

test("spot analysis unavailable and missing entries never expose supplied result values", async () => {
  const fixture = createSnapshot({ count: 50 });
  fixture.spot_analysis.vwap.status = "UNAVAILABLE";
  fixture.spot_analysis.vwap.reason_code = "ZERO_CUMULATIVE_VOLUME";
  delete fixture.spot_analysis["volume-profile"];
  const { page } = await openWorkspace({ storedSnapshot: fixture });
  try {
    await waitForLoadedSnapshot(page);
    const unavailable = page.locator('[data-analysis-key="vwap"]');
    assert.match(await unavailable.innerText(), /UNAVAILABLE.*ZERO_CUMULATIVE_VOLUME/s);
    assert.match(await unavailable.innerText(), /Backend status is UNAVAILABLE; result values are withheld/);
    assert.equal(await unavailable.locator("tbody tr").count(), fixture.candles.length);
    assert.equal(await unavailable.locator("tbody tr").first().locator("td").nth(2).innerText(), "Not available");
    assert.equal(await page.locator("#chart-container polyline.spot-vwap-line").count(), 0);

    const missing = page.locator('[data-analysis-key="volume-profile"]');
    assert.match(await missing.innerText(), /MISSING/);
    assert.match(await missing.innerText(), /did not supply this spot_analysis entry/);
    assert.equal(await missing.locator("table").count(), 0);
  } finally {
    await page.close();
  }
});

test("volume-profile withholds levels when its nested result is not READY", async () => {
  const fixture = createSnapshot({ count: 50 });
  fixture.spot_analysis["volume-profile"].result.status = "UNDEFINED";
  fixture.spot_analysis["volume-profile"].result.reason = "ZERO_TOTAL_VOLUME";
  const { page } = await openWorkspace({ storedSnapshot: fixture });
  try {
    await waitForLoadedSnapshot(page);
    const card = page.locator('[data-analysis-key="volume-profile"]');
    assert.match(await card.innerText(), /AVAILABLE/);
    assert.match(await card.innerText(), /Profile result status: UNDEFINED/);
    assert.match(await card.innerText(), /Profile result reason: ZERO_TOTAL_VOLUME/);
    assert.match(await card.innerText(), /returned levels are withheld/);
    assert.doesNotMatch(await card.innerText(), /Returned POC bin index|Returned VAL|Returned VAH|POC bin assigned volume/);
  } finally {
    await page.close();
  }
});

test("VWAP overlay remains isolated from indicator visibility preferences without refresh", async () => {
  const { page, apiRequests } = await openWorkspace({
    storedSnapshot: createSnapshot({ count: 50 }),
    visible: ["ema-20"],
  });
  try {
    await waitForLoadedSnapshot(page);
    assert.equal(await page.locator("#chart-container polyline.spot-vwap-line").count(), 1);
    await page.getByRole("button", { name: "Pro", exact: true }).click();
    await page.getByRole("checkbox", { name: "EMA 20", exact: true }).uncheck();
    assert.equal(await page.locator("#chart-container polyline.ema-20").count(), 0);
    assert.equal(await page.locator("#chart-container polyline.spot-vwap-line").count(), 1);
    assert.equal(apiRequests.filter((request) => request.method === "POST").length, 0);
  } finally {
    await page.close();
  }
});

test("indicator provenance links use the loaded response and the synthetic example stays separate", { timeout: 60_000 }, async () => {
  const { page, apiRequests } = await openWorkspace();
  try {
    await page.waitForFunction(() => document.querySelector("#snapshot-status")?.dataset.state === "error");
    await page.locator("#history-select").selectOption("501");
    await waitForLoadedSnapshot(page);

    const provenanceText = await page.locator("#snapshot-metadata").innerText();
    const sourceText = await page.locator("#source-list").innerText();
    for (const identity of [
      symbol,
      instrumentId,
      "1m",
      snapshotId,
      qualityReportId,
      "fixture-source-btc",
    ]) {
      assert.ok(`${provenanceText}\n${sourceText}`.includes(identity), `${identity} is present in current provenance`);
    }

    const requestsBeforeDisplayChanges = apiRequests.length;
    const firstLink = page.locator("#indicator-groups .indicator-card .indicator-provenance-link a").first();
    assert.equal(await page.locator("#indicator-groups .indicator-provenance-link a").count(), DEFAULT_VISIBILITY.length);
    assert.equal(await firstLink.getAttribute("href"), "#snapshot-provenance");
    assert.equal(await firstLink.getAttribute("tabindex"), null);
    assert.match(await firstLink.getAttribute("aria-label"), new RegExp(
      `${symbol}.*${instrumentId}.*1m.*${snapshotId}.*${qualityReportId}`,
    ));
    await firstLink.focus();
    await page.keyboard.press("Shift+Tab");
    await page.keyboard.press("Tab");
    assert.equal(await firstLink.evaluate((link) => document.activeElement === link), true);
    assert.equal(await firstLink.evaluate((link) => link.matches(":focus-visible")), true);
    await firstLink.click();
    assert.equal(new URL(page.url()).hash, "#snapshot-provenance");

    await page.getByRole("button", { name: "Pro", exact: true }).click();
    for (const id of INDICATOR_IDS) {
      const name = {
        "ema-20": "EMA 20",
        "ema-50": "EMA 50",
        "ema-500": "EMA 500",
        "atr-14": "ATR 14",
        "bollinger-bands-20": "Bollinger Bands 20",
        "realized-volatility-20": "Realized volatility 20",
        "rsi-14": "RSI 14",
        "macd-12-26-9": "MACD 12/26/9",
        "stochastic-14-3": "Stochastic 14/3",
        "cci-20": "CCI 20",
      }[id];
      await page.getByRole("checkbox", { name, exact: true }).check();
    }
    const cards = page.locator("#indicator-groups .indicator-card");
    assert.equal(await cards.count(), INDICATOR_IDS.length);
    assert.equal(await cards.locator(".indicator-provenance-link a").count(), INDICATOR_IDS.length);
    for (const card of await cards.all()) {
      const text = await card.innerText();
      assert.match(text, /Method version:/);
      assert.match(text, /Parameters:/);
      assert.match(text, /Regimes where it may be useful:/);
      assert.match(text, /Failure modes and limitations:/);
      const link = card.locator(".indicator-provenance-link a");
      assert.equal(await link.getAttribute("href"), "#snapshot-provenance");
      assert.match(await link.getAttribute("aria-label"), new RegExp(
        `${symbol}.*${instrumentId}.*1m.*${snapshotId}.*${qualityReportId}`,
      ));
    }

    await page.locator("#synthetic-example summary").click();
    assert.equal(await page.locator("#synthetic-example tbody tr").count(), INDICATOR_IDS.length);
    assert.match(await page.locator("#synthetic-example").innerText(), /synthetic \/ educational only/i);
    assert.match(await page.locator("#synthetic-example").innerText(), /not provider data.*not market evidence.*not a signal/s);
    assert.equal(await page.locator("#chart-container").innerText().then((text) => /synthetic/i.test(text)), false);
    assert.doesNotMatch(await page.locator("#snapshot-metadata").innerText(), /synthetic/i);
    assert.doesNotMatch(await page.locator("#indicator-groups").innerText(), /synthetic/i);
    assert.equal(apiRequests.length, requestsBeforeDisplayChanges);
    assert.equal(await page.locator("#snapshot-metadata").innerText(), provenanceText);
    assert.equal(await page.locator("#source-list").innerText(), sourceText);
  } finally {
    await page.close();
  }
});

test("browser chart toggles preserve series isolation and bind every point to its candle timestamp", { timeout: 60_000 }, async () => {
  const { page, apiRequests } = await openWorkspace();
  try {
    await page.waitForFunction(() => document.querySelector("#snapshot-status")?.dataset.state === "error");
    await page.locator("#history-select").selectOption("501");
    await waitForLoadedSnapshot(page);
    await page.getByRole("button", { name: "Pro", exact: true }).click();
    for (const name of [
      "EMA 20", "EMA 50", "EMA 500", "Bollinger Bands 20", "ATR 14",
      "Realized volatility 20", "RSI 14", "MACD 12/26/9", "Stochastic 14/3", "CCI 20",
    ]) {
      await page.getByRole("checkbox", { name, exact: true }).check();
    }

    const seriesGroups = {
      "EMA 20": ["ema-20"],
      "EMA 50": ["ema-50"],
      "EMA 500": ["ema-500"],
      "Bollinger Bands 20": ["bollinger-upper", "bollinger-middle", "bollinger-lower"],
      "ATR 14": ["atr-line"],
      "Realized volatility 20": ["realized-volatility-line"],
      "RSI 14": ["rsi-line"],
      "MACD 12/26/9": ["macd-line", "macd-signal", "macd-histogram"],
      "Stochastic 14/3": ["stochastic-k", "stochastic-d"],
      "CCI 20": ["cci-line"],
    };
    const expectedClasses = [...Object.values(seriesGroups).flat(), "spot-vwap-line"].sort();
    const rendered = await readSeries(page);
    assert.deepEqual(rendered.map((line) => line.series).sort(), expectedClasses);

    const priceRange = expectedPriceRange();
    const candleIndex = new Map(snapshot.candles.map((candle, index) => [Date.parse(candle.close_time), index]));
    const seriesResults = {
      "ema-20": snapshot.indicators["ema-20"].result.points.map((point) => [point.candle_end, point.value, "price"]),
      "ema-50": snapshot.indicators["ema-50"].result.points.map((point) => [point.candle_end, point.value, "price"]),
      "ema-500": snapshot.indicators["ema-500"].result.points.map((point) => [point.candle_end, point.value, "price"]),
      "bollinger-upper": snapshot.indicators["bollinger-bands-20"].result.points.map((point) => [point.candle_end, point.upper, "price"]),
      "bollinger-middle": snapshot.indicators["bollinger-bands-20"].result.points.map((point) => [point.candle_end, point.middle, "price"]),
      "bollinger-lower": snapshot.indicators["bollinger-bands-20"].result.points.map((point) => [point.candle_end, point.lower, "price"]),
      "atr-line": snapshot.indicators["atr-14"].result.points.map((point) => [point.candle_end, point.value, "atr"]),
      "realized-volatility-line": snapshot.indicators["realized-volatility-20"].result.points.map((point) => [point.candle_end, point.value, "realized-volatility"]),
      "rsi-line": snapshot.indicators["rsi-14"].result.points.map((point) => [point.candle_end, point.value.value, "rsi"]),
      "macd-line": snapshot.indicators["macd-12-26-9"].result.points.map((point) => [point.candle_end, point.line.value, "macd"]),
      "macd-signal": snapshot.indicators["macd-12-26-9"].result.points.map((point) => [point.candle_end, point.signal.value, "macd"]),
      "macd-histogram": snapshot.indicators["macd-12-26-9"].result.points.map((point) => [point.candle_end, point.histogram.value, "macd"]),
      "stochastic-k": snapshot.indicators["stochastic-14-3"].result.points.map((point) => [point.candle_end, point.k.value, "stochastic"]),
      "stochastic-d": snapshot.indicators["stochastic-14-3"].result.points.map((point) => [point.candle_end, point.d.value, "stochastic"]),
      "cci-line": snapshot.indicators["cci-20"].result.points.map((point) => [point.candle_end, point.value.value, "cci"]),
      "spot-vwap-line": snapshot.spot_analysis.vwap.result.points.map((point) => [point.candle_end, point.value.value, "price"]),
    };
    const panelAxes = [
      ["atr", ["atr-line"]],
      ["realized-volatility", ["realized-volatility-line"]],
      ["rsi", ["rsi-line"]],
      ["macd", ["macd-line", "macd-signal", "macd-histogram"]],
      ["stochastic", ["stochastic-k", "stochastic-d"]],
      ["cci", ["cci-line"]],
    ];
    const panelScales = new Map(panelAxes.map(([axis, classes], panelIndex) => {
      const values = classes.flatMap((className) => seriesResults[className].map(([, value]) => Number(value)));
      let min = Math.min(...values);
      let max = Math.max(...values);
      if (min >= 0) min = 0;
      if (max <= 0) max = 0;
      if (min === max) max = min + Math.max(Math.abs(min) * 0.02, 1);
      return [axis, { min, span: max - min, top: 320 + panelIndex * 120 }];
    }));
    for (const line of rendered) {
      const className = line.series;
      const expected = seriesResults[className];
      assert.equal(line.points.length, expected.length, `${className} point count`);
      expected.forEach(([candleEnd, exactValue, axis], index) => {
        const candle = candleIndex.get(Date.parse(candleEnd));
        assert.equal(candle, index, `${className} point timestamp must match its candle`);
        const expectedX = 70 + candle * 910 / (candleCount - 1);
        const value = Number(exactValue);
        const panel = panelScales.get(axis);
        const expectedY = axis === "price"
          ? 20 + 260 - (value - priceRange.min) / priceRange.span * 260
          : panel.top + 95 - (value - panel.min) / panel.span * 95;
        assert.ok(Math.abs(line.points[index][0] - expectedX) < 0.02, `${className} x alignment at candle ${index}`);
        assert.ok(Math.abs(line.points[index][1] - expectedY) < 0.02, `${className} value at candle ${index}`);
      });
    }

    for (const [name, removedClasses] of Object.entries(seriesGroups)) {
      const checkbox = page.getByRole("checkbox", { name, exact: true });
      await checkbox.uncheck();
      const disabledClasses = (await readSeries(page)).map((line) => line.series).sort();
      assert.deepEqual(disabledClasses, expectedClasses.filter((value) => !removedClasses.includes(value)));
      await checkbox.check();
      assert.deepEqual((await readSeries(page)).map((line) => line.series).sort(), expectedClasses);
    }
    const beginnerClasses = ["atr-line", "ema-20", "ema-50", "spot-vwap-line"].sort();
    await page.getByRole("button", { name: "Beginner", exact: true }).click();
    assert.deepEqual((await readSeries(page)).map((line) => line.series).sort(), beginnerClasses);
    await page.getByRole("button", { name: "Pro", exact: true }).click();
    assert.deepEqual((await readSeries(page)).map((line) => line.series).sort(), expectedClasses);

    await page.locator("#reset-button").click();
    assert.deepEqual((await readSeries(page)).map((line) => line.series).sort(), beginnerClasses);
    await page.getByRole("button", { name: "Pro", exact: true }).click();
    assert.deepEqual((await readSeries(page)).map((line) => line.series).sort(), beginnerClasses);
    assert.equal(apiRequests.filter((request) => request.pathname.endsWith("/refresh")).length, 0);
  } finally {
    await page.close();
  }
});

for (const scenario of [
  {
    name: "WARMUP",
    mutate(fixture) {
      const indicator = fixture.indicators["realized-volatility-20"];
      indicator.status = "WARMUP";
      indicator.reason_code = "INSUFFICIENT_WARMUP";
      indicator.result.points.forEach((point) => { point.value = null; });
    },
    controlReason: /INSUFFICIENT_WARMUP/,
    cardMessage: /The backend has not returned a warmed-up value.*Backend reason: INSUFFICIENT_WARMUP/s,
  },
  {
    name: "UNAVAILABLE with backend reason",
    mutate(fixture) {
      fixture.indicators["realized-volatility-20"] = {
        status: "UNAVAILABLE",
        reason_code: "DETERMINISTIC_CALCULATION_FAILED",
        result: null,
      };
    },
    controlReason: /DETERMINISTIC_CALCULATION_FAILED/,
    cardMessage: /No usable value.*Backend reason: DETERMINISTIC_CALCULATION_FAILED/s,
  },
  {
    name: "omitted response entry",
    mutate(fixture) {
      delete fixture.indicators["realized-volatility-20"];
    },
    controlReason: /not supplied in response/,
    cardMessage: /No usable value.*Display withheld: INDICATOR_STATUS_UNAVAILABLE/s,
  },
]) {
  test(`browser RV20 ${scenario.name} remains unavailable and unplotted`, async () => {
    const fixture = createSnapshot({ count: 50 });
    scenario.mutate(fixture);
    const { page, apiRequests } = await openWorkspace({
      storedSnapshot: fixture,
      visible: [...DEFAULT_VISIBILITY, "realized-volatility-20"],
    });
    try {
      await waitForLoadedSnapshot(page);
      const control = page.locator(".indicator-toggle", { hasText: "Realized volatility 20" });
      const card = page.locator(".indicator-card", { hasText: "Realized volatility 20" });
      assert.match(await control.innerText(), scenario.controlReason);
      assert.equal(await page.getByRole("checkbox", { name: /Realized volatility 20/ }).isDisabled(), true);
      assert.match(await card.innerText(), scenario.cardMessage);
      assert.equal(await card.locator(".indicator-value").count(), 0);
      assert.equal(await page.locator("#chart-container .realized-volatility-line").count(), 0);
      assert.equal(apiRequests.filter((request) => request.method === "POST").length, 0);
    } finally {
      await page.close();
    }
  });
}

test("browser clears the previous chart after a 501-candle snapshot rejects a 250-candle read", { timeout: 60_000 }, async () => {
  const { page, apiRequests } = await openWorkspace();
  try {
    await page.waitForFunction(() => document.querySelector("#snapshot-status")?.dataset.state === "error");
    await page.locator("#history-select").selectOption("501");
    await waitForLoadedSnapshot(page);
    assert.equal(await page.locator("#chart-container svg").count(), 1);

    await page.locator("#history-select").selectOption("250");
    await page.getByText("Research request failed.", { exact: true }).waitFor();
    assert.equal(await page.locator("#chart-container svg").count(), 0);
    assert.match(await page.locator("#chart-container").innerText(), /stored 1m snapshot.*maximum of 250/);
    assert.match(await page.locator("#chart-container").innerText(), /larger history bound.*explicitly refresh this same selector/);
    assert.doesNotMatch(await page.locator("body").innerText(), /PRIVATE|must not appear/);
    assert.equal(await page.locator("#snapshot-metadata").innerText(), "Instrument / venue\nNot yet available");
    assert.equal(await page.locator("#indicator-groups .indicator-provenance-link").count(), 0);
    assert.ok(apiRequests.some((request) => request.pathname.endsWith("/candles") && request.limit === "250"));
    assert.equal(apiRequests.filter((request) => request.pathname.endsWith("/refresh")).length, 0);
  } finally {
    await page.close();
  }
});

for (const timeframe of Object.keys(TIMEFRAME_SECONDS)) {
  for (const limit of [50, 90, 100, 250, 501]) {
    test(`browser ${timeframe}/${limit}: stored read, explicit refresh eligibility, exact readback`, { timeout: 60_000 }, async () => {
      const { page, apiRequests } = await openWorkspace({
        storedSnapshot: createSnapshot({ timeframe, count: limit }),
        allowRefresh: true,
      });
      try {
        await page.waitForFunction(() =>
          document.querySelector("#snapshot-status")?.dataset.state !== "warning");
        await page.locator("#history-select").selectOption(String(limit));
        await waitForLoadedSnapshot(page);
        assert.equal(await page.locator("#timeframe-select").inputValue(), timeframe);
        const metadata = await page.locator("#snapshot-metadata").innerText();
        assert.ok(metadata.includes(`Timeframe\n${timeframe}`));
        assert.ok(metadata.includes(`Returned candles\n${limit}`));
        assert.equal(await page.locator("#candle-rows tr").count(), limit);
        assert.equal(await page.locator("#chart-container svg").count(), 1);
        assert.ok(apiRequests.some((request) =>
          request.timeframe === timeframe && request.limit === String(limit)));
        assert.equal(apiRequests.filter((request) => request.method === "POST").length, 0);
        const eligible = timeframe !== "1d" || limit <= 90;
        assert.equal(await page.locator("#refresh-button").isDisabled(), !eligible);
        if (!eligible) {
          assert.match(await page.locator("#refresh-note").innerText(), /90-day.*2–90.*1d.*historical reads.*501/);
          return;
        }

        await page.locator("#refresh-button").click();
        await page.waitForFunction(() => !document.querySelector("#refresh-button").disabled);
        await waitForLoadedSnapshot(page);
        assert.equal(apiRequests.filter((request) => request.method === "POST").length, 1);
        const readsBefore = apiRequests.filter((request) => request.pathname.endsWith("/candles")).length;
        await page.locator("#history-select").selectOption(limit === 501 ? "50" : "501");
        await page.locator("#history-select").selectOption(String(limit));
        await waitForLoadedSnapshot(page);
        assert.ok(apiRequests.filter((request) => request.pathname.endsWith("/candles")).length > readsBefore);
        assert.equal(apiRequests.filter((request) => request.method === "POST").length, 1);
        assert.ok((await page.locator("#snapshot-metadata").innerText()).includes(`Returned candles\n${limit}`));
      } finally {
        await page.close();
      }
    });
  }
}

for (const [state, status, expected] of [
  ["missing", 404, /No stored snapshot matches/],
  ["provider unavailable", 503, /provider\/storage is unavailable/],
  ["invalid selector", 422, /rejected the selector or history bound/],
  ["corrupt provenance", 200, /exact snapshot lineage/],
]) {
  test(`browser ${state} clears prior chart, metadata, and sources`, async () => {
    const { page, apiRequests } = await openWorkspace({ storedSnapshot: createSnapshot({ count: 50 }) });
    try {
      await waitForLoadedSnapshot(page);
      assert.equal(await page.locator("#history-select").inputValue(), "250");
      assert.ok((await page.locator("#snapshot-metadata").innerText()).includes("Returned candles\n50"));
      const corrupt = createSnapshot({ count: 50 });
      corrupt.lineage.market_data_ids[0] = "mismatched-source";
      await page.route("**/candles?**", (route) => route.fulfill({
        status,
        contentType: "application/json",
        headers: { "access-control-allow-origin": "*" },
        body: JSON.stringify(status === 200 ? corrupt : { detail: "PRIVATE diagnostic", code: "UNKNOWN" }),
      }));
      await page.locator("#history-select").selectOption("90");
      await page.getByText("Research request failed.", { exact: true }).waitFor();
      assert.match(await page.locator("#chart-container").innerText(), expected);
      assert.doesNotMatch(await page.locator("body").innerText(), /PRIVATE/);
      assert.equal(await page.locator("#chart-container svg").count(), 0);
      assert.equal(await page.locator("#snapshot-metadata").innerText(), "Instrument / venue\nNot yet available");
      assert.equal(await page.locator("#source-list").innerText(), "");
      assert.equal(await page.locator("#candle-rows td").count(), 1);
      assert.equal(await page.locator("#indicator-groups .indicator-value").count(), 0);
      assert.doesNotMatch(await page.locator("#indicator-groups").innerText(), /fixture-calculation|fixture-snapshot|fixture-report/);
      assert.equal(apiRequests.filter((request) => request.method === "POST").length, 0);
    } finally {
      await page.close();
    }
  });
}

for (const state of ["STALE", "INVALID", "WARMUP", "HISTORICAL"]) {
  test(`browser preserves distinct ${state} context without inventing indicators`, async () => {
    const fixture = createSnapshot({ count: 50 });
    if (state === "STALE") {
      fixture.data_quality.status = "STALE";
      fixture.indicators["realized-volatility-20"] = {
        status: "UNAVAILABLE",
        reason_code: "STALE_FOR_SERVING_CUTOFF",
        result: null,
      };
    }
    if (state === "INVALID") {
      fixture.data_quality.status = "INVALID";
      fixture.data_quality.report_status = "INVALID";
      fixture.data_quality.report.status = "INVALID";
      fixture.persisted = false;
      fixture.indicators["realized-volatility-20"] = {
        status: "UNAVAILABLE",
        reason_code: "QUALITY_NOT_VALID",
        result: null,
      };
    }
    if (state === "WARMUP") {
      fixture.indicators["ema-20"].status = "WARMUP";
      fixture.indicators["ema-20"].reason_code = "INSUFFICIENT_WARMUP";
      fixture.indicators["ema-20"].result.points.forEach((point) => { point.value = null; });
    }
    const { page, apiRequests } = await openWorkspace({
      storedSnapshot: fixture,
      visible: state === "STALE" || state === "INVALID"
        ? [...DEFAULT_VISIBILITY, "realized-volatility-20"]
        : undefined,
    });
    try {
      await waitForLoadedSnapshot(page);
      if (state === "HISTORICAL") {
        await page.route("**/candles?**", (route) => {
          const asOf = new URL(route.request().url()).searchParams.get("as_of");
          return route.fulfill({
            status: 200,
            contentType: "application/json",
            headers: { "access-control-allow-origin": "*" },
            body: JSON.stringify({ ...fixture, temporal_context: "HISTORICAL", requested_as_of: asOf, freshness_cutoff: asOf }),
          });
        });
        const localCutoff = await page.evaluate((value) => {
          const instant = new Date(value);
          const part = (number) => String(number).padStart(2, "0");
          return `${instant.getFullYear()}-${part(instant.getMonth() + 1)}-${part(instant.getDate())}T${part(instant.getHours())}:${part(instant.getMinutes())}`;
        }, fixture.as_of);
        await page.locator("#as-of-input").fill(localCutoff);
        await page.locator("#as-of-input").dispatchEvent("change");
        await page.waitForFunction(() => document.querySelector("#snapshot-status").textContent.includes("HISTORICAL — NOT CURRENT"));
        assert.equal(await page.locator("#refresh-button").isDisabled(), true);
        assert.match(await page.locator("#refresh-note").innerText(), /Historical cutoffs are read-only/);
      } else if (state === "WARMUP") {
        assert.match(await page.locator("#indicator-groups").innerText(), /WARMUP.*INSUFFICIENT_WARMUP/s);
        assert.equal(await page.locator("#chart-container polyline.ema-20").count(), 0);
      } else {
        assert.match(await page.locator("#snapshot-status").innerText(), new RegExp(state));
        assert.equal(await page.locator("#chart-container polyline.indicator-line").count(), 0);
        assert.equal(await page.locator("#indicator-groups .indicator-value").count(), 0);
        if (state === "STALE" || state === "INVALID") {
          const expectedReason = state === "STALE" ? "STALE_FOR_SERVING_CUTOFF" : "QUALITY_NOT_VALID";
          if (state === "STALE") {
            assert.ok((await page.locator("#snapshot-metadata").innerText()).includes("Underlying report status\nVALID"));
          }
          assert.match(
            await page.locator(".indicator-toggle", { hasText: "Realized volatility 20" }).innerText(),
            new RegExp(expectedReason),
          );
          assert.equal(await page.getByRole("checkbox", { name: /Realized volatility 20/ }).isDisabled(), true);
          assert.match(
            await page.locator(".indicator-card", { hasText: "Realized volatility 20" }).innerText(),
            new RegExp(`Backend reason: ${expectedReason}`),
          );
          assert.equal(await page.locator("#chart-container .realized-volatility-line").count(), 0);
        }
      }
      assert.equal(apiRequests.filter((request) => request.method === "POST").length, 0);
    } finally {
      await page.close();
    }
  });
}

for (const delayedAction of ["read", "refresh"]) {
  test(`browser delayed ${delayedAction} cannot overwrite a newer timeframe selection`, async () => {
    const { page } = await openWorkspace({ storedSnapshot: createSnapshot({ count: 50 }) });
    let releaseResponse;
    let markStarted;
    const responseGate = new Promise((resolveGate) => { releaseResponse = resolveGate; });
    const started = new Promise((resolveStarted) => { markStarted = resolveStarted; });
    try {
      await waitForLoadedSnapshot(page);
      await page.route("http://127.0.0.1:8000/api/research/spot/**", async (route) => {
        const request = route.request();
        const url = new URL(request.url());
        const selectedTimeframe = request.method() === "POST"
          ? request.postDataJSON().timeframe
          : url.searchParams.get("timeframe");
        if (selectedTimeframe === "1m") {
          markStarted();
          await responseGate;
        }
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          headers: { "access-control-allow-origin": "*" },
          body: JSON.stringify(createSnapshot({ timeframe: selectedTimeframe, count: 50 })),
        });
      });
      if (delayedAction === "read") {
        await page.locator("#history-select").selectOption("90");
      } else {
        await page.locator("#refresh-button").click();
      }
      await started;
      await page.locator("#timeframe-select").selectOption("5m");
      await page.waitForFunction(() => document.querySelector("#snapshot-metadata").innerText.includes("Timeframe\n5m"));
      const lateResponse = page.waitForResponse((response) => {
        const url = new URL(response.url());
        return delayedAction === "read"
          ? url.pathname.endsWith("/candles") && url.searchParams.get("timeframe") === "1m"
          : url.pathname.endsWith("/refresh");
      });
      releaseResponse();
      await (await lateResponse).finished();
      await page.evaluate(() => new Promise((resolveFrame) =>
        requestAnimationFrame(() => requestAnimationFrame(resolveFrame))));
      assert.equal(await page.locator("#timeframe-select").inputValue(), "5m");
      assert.ok((await page.locator("#snapshot-metadata").innerText()).includes("Timeframe\n5m"));
      assert.match(await page.locator("#chart-container svg title").textContent(), /5m/);
    } finally {
      releaseResponse();
      await page.close();
    }
  });
}
