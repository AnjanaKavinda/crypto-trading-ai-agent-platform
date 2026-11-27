import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { extname, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { once } from "node:events";
import test from "node:test";
import { TIMEFRAME_SECONDS } from "../../apps/web/src/research-api.mjs";
import { DEFAULT_VISIBILITY, INDICATOR_IDS, PREFERENCES_KEY } from "../../apps/web/src/workspace-state.mjs";

const require = createRequire(new URL("../../apps/web/package.json", import.meta.url));
const { chromium } = require("playwright");
const webRoot = resolve(fileURLToPath(new URL("../../apps/web/", import.meta.url)));
import { DESK_TIMEFRAMES } from "../../apps/web/src/desk-state.mjs";
import { candleCount, createSnapshot, instrumentId, qualityReportId, snapshotId, symbol } from "./spot-fixture.mjs";
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

async function openWorkspace({ storedSnapshot, allowRefresh = false, visible, markers, preferences } = {}) {
  const page = await browser.newPage();
  page.setDefaultTimeout(10_000);
  const apiRequests = [];
  let stored = storedSnapshot ?? snapshot;
  {
    // Desk-wide display preferences (UR1/UR3), seeded once per new page:
    // Pro with VWAP on unless a test asks otherwise.
    await page.addInitScript(({ key, value }) => {
      if (!sessionStorage.getItem("seeded")) {
        localStorage.setItem(key, value);
        sessionStorage.setItem("seeded", "1");
      }
    }, {
      key: PREFERENCES_KEY,
      value: JSON.stringify({ mode: "pro", visible: visible ?? [...DEFAULT_VISIBILITY, "vwap"], ...preferences }),
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
    if (url.pathname.endsWith("/strategy-markers") && markers && request.method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", headers, body: JSON.stringify(markers(stored, url.searchParams)) });
      return;
    }
    await route.fulfill({ status: 405, contentType: "application/json", headers, body: "{}" });
  });
  await page.goto(`${origin}/index.html?instrument=${instrumentId}&timeframe=${stored.timeframe}#charts`);
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
  const lines = await page.locator("#chart-container polyline.indicator-line").evaluateAll((nodes) =>
    nodes.map((line) => ({
      series: [...line.classList].filter((name) => name !== "indicator-line").join(" "),
      points: (line.getAttribute("points") ?? "").trim().split(/\s+/).filter(Boolean).map((pair) =>
        pair.split(",").map(Number),
      ),
    })),
  );
  const bars = await page.locator("#chart-container rect.macd-histogram-bar").evaluateAll((nodes) => nodes.map((bar) => {
    const y = Number(bar.getAttribute("y"));
    const end = Number(bar.dataset.value) >= 0 ? y : y + Number(bar.getAttribute("height"));
    // Third value: tolerance — a near-zero bar is drawn at the 1 px minimum height.
    return [Number(bar.getAttribute("x")) + Number(bar.getAttribute("width")) / 2, end, Number(bar.getAttribute("height")) <= 1 ? 1 : 0.02];
  }));
  return bars.length ? [...lines, { series: "macd-histogram", points: bars }] : lines;
}

// Pane geometry is responsive (UR1/UR2); the chart exposes it as data attributes.
async function chartGeometry(page) {
  return page.locator("#chart-container svg").evaluate((svg) => ({
    price: { top: Number(svg.dataset.priceTop), height: Number(svg.dataset.priceHeight), min: Number(svg.dataset.priceMin), max: Number(svg.dataset.priceMax) },
    panes: Object.fromEntries([...svg.querySelectorAll("g.indicator-pane")].map((pane) => [pane.dataset.paneKey, {
      top: Number(pane.dataset.top), height: Number(pane.dataset.height), min: Number(pane.dataset.min), max: Number(pane.dataset.max),
    }])),
  }));
}

async function waitForLoadedSnapshot(page) {
  await page.locator("#chart-container svg").waitFor({ state: "visible" });
  await page.locator("#snapshot-status").waitFor();
  await openDrawer(page);
}

// The relocated details (analyses, OHLCV, provenance, indicator details) sit
// in collapsed drawer sections; open them as the owner would.
async function openDrawer(page) {
  await page.evaluate(() => document.querySelectorAll("#chart-drawer details").forEach((details) => { details.open = true; }));
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

test("VWAP overlay has its own pill, independent of indicator toggles, without refresh", async () => {
  const { page, apiRequests } = await openWorkspace({
    storedSnapshot: createSnapshot({ count: 50 }),
    visible: ["ema-20", "vwap"],
  });
  try {
    await waitForLoadedSnapshot(page);
    assert.equal(await page.locator("#chart-container polyline.spot-vwap-line").count(), 1);
    assert.equal(await page.locator('#indicator-toolbar [data-pill="VWAP"]').getAttribute("aria-pressed"), "true");
    await page.getByRole("checkbox", { name: "EMA 20", exact: true }).uncheck();
    assert.equal(await page.locator("#chart-container polyline.ema-20").count(), 0);
    assert.equal(await page.locator("#chart-container polyline.spot-vwap-line").count(), 1);
    // UR3: the pill and the checkbox always agree.
    assert.equal(await page.locator('#indicator-toolbar [data-pill="EMA20"]').getAttribute("aria-pressed"), "false");
    await page.locator('#indicator-toolbar [data-pill="VWAP"]').click();
    assert.equal(await page.locator("#chart-container polyline.spot-vwap-line").count(), 0);
    await page.locator('#indicator-toolbar [data-pill="VWAP"]').click();
    assert.equal(await page.locator("#chart-container polyline.spot-vwap-line").count(), 1);
    // VWAP is not one of the Beginner essentials.
    await page.getByRole("button", { name: "Beginner", exact: true }).click();
    assert.equal(await page.locator("#chart-container polyline.spot-vwap-line").count(), 0);
    assert.equal(await page.locator('#indicator-toolbar [data-pill="VWAP"]').count(), 0);
    assert.equal(apiRequests.filter((request) => request.method === "POST").length, 0);
  } finally {
    await page.close();
  }
});

test("indicator provenance links use the loaded response and the synthetic example stays separate", { timeout: 60_000 }, async () => {
  const { page, apiRequests } = await openWorkspace();
  try {
    // U5b: the 501-candle default reads the stored snapshot on first load.
    await waitForLoadedSnapshot(page);

    const provenanceText = await page.locator("#snapshot-metadata").innerText();
    const sourceText = await page.locator("#source-list").innerText();
    for (const identity of [
      symbol,
      instrumentId,
      "1h",
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
      `${symbol}.*${instrumentId}.*1h.*${snapshotId}.*${qualityReportId}`,
    ));
    await firstLink.focus();
    await page.keyboard.press("Shift+Tab");
    await page.keyboard.press("Tab");
    assert.equal(await firstLink.evaluate((link) => document.activeElement === link), true);
    assert.equal(await firstLink.evaluate((link) => link.matches(":focus-visible")), true);
    await firstLink.click();
    assert.equal(new URL(page.url()).hash, "#snapshot-provenance");
    // An in-page anchor never switches the desk tab.
    assert.equal(await page.getByRole("tab", { name: "Charts" }).getAttribute("aria-selected"), "true");
    assert.equal(await page.locator("#snapshot-provenance").getAttribute("open"), "");

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
        `${symbol}.*${instrumentId}.*1h.*${snapshotId}.*${qualityReportId}`,
      ));
    }

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
    // U5b: the 501-candle default reads the stored snapshot on first load.
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
    const candleXs = await page.locator("#chart-container line.candle-wick").evaluateAll((wicks) =>
      wicks.map((wick) => Number(wick.getAttribute("x1"))),
    );
    assert.equal(candleXs.length, candleCount);

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
    const geometry = await chartGeometry(page);
    assert.ok(Math.abs(geometry.price.min - priceRange.min) < 1e-9 && Math.abs(geometry.price.max - priceRange.min - priceRange.span) < 1e-9);
    assert.deepEqual(Object.keys(geometry.panes), ["atr", "realized-volatility", "rsi", "macd", "stochastic", "cci"]);
    for (const line of rendered) {
      const className = line.series;
      const expected = seriesResults[className];
      assert.equal(line.points.length, expected.length, `${className} point count`);
      expected.forEach(([candleEnd, exactValue, axis], index) => {
        const candle = candleIndex.get(Date.parse(candleEnd));
        assert.equal(candle, index, `${className} point timestamp must match its candle`);
        const expectedX = candleXs[candle];
        const value = Number(exactValue);
        const { price } = geometry;
        const panel = geometry.panes[axis];
        const inner = panel ? panel.height - 4 : 0;
        const expectedY = axis === "price"
          ? price.top + price.height - (value - price.min) / (price.max - price.min) * price.height
          : panel.top + 2 + inner - (value - panel.min) / (panel.max - panel.min) * inner;
        assert.ok(Math.abs(line.points[index][0] - expectedX) < 0.02, `${className} x alignment at candle ${index}`);
        assert.ok(Math.abs(line.points[index][1] - expectedY) <= (line.points[index][2] ?? 0.02), `${className} value at candle ${index}`);
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
    const beginnerClasses = ["atr-line", "bollinger-lower", "bollinger-middle", "bollinger-upper", "ema-20", "ema-50", "rsi-line"].sort();
    await page.getByRole("button", { name: "Beginner", exact: true }).click();
    assert.deepEqual((await readSeries(page)).map((line) => line.series).sort(), beginnerClasses);
    await page.getByRole("button", { name: "Pro", exact: true }).click();
    assert.deepEqual((await readSeries(page)).map((line) => line.series).sort(), expectedClasses);
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
    // U5b: the 501-candle default reads the stored snapshot on first load.
    await waitForLoadedSnapshot(page);
    assert.equal(await page.locator("#chart-container svg").count(), 1);

    await page.locator("#history-select").selectOption("250");
    await page.getByText("Research request failed.", { exact: true }).waitFor();
    assert.equal(await page.locator("#chart-container svg").count(), 0);
    assert.match(await page.locator("#chart-container").innerText(), /stored 1h snapshot.*maximum of 250/);
    assert.match(await page.locator("#chart-container").innerText(), /larger history bound.*explicitly refresh this same selector/);
    assert.doesNotMatch(await page.locator("body").innerText(), /PRIVATE|must not appear/);
    assert.equal(await page.locator("#snapshot-metadata").innerText(), "Instrument / venue\nNo snapshot loaded");
    assert.equal(await page.locator("#indicator-groups .indicator-provenance-link").count(), 0);
    assert.ok(apiRequests.some((request) => request.pathname.endsWith("/candles") && request.limit === "250"));
    assert.equal(apiRequests.filter((request) => request.pathname.endsWith("/refresh")).length, 0);
  } finally {
    await page.close();
  }
});

for (const timeframe of DESK_TIMEFRAMES) {
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
        assert.equal(await page.locator(`#timeframe-pills [data-timeframe="${timeframe}"]`).getAttribute("aria-pressed"), "true");
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
      assert.equal(await page.locator("#history-select").inputValue(), "501");
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
      assert.equal(await page.locator("#snapshot-metadata").innerText(), "Instrument / venue\nNo snapshot loaded");
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
      assert.match(await page.locator("#chart-container svg > title").textContent(), /5m/);
    } finally {
      releaseResponse();
      await page.close();
    }
  });
}

