import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { extname, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { once } from "node:events";
import test from "node:test";

const require = createRequire(new URL("../../apps/web/package.json", import.meta.url));
const { chromium } = require("playwright");
const webRoot = resolve(fileURLToPath(new URL("../../apps/web/", import.meta.url)));
const instrumentId = "BTC-USDT-SPOT";
const symbol = "BTCUSDT";
const candleCount = 501;
const intervalMs = 60_000;
const qualityReportId = "fixture-report-btc-1m";
const snapshotId = "fixture-snapshot-btc-1m";

function decimal(value) {
  return value.toFixed(4);
}

function createSnapshot() {
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
    timeframe: "1m",
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

  return {
    instrument_id: instrumentId,
    symbol,
    venue_id: "BINANCE-SPOT",
    timeframe: "1m",
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

async function openWorkspace() {
  const page = await browser.newPage();
  const apiRequests = [];
  await page.route("http://127.0.0.1:8000/api/research/spot/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    apiRequests.push({ method: request.method(), pathname: url.pathname, limit: url.searchParams.get("limit") });
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
      if (url.searchParams.get("limit") === "501") {
        await route.fulfill({ status: 200, contentType: "application/json", headers, body: JSON.stringify(snapshot) });
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
        }),
      });
      return;
    }
    await route.fulfill({ status: 405, contentType: "application/json", headers, body: "{}" });
  });
  await page.goto(`${origin}/index.html?instrument=${instrumentId}&timeframe=1m`);
  return { page, apiRequests };
}

function expectedPriceRange() {
  const values = [];
  for (const candle of snapshot.candles) {
    values.push(Number(candle.metrics.low.value), Number(candle.metrics.high.value));
  }
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
    const expectedClasses = Object.values(seriesGroups).flat().sort();
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
    const beginnerClasses = ["atr-line", "ema-20", "ema-50"].sort();
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
    assert.match(await page.locator("#chart-container").innerText(), /rejected the selector or history bound/);
    assert.equal(await page.locator("#snapshot-metadata").innerText(), "Instrument / venue\nNot yet available");
    assert.ok(apiRequests.some((request) => request.pathname.endsWith("/candles") && request.limit === "250"));
    assert.equal(apiRequests.filter((request) => request.pathname.endsWith("/refresh")).length, 0);
  } finally {
    await page.close();
  }
});
