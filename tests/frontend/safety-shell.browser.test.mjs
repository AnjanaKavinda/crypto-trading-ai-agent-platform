// U9 (#156, focused): safety, offline and accessibility checks across the desk.
import assert from "node:assert/strict";
import { once } from "node:events";
import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { extname, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { createSnapshot } from "./spot-fixture.mjs";

const require = createRequire(new URL("../../apps/web/package.json", import.meta.url));
const { chromium } = require("playwright");
const root = fileURLToPath(new URL("../../apps/web", import.meta.url));
const API = "http://127.0.0.1:8000";
const COINS = [["BTC-USDT-SPOT", "BTCUSDT"], ["ETH-USDT-SPOT", "ETHUSDT"], ["BNB-USDT-SPOT", "BNBUSDT"], ["SOL-USDT-SPOT", "SOLUSDT"], ["XRP-USDT-SPOT", "XRPUSDT"]];
const TABS = ["Today", "Charts", "Strategy lab", "My results"];
// Any control that could look like trading.
const TRADING_CONTROL = /\b(buy|sell|order|execute|approve|place trade|submit trade|go live)\b/i;

let server;
let origin;
let browser;
test.before(async () => {
  server = createServer(async (request, response) => {
    try {
      const pathname = new URL(request.url, "http://localhost").pathname;
      const path = resolve(root, "." + (pathname === "/" ? "/index.html" : pathname));
      const rel = relative(root, path);
      if (rel.startsWith(".." + sep) || rel === "..") throw new Error("outside root");
      const body = await readFile(path);
      response.writeHead(200, { "Content-Type": { ".html": "text/html", ".mjs": "application/javascript", ".css": "text/css" }[extname(path)] ?? "application/octet-stream" });
      response.end(body);
    } catch { response.writeHead(404); response.end(); }
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  origin = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ headless: true });
});
test.after(async () => {
  await browser?.close();
  server?.close();
});

// SYNTHETIC API (labelled synthetic; not market data or real results). The
// forward record is deliberately FORWARD_PASS with an open BTC signal: even a
// green card must offer no order control.
function syntheticApi(page) {
  const requests = [];
  const forward = (strategy, stage, reason, signals = {}) => ({
    label: "SIMULATED RESEARCH EVIDENCE - NOT AN ORDER",
    strategy: { strategy_id: strategy, version: 1, content_sha256: "a".repeat(64) },
    protocol: { prospective_start: "2026-11-26T00:00:00Z" },
    signals: Object.fromEntries(COINS.map(([, symbol]) => [symbol, signals[symbol] ?? []])),
    stage, reason,
    forward: { label: "SIMULATED", closed_trades: 3, win_rate: "0.6667", expectancy: "0.0123", max_drawdown: "0.0400", review_point: { trades: 15, date: "2027-05-26T00:00:00Z", reached: true } },
    authority: { qualification_authorized: false, approval_authorized: false, execution_authorized: false },
    historical_verdict: null,
  });
  const verdict = {
    contract_id: "C-109", verdict_id: "00000000-0000-4000-8000-000000000109", strategy_id: "synthetic-strategy", strategy_version: "1",
    verdict_status: "FAIL", protocol_id: "spot-walk-forward-prospective", protocol_version: "2",
    report_created_at: "2026-01-01T00:00:00Z", recorded_at: "2026-01-02T00:00:00Z", development_max_drawdown: "0.25",
    qualification_authorized: false, approval_authorized: false, execution_authorized: false,
    datasets: COINS.map(([, symbol]) => ({ symbol, timeframe: "1d", content_sha256: "c".repeat(64) })),
    verdict_reasons: ["DOES_NOT_BEAT_CASH"],
  };
  return page.route(`${API}/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    requests.push(request.method());
    const headers = { "access-control-allow-origin": "*" };
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", headers, body: JSON.stringify(body) });
    if (url.pathname.endsWith("/symbols")) {
      return json({ provider: "binance-spot-public", redistribution: "NOT_AUTHORIZED", instruments: COINS.map(([instrument_id, symbol]) => ({ instrument_id, symbol, venue_id: "BINANCE-SPOT", eligibility: "CHECKED_ON_EACH_REFRESH" })) });
    }
    if (url.pathname.endsWith("/candles")) {
      const instrumentId = url.pathname.split("/").at(-2);
      const symbol = COINS.find(([id]) => id === instrumentId)[1];
      return json(createSnapshot({ instrumentId, symbol, timeframe: url.searchParams.get("timeframe"), count: 60 }));
    }
    if (url.pathname.endsWith("/forward/verdicts")) return json({ items: [verdict] });
    if (url.pathname.endsWith("/forward/trend-daily-regime")) {
      return json(forward("trend-daily-regime", "FORWARD_PASS", "PREREGISTERED_FORWARD_CRITERIA_MET", {
        BTCUSDT: [{ status: "OPEN", signal_candle_open_time: "2026-12-01T00:00:00Z", simulated_entry_fill: { label: "SIMULATED", value: "100.00" }, simulated_initial_stop: { label: "SIMULATED", value: "95.00" } }],
      }));
    }
    if (url.pathname.endsWith("/forward/range-reversion-4h")) return json(forward("range-reversion-4h", "FAIL", "HISTORICAL_FAIL"));
    return json({}, 405);
  }).then(() => requests);
}

test("U9: no order or execution control exists on any tab and Live trading OFF is always visible", async () => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.setDefaultTimeout(15_000);
  const requests = await syntheticApi(page);
  try {
    await page.goto(`${origin}/`);
    await page.locator('#signal-cards .signal-card[data-state="green"]').waitFor();
    for (const tab of TABS) {
      await page.getByRole("tab", { name: tab }).click();
      assert.equal(await page.locator("#desk-live").isVisible(), true, `${tab}: Live trading OFF visible`);
      assert.match(await page.locator("#desk-live").innerText(), /Live trading: OFF/);
      if (tab === "Charts") await page.locator("#chart-container svg").waitFor();
      // Visible text and accessible name of every control. The SIGNALS pill is
      // exempt: it only shows or hides illustrated BUY/SELL markers on the chart.
      const controls = await page.locator("button, a, [role=button], input[type=submit]").evaluateAll((nodes) =>
        nodes.filter((node) => node.dataset.pill !== "SIGNALS")
          .map((node) => `${node.textContent} ${node.getAttribute("aria-label") ?? ""}`.trim()));
      const trading = controls.filter((text) => TRADING_CONTROL.test(text)
        && !/no order|not an order|never an order|without an order|no .*execution/i.test(text));
      assert.deepEqual(trading, [], `${tab}: trading controls`);
    }
    // Full screen hides the header, so the workspace shows its own Live trading OFF chip.
    await page.getByRole("tab", { name: "Charts" }).click();
    await page.locator("#fullscreen-button").click();
    assert.equal(await page.locator("#charts-workspace .fullscreen-only").isVisible(), true);
    assert.match(await page.locator("#charts-workspace .fullscreen-only").innerText(), /Live trading: OFF/);
    await page.keyboard.press("Escape");
    assert.ok(requests.every((method) => method === "GET" || method === "OPTIONS"), "the desk only reads");
  } finally {
    await page.close();
  }
});

test("U9: with the API down, Signal Center and Strategy lab say so without crashing", async () => {
  const page = await browser.newPage();
  page.setDefaultTimeout(15_000);
  const crashes = [];
  page.on("pageerror", (error) => crashes.push(error.message));
  await page.route(`${API}/**`, (route) => route.abort("connectionrefused"));
  try {
    await page.goto(`${origin}/`);
    await page.waitForFunction(() => document.querySelector("#signal-status").dataset.state === "error");
    assert.match(await page.locator("#signal-status").innerText(), /Signal Center unavailable — .*unreachable.*no signal/);
    assert.equal(await page.locator("#signal-cards .signal-card").count(), 0);
    await page.getByRole("tab", { name: "Strategy lab" }).click();
    await page.waitForFunction(() => document.querySelector("#lab-imported-status").dataset.state === "error");
    assert.match(await page.locator("#lab-imported-status").innerText(), /Imported verdicts unavailable — .*unreachable/);
    assert.equal(await page.locator("#lab-verdicts .verdict-card").count(), 3, "the verdicts recorded on #516 still show");
    assert.deepEqual(crashes, []);
  } finally {
    await page.close();
  }
});

test("U9: Signal Center cards, glossary terms and imported verdicts are keyboard-reachable and labelled", async () => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.setDefaultTimeout(15_000);
  await syntheticApi(page);
  try {
    await page.goto(`${origin}/`);
    await page.locator("#signal-cards .signal-card").nth(4).waitFor();
    // Tab from the sizing inputs into the first card.
    await page.locator("#signal-reload").focus();
    await page.keyboard.press("Tab");
    const focused = await page.evaluate(() => ({
      card: document.activeElement.classList.contains("signal-card"),
      label: document.activeElement.getAttribute("aria-label"),
    }));
    assert.equal(focused.card, true);
    assert.match(focused.label, /^BTCUSDT: Validated BUY\./);
    for (const card of await page.locator("#signal-cards .signal-card").all()) {
      assert.match(await card.getAttribute("aria-label"), /^[A-Z]+USDT: (No signal — stay out|Forward-testing — paper only|Validated BUY)\./);
    }
    const term = page.locator("#signal-cards .term").first();
    assert.equal(await term.getAttribute("tabindex"), "0");
    assert.match(await term.getAttribute("aria-label"), /: .{20,}/);
    await page.getByRole("tab", { name: "Strategy lab" }).click();
    const imported = page.locator("#lab-imported .imported-verdict").first();
    await imported.waitFor();
    assert.equal(await imported.getAttribute("tabindex"), "0");
    const labelledBy = await imported.getAttribute("aria-labelledby");
    assert.equal(await page.locator(`#${labelledBy}`).innerText(), "synthetic-strategy · v1");
    await imported.focus();
    assert.equal(await imported.evaluate((node) => node.matches(":focus-visible") || document.activeElement === node), true);
  } finally {
    await page.close();
  }
});