test("chart workspace zooms, pans, switches scale and shows the exact last close", async () => {
  const fixture = createSnapshot({ count: 50 });
  const { page, apiRequests } = await openWorkspace({ storedSnapshot: fixture });
  try {
    await waitForLoadedSnapshot(page);
    const wicks = () => page.locator("#chart-container line.candle-wick").count();
    const range = page.locator("#chart-view-range");
    assert.equal(await wicks(), 50);
    assert.match(await range.innerText(), /Showing candles 1–50 of 50 · scale: Auto/);
    assert.equal(
      await page.locator("#chart-container .last-price-tag").getAttribute("data-last-price"),
      fixture.candles.at(-1).metrics.close.value,
    );
    // Synthetic fixture: last close "100.7400" is shown at 2 dp, exact on hover.
    assert.equal(await page.locator("#chart-container .last-price-text").textContent(), "100.74");
    assert.match(await page.locator("#chart-container .last-price-tag title").textContent(), /100\.7400 USDT/);
    await page.locator("#chart-container svg").focus();
    await page.keyboard.press("End");
    await page.keyboard.press("ArrowLeft");
    const inspector = page.locator("#chart-inspector");
    assert.match(await inspector.textContent(), / C 100\.73 USDT/);
    assert.match(await inspector.getAttribute("data-exact"), /Close: 100\.7300 USDT/);
    assert.match(await inspector.getAttribute("title"), /^Exact returned values: /);
    assert.match(await page.locator("#market-trades").innerText(), /Market trades — unavailable[\s\S]*#355/);
    const requestsBefore = apiRequests.length;
    await page.locator('[data-chart-action="zoom-in"]').click();
    assert.equal(await wicks(), 25);
    assert.match(await range.innerText(), /Showing candles 26–50 of 50/);
    await page.locator('[data-chart-action="pan-left"]').click();
    assert.match(await range.innerText(), /Showing candles 20–44 of 50/);
    await page.locator('[data-chart-action="scale-percent"]').click();
    assert.equal(await page.locator('[data-chart-action="scale-percent"]').getAttribute("aria-pressed"), "true");
    assert.match(await page.locator("#chart-container .price-axis-tick").first().textContent(), /%$/);
    await page.locator('[data-chart-action="scale-log"]').click();
    assert.match(await range.innerText(), /scale: Log/);
    await page.locator("#chart-container svg").focus();
    await page.keyboard.press("-");
    assert.equal(await wicks(), 50);
    await page.locator('[data-chart-action="reset"]').click();
    assert.match(await range.innerText(), /Showing candles 1–50 of 50 · scale: Auto/);
    assert.equal(apiRequests.length, requestsBefore, "view controls must not issue API requests");
  } finally {
    await page.close();
  }
});

test("chart workspace timeframe pills, markets list, volume average and market-trades notice", async () => {
  const fixture = createSnapshot({ count: 50 });
  const { page, apiRequests } = await openWorkspace({ storedSnapshot: fixture });
  try {
    await waitForLoadedSnapshot(page);
    // Backend prior-20 trailing volume average is drawn from candle 21 onward.
    const line = page.locator("#chart-container polyline.volume-average-line");
    assert.equal(await line.count(), 1);
    const points = (await line.getAttribute("points")).trim().split(/\s+/);
    assert.equal(points.length, 30);
    assert.match(await page.locator("#chart-container .legend-volume-average-line").textContent(), /Prior-20 average volume · backend/);
    // Markets list comes from the API allowlist and marks the selection.
    const market = page.locator(`#markets-list [data-instrument-id="${instrumentId}"]`);
    assert.equal(await market.textContent(), symbol);
    assert.equal(await market.getAttribute("aria-pressed"), "true");
    assert.match(await page.locator("#markets-list-count").textContent(), /Markets \(1\)/);
    // Market trades are unavailable, never inferred.
    assert.match(await page.locator("#market-trades").innerText(), /unavailable[\s\S]*#355/);
    // Weekly/monthly pills are disabled with a reason; live pills load that timeframe.
    for (const value of ["1w", "1M"]) {
      const pill = page.locator(`#timeframe-pills [data-timeframe="${value}"]`);
      assert.equal(await pill.isDisabled(), true);
      assert.match(await pill.getAttribute("title"), /not served by the local research API/);
    }
    assert.equal(await page.locator('#timeframe-pills [data-timeframe="4h"]').getAttribute("aria-pressed"), "false");
    const before = apiRequests.length;
    await page.locator('#timeframe-pills [data-timeframe="4h"]').click();
    await page.waitForFunction(() => document.querySelector("#timeframe-select").value === "4h");
    assert.equal(await page.locator('#timeframe-pills [data-timeframe="4h"]').getAttribute("aria-pressed"), "true");
    const loads4h = () => apiRequests.slice(before).some((item) => item.pathname.endsWith("/candles") && item.timeframe === "4h");
    for (let attempt = 0; attempt < 50 && !loads4h(); attempt += 1) await page.waitForTimeout(100);
    assert.ok(loads4h());
    assert.ok(apiRequests.every((item) => item.method === "GET"), "pills and markets must only read");
  } finally {
    await page.close();
  }
});

test("indicator toolbar pills toggle backend overlays and disable not-ready indicators with reasons", async () => {
  const { page, apiRequests } = await openWorkspace({ storedSnapshot: createSnapshot({ count: 50 }) });
  try {
    await waitForLoadedSnapshot(page);
    const pill = (short) => page.locator(`#indicator-toolbar [data-pill="${short}"]`);
    assert.equal(await pill("EMA20").getAttribute("aria-pressed"), "true");
    assert.equal(await pill("RSI").getAttribute("aria-pressed"), "false");
    const before = apiRequests.length;
    await pill("RSI").click();
    assert.equal(await pill("RSI").getAttribute("aria-pressed"), "true");
    assert.ok((await readSeries(page)).some((line) => line.series === "rsi-line"));
    assert.equal(await page.locator("#view-mode").textContent(), "Pro view");
    await pill("EMA20").click();
    assert.equal(await pill("EMA20").getAttribute("aria-pressed"), "false");
    assert.ok(!(await readSeries(page)).some((line) => line.series === "ema-20"));
    for (const short of ["SMA", "OBV", "CVD", "HEAT"]) {
      assert.equal(await pill(short).isDisabled(), true, short);
      assert.match(await pill(short).getAttribute("title"), /Connect|To build|Needs trades|Needs order book/);
    }
    assert.equal(await pill("VWAP").isDisabled(), false);
    await pill("VWAP").click();
    await page.waitForFunction(() => document.activeElement?.dataset?.analysisKey === "vwap");
    assert.equal(apiRequests.length, before, "toolbar pills must not issue API requests");
  } finally {
    await page.close();
  }
});

test("drawing tools place browser-only annotations that persist and clear without API requests", async () => {
  const { page, apiRequests } = await openWorkspace({ storedSnapshot: createSnapshot({ count: 50 }) });
  try {
    await waitForLoadedSnapshot(page);
    const clickChart = async (xFraction, viewY) => {
      const svg = page.locator("#chart-container svg");
      const box = await svg.boundingBox();
      const [, , viewWidth, viewHeight] = (await svg.getAttribute("viewBox")).split(/\s+/).map(Number);
      const plotLeft = 150;
      const plotWidth = viewWidth - 150 - 125;
      await page.mouse.click(
        box.x + ((plotLeft + xFraction * plotWidth) / viewWidth) * box.width,
        box.y + (viewY / viewHeight) * box.height,
      );
    };
    const count = () => page.locator("#chart-container .user-drawings").getAttribute("data-drawing-count");
    assert.equal(await count(), "0");
    const before = apiRequests.length;
    await page.locator('[data-drawing-tool="hline"]').click();
    assert.equal(await page.locator('[data-drawing-tool="hline"]').getAttribute("aria-pressed"), "true");
    await clickChart(0.5, 150);
    assert.equal(await count(), "1");
    await page.locator('[data-drawing-tool="fib"]').click();
    await clickChart(0.2, 60);
    assert.match(await page.locator("#drawing-status").textContent(), /swing end \(2 of 2\)/);
    await clickChart(0.7, 240);
    assert.equal(await count(), "2");
    assert.equal(await page.locator("#chart-container .drawing-fib .drawing-fib-level").count(), 7);
    assert.match(await page.locator("#chart-container .drawing-fib title").textContent(), /Your annotation — not evidence/);
    assert.equal(apiRequests.length, before, "drawing must not issue API requests");
    // Drawings are anchored to candle time + price, so they survive zoom.
    await page.locator('[data-chart-action="zoom-in"]').click();
    assert.equal(await count(), "2");
    await page.reload();
    await waitForLoadedSnapshot(page);
    assert.equal(await count(), "2");
    const afterReload = apiRequests.length;
    await page.locator('[data-drawing-tool="clear"]').click();
    assert.equal(await count(), "0");
    assert.equal(apiRequests.length, afterReload, "clear must not issue API requests");
    assert.ok(apiRequests.every((item) => item.method === "GET"));
  } finally {
    await page.close();
  }
});

function syntheticMarkers(stored, params) {
  // SYNTHETIC marker response bound to the fixture snapshot; not market data.
  const fact = (value) => ({ label: "VERIFIED_FACT", value, reason: null });
  const proposal = (value, reason) => ({ label: "RESEARCH_PROPOSAL", value, reason });
  const sized = params.get("account_size") && params.get("risk_pct");
  return {
    instrument_id: stored.instrument_id,
    symbol: stored.symbol,
    timeframe: stored.timeframe,
    as_of: stored.as_of,
    snapshot_id: stored.snapshot_id,
    data_quality_status: "VALID",
    quality_report_id: stored.data_quality.report_id,
    strategy: { strategy_id: "ema-trend-atr-stop", version: 1, content_sha256: "c".repeat(64), parameters: {} },
    costs: { fee_bps_per_side: "10", slippage_bps_per_side: "5", basis: "assumption", label: "RESEARCH_PROPOSAL" },
    evidence_scope: "Replays ema-trend-atr-stop v1 over this snapshot only.",
    not_applicable: { leverage: { label: "NOT_APPLICABLE", value: null, reason: "Spot research, no leverage" } },
    status: "AVAILABLE",
    reason_code: null,
    position: "FLAT",
    markers: [
      {
        side: "BUY", status: "FILLED", time: fact(stored.candles[20].open_time), fill_time: fact(stored.candles[21].open_time),
        conditions: [{ condition: "EMA20 closed above EMA50 after being on the other side", met: true, ema_20: fact("101.5") }],
        entry_open: fact(stored.candles[21].metrics.open.value),
        modelled_entry_fill: proposal("101.05", "next candle open plus modelled slippage"),
        stop: proposal("97.05", "modelled entry fill minus stop distance"),
        position_size: sized
          ? { quantity: proposal("2.50000000", "(account x risk%) / (entry - stop), before fees"), capped: false }
          : { quantity: { label: "UNAVAILABLE", value: null, reason: "enter account size and risk %" }, capped: null },
      },
      {
        side: "SELL", status: "FILLED", exit_reason: "SIGNAL_EXIT", time: fact(stored.candles[30].open_time),
        fill_time: fact(stored.candles[31].open_time),
        conditions: [{ condition: "EMA20 closed below EMA50 after being on the other side", met: true }],
        net_return: proposal("-0.012", "after modelled fees/slippage"),
      },
    ],
  };
}

test("strategy markers draw on the chart and the evidence panel shows labelled values and sizing", async () => {
  const fixture = createSnapshot({ count: 50 });
  const { page, apiRequests } = await openWorkspace({ storedSnapshot: fixture, markers: syntheticMarkers });
  const markerUrls = [];
  page.on("request", (request) => { if (request.url().includes("/api/research/spot/") && request.url().includes("/strategy-markers?")) markerUrls.push(new URL(request.url())); });
  try {
    await waitForLoadedSnapshot(page);
    // U5b: SIGNALS is off by default — no markers are read or drawn.
    const signals = page.locator('#indicator-toolbar [data-pill="SIGNALS"]');
    assert.equal(await signals.getAttribute("aria-pressed"), "false");
    assert.equal(await page.locator("#chart-container polygon.strategy-marker").count(), 0);
    assert.equal(markerUrls.length, 0, markerUrls.map(String).join(" "));
    assert.equal(await page.locator("#chart-signal-banner").isHidden(), true);
    // Turned on: the strategy for this timeframe is named explicitly and its FAILED verdict is shown.
    await signals.click();
    await page.locator("#chart-container polygon.strategy-marker-buy").waitFor();
    assert.equal(markerUrls[0].searchParams.get("strategy"), "ema-trend-atr-stop");
    assert.equal(markerUrls[0].searchParams.get("version"), "1");
    assert.equal(await page.locator("#marker-strategy").inputValue(), "ema-trend-atr-stop@1");
    assert.equal(await page.locator("#chart-signal-banner").innerText(),
      "ema-trend-atr-stop v1 — FAILED verdict (2026-11-26). Illustration only, not a trade signal.");
    assert.match(await page.locator("#markers-banner").innerText(), /FAILED verdict \(2026-11-26\)[\s\S]*did not beat simply holding cash/);
    assert.equal(await page.locator("#chart-container polygon.strategy-marker-sell").count(), 1);
    const body = page.locator("#markers-body");
    assert.match(await body.innerText(), /2 markers · position FLAT/);
    assert.match(await page.locator("#marker-detail").innerText(), /Modelled entry fill[\s\S]*101\.05[\s\S]*Research proposal/);
    assert.match(await page.locator("#marker-detail").innerText(), /enter account size and risk %/);
    await page.locator("#chart-container polygon.strategy-marker-sell").click();
    // Display precision with the exact backend value kept on hover.
    assert.match(await page.locator("#marker-detail").innerText(), /Net return[\s\S]*−1\.20%/);
    assert.equal(await page.locator('#marker-detail [data-exact="-0.012"]').getAttribute("title"), "Exact value: -0.012");
    await page.locator("#sizing-account").fill("abc");
    await page.locator("#sizing-form button").click();
    assert.match(await page.locator("#sizing-error").innerText(), /positive USDT amount/);
    await page.locator("#sizing-account").fill("1000");
    await page.locator("#sizing-risk").fill("1");
    await page.locator("#sizing-form button").click();
    await page.locator('#markers-body [data-marker-index="0"]').click();
    await page.locator('#marker-detail [data-exact="2.50000000"]').waitFor();
    const markerReads = apiRequests.filter((item) => item.pathname.endsWith("/strategy-markers"));
    assert.equal(markerReads.length, 2);
    assert.ok(apiRequests.every((item) => item.method === "GET"));
  } finally {
    await page.close();
  }
});

test("record my decision binds the journal to the exact current VALID snapshot on screen", async () => {
  // Synthetic fixture: identifiers rewritten to UUIDs so the C-107v2 readback can bind to them.
  const snapshotUuid = "00000000-0000-4000-8000-00000000c002";
  const reportUuid = "00000000-0000-4000-8000-00000000c003";
  const fixture = JSON.parse(JSON.stringify(createSnapshot({ count: 50 })).replaceAll(snapshotId, snapshotUuid).replaceAll(qualityReportId, reportUuid));
  const { page } = await openWorkspace({ storedSnapshot: fixture });
  const posts = [];
  const entries = [];
  await page.route("http://127.0.0.1:8000/api/research/decision-journal**", async (route) => {
    const request = route.request();
    const headers = { "content-type": "application/json", "access-control-allow-origin": "*", "access-control-allow-methods": "GET, POST, OPTIONS", "access-control-allow-headers": "content-type" };
    if (request.method() === "OPTIONS") { await route.fulfill({ status: 204, headers }); return; }
    if (request.method() === "GET") { await route.fulfill({ status: 200, headers, body: JSON.stringify({ items: entries, next_cursor: null }) }); return; }
    const body = request.postDataJSON();
    posts.push(body);
    const recordedAt = new Date().toISOString();
    const entry = {
      contract_id: "C-107", schema_version: "2", entry_id: "00000000-0000-4000-8000-0000000000e1", content_sha256: "b".repeat(64),
      request_id: body.request_id, request_sha256: "c".repeat(64), profile: "PERSONAL_SPOT_RESEARCH", operating_mode: "RESEARCH",
      origin: "LOCAL_USER_DECLARATION", identity_assurance: "LOCAL_SESSION_UNAUTHENTICATED", qualification_authorized: false,
      approval_authorized: false, execution_authorized: false, trade_facts_verified: false,
      source: { artifact_type: "C-002", artifact_id: body.snapshot_id, version: "1", content_sha256: "d".repeat(64) },
      quality_report: { artifact_type: "C-003", artifact_id: body.quality_report_id, version: "1", content_sha256: "e".repeat(64) },
      snapshot_observation: { instrument_id: body.instrument_id, timeframe: body.timeframe, as_of: fixture.as_of, last_candle_open_time: fixture.candles.at(-1).open_time, candle_count: 50, fresh_until: new Date(Date.now() + 3600_000).toISOString(), quality_status: "VALID" },
      declared_action: body.declared_action, declared_at: body.declared_at, recorded_at: recordedAt, note: body.note, supersedes: null, correction_reason: null,
    };
    entries.push(entry);
    await route.fulfill({ status: 200, headers, body: JSON.stringify(entry) });
  });
  try {
    await waitForLoadedSnapshot(page);
    // The drawer's quick form (Abstain | Trade intent + note) is ready for the snapshot on screen.
    await page.locator('#decision-body [data-action="ABSTAIN"]').waitFor();
    assert.match(await page.locator("#decision-note").innerText(), new RegExp(snapshotUuid));
    assert.equal(posts.length, 0);
    await page.locator('#decision-body [data-action="ABSTAIN"]').click();
    await page.locator("#decision-body textarea").first().fill("No clear trend; staying out.");
    await page.getByRole("button", { name: "Save declaration", exact: true }).click();
    await page.waitForFunction(() => document.querySelector("#decision-body")?.innerText.includes("Saved unverified research declaration"));
    assert.equal(posts.length, 1);
    assert.deepEqual(
      { instrument_id: posts[0].instrument_id, timeframe: posts[0].timeframe, snapshot_id: posts[0].snapshot_id, quality_report_id: posts[0].quality_report_id, declared_action: posts[0].declared_action },
      { instrument_id: instrumentId, timeframe: "1h", snapshot_id: snapshotUuid, quality_report_id: reportUuid, declared_action: "ABSTAIN" },
    );
    assert.equal(Object.hasOwn(posts[0], "source"), false);
    const text = await page.locator("#decision-body").innerText();
    assert.match(text, new RegExp("Request key \\(retain for recovery\\): " + posts[0].request_id));
    assert.match(text, /Quality report: 00000000-0000-4000-8000-00000000c003 · VALID/);
    await page.getByRole("button", { name: "Read declaration history", exact: true }).click();
    await page.getByRole("button", { name: "Append correction", exact: true }).waitFor();
  } finally {
    await page.close();
  }
});

test("UR1: Beginner|Pro switch — 7 pills, 6 tools and a plain reading in Beginner; everything in Pro; remembered", async () => {
  const { page } = await openWorkspace({
    storedSnapshot: createSnapshot({ count: 60 }),
    preferences: { mode: "beginner", visible: [...DEFAULT_VISIBILITY] },
  });
  try {
    await waitForLoadedSnapshot(page);
    assert.equal(await page.locator("#beginner-button").getAttribute("aria-pressed"), "true");
    assert.deepEqual(await page.locator("#indicator-toolbar .indicator-pill").allInnerTexts(), ["SIGNALS", "EMA20", "EMA50", "BB", "RSI", "ATR", "VOL"]);
    assert.equal(await page.locator("#drawing-tools .drawing-tool").count(), 6);
    assert.match(await page.locator("#plain-reading").innerText(), /Trend: [\s\S]*Momentum: RSI[\s\S]*Volatility: ATR[\s\S]*Not a signal/);
    assert.equal(await page.locator("#indicator-details").isHidden(), true);
    await page.getByRole("button", { name: "Pro", exact: true }).click();
    assert.equal(await page.locator("#indicator-toolbar .indicator-pill").count(), 32);
    assert.equal(await page.locator("#drawing-tools .drawing-tool").count(), 11);
    assert.equal(await page.locator("#indicator-details").isHidden(), false);
    await page.reload();
    await waitForLoadedSnapshot(page);
    assert.equal(await page.locator("#pro-button").getAttribute("aria-pressed"), "true");
    assert.equal(await page.locator("#indicator-toolbar .indicator-pill").count(), 32);
  } finally {
    await page.close();
  }
});

test("UR1: full screen keeps pills, mode, timeframe and tools; the drawer opens as an overlay; Esc exits", async () => {
  const { page } = await openWorkspace({ storedSnapshot: createSnapshot({ count: 60 }) });
  try {
    await waitForLoadedSnapshot(page);
    const button = page.locator("#fullscreen-button");
    await button.click();
    assert.equal(await button.innerText(), "✕ Exit full screen");
    assert.match(await page.locator("#charts-workspace").getAttribute("class"), /is-fullscreen/);
    for (const selector of ["#indicator-toolbar", "#pro-button", "#timeframe-pills", "#drawing-tools", "#chart-container svg"]) {
      assert.equal(await page.locator(selector).isVisible(), true, selector);
    }
    assert.equal(await page.locator("#chart-drawer").isVisible(), false);
    await page.locator("#drawer-toggle").click();
    assert.equal(await page.locator("#chart-drawer").isVisible(), true);
    assert.equal(await page.locator("#chart-drawer").evaluate((node) => getComputedStyle(node).position), "fixed");
    await page.keyboard.press("Escape");
    assert.equal(await button.innerText(), "⛶ Full screen");
    assert.doesNotMatch(await page.locator("#charts-workspace").getAttribute("class"), /is-fullscreen/);
    assert.equal(await page.locator("#chart-drawer").isVisible(), true, "the drawer state from before full screen is restored");
  } finally {
    await page.close();
  }
});
