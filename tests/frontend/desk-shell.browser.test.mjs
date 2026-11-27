import assert from "node:assert/strict";
import { once } from "node:events";
import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { extname, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { DESK_TABS } from "../../apps/web/src/desk-state.mjs";
import { captureScreenshot, SCREENSHOT_VIEWPORTS, screenshotDir } from "./screenshots.mjs";
import { createSnapshot } from "./spot-fixture.mjs";

const require = createRequire(new URL("../../apps/web/package.json", import.meta.url));
const { chromium } = require("playwright");
const root = fileURLToPath(new URL("../../apps/web", import.meta.url));
const API = "http://127.0.0.1:8000";
const COINS = [["BTC-USDT-SPOT", "BTCUSDT"], ["ETH-USDT-SPOT", "ETHUSDT"], ["BNB-USDT-SPOT", "BNBUSDT"], ["SOL-USDT-SPOT", "SOLUSDT"], ["XRP-USDT-SPOT", "XRPUSDT"]];

async function startServer() {
  const server = createServer(async (request, response) => {
    try {
      const pathname = new URL(request.url, "http://localhost").pathname;
      const path = resolve(root, "." + (pathname === "/" ? "/index.html" : pathname));
      const rel = relative(root, path);
      if (rel.startsWith(".." + sep) || rel === "..") throw new Error("outside root");
      const body = await readFile(path);
      response.writeHead(200, { "Content-Type": { ".html": "text/html", ".mjs": "application/javascript",
        ".css": "text/css" }[extname(path)] ?? "application/octet-stream" });
      response.end(body);
    } catch { response.writeHead(404); response.end(); }
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  return { server, origin: `http://127.0.0.1:${server.address().port}` };
}

test("desk: one page, tabs route by hash without iframes, API failures fail closed with their code", async () => {
  const { server, origin } = await startServer();
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    const apiCalls = [];
    // The local API is down: every read fails, nothing is invented.
    await page.route(`${API}/**`, (route) => {
      apiCalls.push({ url: route.request().url(), method: route.request().method() });
      return route.fulfill({ status: 503, contentType: "application/json", body: "{}" });
    });
    await page.goto(`${origin}/`);
    const tabs = page.getByRole("tab");
    assert.deepEqual(await tabs.allTextContents(), ["Today", "Charts", "Strategy lab", "My results"]);
    assert.equal(await page.getByRole("tab", { name: "Today" }).getAttribute("aria-selected"), "true");
    assert.equal(await page.locator("iframe").count(), 0);
    assert.match(await page.locator("#desk-live").textContent(), /Live trading: OFF/);
    assert.match(await page.locator("#desk-mode").textContent(), /Mode: RESEARCH/);
    await page.waitForFunction(() => document.querySelector("#desk-freshness").dataset.state === "error");
    assert.match(await page.locator("#desk-freshness").textContent(), /Data: unavailable · 4h/);
    await page.waitForFunction(() => /Today view unavailable/.test(document.querySelector("#today-status").textContent));

    await page.getByRole("tab", { name: "Charts" }).click();
    assert.match(page.url(), /#charts$/);
    assert.equal(await page.locator("#panel-today").isHidden(), true);
    await page.waitForFunction(() => /Supported instruments could not be read/.test(document.querySelector("#chart-container").textContent));
    assert.equal(await page.getByRole("button", { name: "Retry supported-symbol read" }).count(), 1);

    await page.getByRole("tab", { name: "Charts" }).focus();
    await page.keyboard.press("ArrowRight");
    assert.equal(await page.getByRole("tab", { name: "Strategy lab" }).getAttribute("aria-selected"), "true");
    // UR5: the recorded verdicts are local, so they show even with the API down.
    await page.locator("#lab-verdicts .verdict-card").nth(2).waitFor();
    assert.equal(await page.locator("#lab-verdicts .verdict-card").count(), 3);

    await page.goto(`${origin}/signals.html`);
    await page.waitForURL(/index\.html#my-results$/);
    assert.equal(await page.getByRole("tab", { name: "My results" }).getAttribute("aria-selected"), "true");
    await page.getByRole("heading", { name: "Persisted research records" }).waitFor();
    assert.ok(apiCalls.every(({ method }) => method === "GET" || method === "OPTIONS"), "desk never writes");
    assert.ok(apiCalls.every(({ url }) => !url.includes("/refresh")), "desk never refreshes providers");

    // UR0: one full-page screenshot per tab and viewport (API down: honest error states).
    if (screenshotDir()) {
      for (const viewport of SCREENSHOT_VIEWPORTS) {
        await page.setViewportSize(viewport);
        for (const tab of DESK_TABS) {
          await page.goto(`${origin}/index.html#${tab.id}`);
          await page.waitForLoadState("networkidle");
          assert.ok(await captureScreenshot(page, tab.id, viewport));
        }
      }
    }
  } finally {
    await browser?.close();
    server.close();
  }
});

test("UR1/UR3/UR5: Today lists the coins and verdicts; coin and timeframe persist across tabs and reloads", async () => {
  const { server, origin } = await startServer();
  // SYNTHETIC five-coin snapshots (labelled synthetic; not market data). UUID
  // identities so the journal readback can bind to them.
  const fixtures = new Map();
  COINS.forEach(([instrumentId, symbol], index) => {
    for (const [slot, timeframe] of [[1, "4h"], [2, "1d"]]) {
      fixtures.set(`${instrumentId}|${timeframe}`, createSnapshot({
        instrumentId, symbol, timeframe, count: 60,
        snapshotId: `00000000-0000-4000-8000-0000000${slot}${index}c02`,
        qualityReportId: `00000000-0000-4000-8000-0000000${slot}${index}c03`,
      }));
    }
  });
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const reads = [];
    const posts = [];
    await page.route(`${API}/**`, async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const headers = { "access-control-allow-origin": "*", "access-control-allow-headers": "content-type", "access-control-allow-methods": "GET, POST, OPTIONS" };
      if (request.method() === "OPTIONS") return route.fulfill({ status: 204, headers });
      if (url.pathname.endsWith("/symbols")) {
        return route.fulfill({ status: 200, contentType: "application/json", headers, body: JSON.stringify({
          provider: "binance-spot-public", redistribution: "NOT_AUTHORIZED",
          instruments: COINS.map(([instrument_id, symbol]) => ({ instrument_id, symbol, venue_id: "BINANCE-SPOT", eligibility: "CHECKED_ON_EACH_REFRESH" })),
        }) });
      }
      if (url.pathname.endsWith("/candles")) {
        const instrumentId = url.pathname.split("/").at(-2);
        reads.push(`${instrumentId}|${url.searchParams.get("timeframe")}`);
        const fixture = fixtures.get(`${instrumentId}|${url.searchParams.get("timeframe")}`);
        return fixture
          ? route.fulfill({ status: 200, contentType: "application/json", headers, body: JSON.stringify(fixture) })
          : route.fulfill({ status: 404, contentType: "application/json", headers, body: "{}" });
      }
      if (url.pathname.endsWith("/decision-journal") && request.method() === "POST") {
        const body = request.postDataJSON();
        posts.push(body);
        const fixture = fixtures.get(`${body.instrument_id}|${body.timeframe}`);
        return route.fulfill({ status: 200, contentType: "application/json", headers, body: JSON.stringify({
          contract_id: "C-107", schema_version: "2", entry_id: "00000000-0000-4000-8000-0000000000e1", content_sha256: "b".repeat(64),
          request_id: body.request_id, request_sha256: "c".repeat(64), profile: "PERSONAL_SPOT_RESEARCH", operating_mode: "RESEARCH",
          origin: "LOCAL_USER_DECLARATION", identity_assurance: "LOCAL_SESSION_UNAUTHENTICATED", qualification_authorized: false,
          approval_authorized: false, execution_authorized: false, trade_facts_verified: false,
          source: { artifact_type: "C-002", artifact_id: body.snapshot_id, version: "1", content_sha256: "d".repeat(64) },
          quality_report: { artifact_type: "C-003", artifact_id: body.quality_report_id, version: "1", content_sha256: "e".repeat(64) },
          snapshot_observation: { instrument_id: body.instrument_id, timeframe: body.timeframe, as_of: fixture.as_of, last_candle_open_time: fixture.candles.at(-1).open_time, candle_count: 60, fresh_until: new Date(Date.now() + 3600_000).toISOString(), quality_status: "VALID" },
          declared_action: body.declared_action, declared_at: body.declared_at, recorded_at: new Date().toISOString(), note: body.note, supersedes: null, correction_reason: null,
        }) });
      }
      return route.fulfill({ status: 405, contentType: "application/json", headers, body: "{}" });
    });

    await page.goto(`${origin}/`);
    await page.locator("#today-rows .coin-row").nth(4).waitFor();
    assert.equal(await page.locator("#today-rows .coin-row").count(), 5);
    assert.match(await page.locator("#today-rows .coin-row").first().innerText(), /BTC[\s\S]*100\.\d{2}[\s\S]*%[\s\S]*NO_TRADE/);
    assert.match(await page.locator("#desk-freshness").innerText(), /^Data: fresh · 4h · \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC$/);
    // UR5: all three recorded verdicts with their reasons.
    assert.equal(await page.locator("#today-verdicts .verdict-row").count(), 3);
    assert.match(await page.locator("#today-verdicts").innerText(), /ema-trend-atr-stop v1[\s\S]*FAIL[\s\S]*2026-11-26[\s\S]*trend-daily-regime v1[\s\S]*FAIL[\s\S]*2026-11-27[\s\S]*range-reversion-4h v1[\s\S]*FAIL[\s\S]*2026-11-27/);
    await page.locator("#today-verdicts summary").nth(2).click();
    assert.match(await page.locator("#today-verdicts").innerText(), /profitable in too few of the test windows/);
    assert.match(await page.locator("#today-why").innerText(), /No strategy has passed its study/);

    // Choose ETH, then record a quick decision against its exact snapshot.
    await page.locator('#today-rows [data-instrument-id="ETH-USDT-SPOT"]').click();
    assert.equal(await page.locator("#today-focus-heading").innerText(), "ETH");
    await page.getByRole("button", { name: "Save declaration" }).click();
    assert.match(await page.locator("#today-decision-body").innerText(), /Choose Abstain or Trade intent first/);
    assert.equal(posts.length, 0);
    await page.locator('#today-decision-body [data-action="ABSTAIN"]').click();
    await page.locator("#today-decision-body textarea").fill("Synthetic test note: no clear trend.");
    await page.getByRole("button", { name: "Save declaration" }).click();
    await page.waitForFunction(() => /Saved unverified research declaration/.test(document.querySelector("#today-decision-body").innerText));
    assert.deepEqual(
      { instrument_id: posts[0].instrument_id, timeframe: posts[0].timeframe, snapshot_id: posts[0].snapshot_id, declared_action: posts[0].declared_action },
      { instrument_id: "ETH-USDT-SPOT", timeframe: "4h", snapshot_id: fixtures.get("ETH-USDT-SPOT|4h").snapshot_id, declared_action: "ABSTAIN" },
    );

    // The mini chart opens Charts on the same coin and timeframe.
    await page.locator("#today-chart").click();
    await page.locator("#chart-container svg").waitFor();
    assert.equal(await page.locator("#chart-heading").innerText(), "ETH/USDT");
    assert.equal(await page.locator('#timeframe-pills [data-timeframe="4h"]').getAttribute("aria-pressed"), "true");
    assert.deepEqual(await page.locator("#timeframe-pills .toolbar-shortcuts button").allInnerTexts(), ["1h", "4h", "1D"]);
    // One read per coin and timeframe: Charts reuses Today's stored snapshot.
    assert.equal(new Set(reads).size, reads.length, `duplicate reads: ${reads.join(", ")}`);

    await page.locator('#timeframe-pills [data-timeframe="1d"]').click();
    await page.waitForFunction(() => /1D/.test(document.querySelector("#desk-freshness").textContent));
    await page.reload();
    await page.locator("#chart-container svg").waitFor();
    assert.equal(await page.locator("#chart-heading").innerText(), "ETH/USDT");
    assert.equal(await page.locator('#timeframe-pills [data-timeframe="1d"]').getAttribute("aria-pressed"), "true");
    await page.getByRole("tab", { name: "Today" }).click();
    await page.locator("#today-rows .coin-row").nth(4).waitFor();
    assert.equal(await page.locator("#today-timeframe").innerText(), "1D");
    assert.equal(await page.locator('#today-rows [data-instrument-id="ETH-USDT-SPOT"]').getAttribute("aria-pressed"), "true");
    assert.equal(posts.length, 1);
  } finally {
    await browser?.close();
    server.close();
  }
});
