// Owner's real Docker preview: GETs only, no synthetic responses or DB writes.
// UI_SCREENSHOT_DIR chooses the output folder; TOOLBAR_PHASE=before|after.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { createHash } from "node:crypto";
import { join } from "node:path";
import { captureScreenshot, SCREENSHOT_VIEWPORTS, screenshotDir } from "./screenshots.mjs";

const require = createRequire(new URL("../../apps/web/package.json", import.meta.url));
const { chromium } = require("playwright");
const phase = process.env.TOOLBAR_PHASE ?? "before";
const dir = screenshotDir();
assert.ok(dir, "Set UI_SCREENSHOT_DIR for real-data preview evidence");
const origin = "http://127.0.0.1:5173";
const browser = await chromium.launch({ headless: true });
const report = { phase, origin, published_head: process.env.TOOLBAR_REVISION ?? null, requests: [], errors: [], resources: {}, captures: [], layout: [] };
try {
  const page = await browser.newPage();
  await page.route("**/api/**", (route) => {
    const method = route.request().method();
    assert.equal(method, "GET", "Preview cannot refresh providers or write records");
    report.requests.push(route.request().url());
    return route.continue();
  });
  page.on("pageerror", (error) => report.errors.push(error.message));
  for (const file of ["index.html", "styles.css", "src/app.mjs", ...(phase === "after" ? ["src/chart-display.mjs", "src/chart-toolbar.mjs", "src/workspace-state.mjs", "src/indicator-toolbar.mjs"] : [])]) {
    const response = await page.request.get(`${origin}/${file}`);
    const served = await response.body();
    const local = await readFile(new URL(`../../apps/web/${file}`, import.meta.url));
    report.resources[file] = {
      served_sha256: createHash("sha256").update(served).digest("hex"),
      matches_worktree: served.equals(local),
    };
  }
  await page.goto(`${origin}/#charts`);
  await page.locator("#beginner-button").waitFor();
  await page.waitForFunction(() => !/Reading|Loading/.test(document.querySelector("#snapshot-status")?.textContent ?? ""), null, { timeout: 60000 });
  report.status = await page.locator("#snapshot-status").innerText();
  report.market = await page.locator("#chart-heading").innerText();
  for (const viewport of SCREENSHOT_VIEWPORTS) {
    await page.setViewportSize(viewport);
    for (const mode of ["beginner", "pro"]) {
      await page.locator(`#${mode}-button`).click();
      // Match before/after chart context: default window and open drawer.
      await page.locator("#charts-workspace").evaluate((node) => { node.dataset.drawer = "open"; });
      report.captures.push(await captureScreenshot(page, `${phase}-${mode}`, viewport));
      report.layout.push({ mode, viewport, chart: await page.locator("#chart-container").boundingBox() });
    }
  }
  report.chart = await page.locator("#chart-container").evaluate((node) => ({
    width: node.clientWidth, height: node.clientHeight, top: node.getBoundingClientRect().top, svg: Boolean(node.querySelector("svg")),
  }));
  if (phase === "after") {
    const viewport = SCREENSHOT_VIEWPORTS[0];
    await page.setViewportSize(viewport);
    for (const menu of ["chart-type", "order-flow", "indicators", "timeframe"]) {
      await page.locator(`#${menu}-menu > summary`).click();
      report.captures.push(await captureScreenshot(page, `menu-${menu}`, viewport));
      const box = await page.locator(`#${menu}-menu .chart-menu-panel`).boundingBox();
      assert.ok(box.x >= 0 && box.x + box.width <= viewport.width, `${menu} fits viewport`);
      await page.keyboard.press("Escape");
    }
    const candleRequests = report.requests.filter((url) => url.includes("/candles?")).length;
    await page.locator("#chart-container svg").evaluate((el) => { el.dataset.identity = "real-chart"; });
    await page.locator("#chart-type-menu > summary").click();
    await page.locator('[data-control="favorite-favoriteStyles-line"]').click();
    assert.equal(await page.locator("#chart-container svg").getAttribute("data-identity"), "real-chart");
    await page.keyboard.press("Escape");
    await page.locator("#timeframe-menu > summary").click();
    await page.locator('[data-control="favorite-favoriteTimeframes-1h"]').click();
    assert.equal(await page.locator("#chart-container svg").getAttribute("data-identity"), "real-chart");
    await page.keyboard.press("Escape");
    assert.equal(report.requests.filter((url) => url.includes("/candles?")).length, candleRequests);
    for (const [style, selector] of [["bars", ".ohlc-bar"], ["hollow", ".hollow-body"], ["line", ".close-price-line"], ["step", ".close-price-line"], ["candles", ".candle-body"]]) {
      await page.locator("#chart-type-menu > summary").click();
      await page.locator(`[data-control="style-menu-${style}"]`).click();
      assert.ok(await page.locator(`#chart-container ${selector}`).count() > 0);
      if (style === "hollow") {
        const paint = await page.locator(".hollow-body").first().evaluate((el) => [getComputedStyle(el).fill, getComputedStyle(el).stroke]);
        assert.notEqual(paint[0], paint[1]);
      }
    }
    await page.locator("#indicators-menu > summary").click();
    await page.getByRole("searchbox", { name: "Search indicators" }).fill("RSI");
    await page.locator('[data-control="toggle-study-rsi-14"]').click();
    assert.ok(await page.locator('.indicator-pane[data-pane="rsi-14"]').count());
    await page.locator('#indicators-menu [data-study="rsi-14"] .study-settings > summary').click();
    await page.getByRole("combobox", { name: "RSI 14 line width" }).selectOption("3");
    assert.equal(await page.locator(".rsi-line").evaluate((el) => getComputedStyle(el).strokeWidth), "3px");
    await page.getByRole("searchbox", { name: "Search indicators" }).fill("");
    await page.locator('[data-control="filter-Active"]').click();
    await page.keyboard.press("Escape");
    await page.locator("#order-flow-menu > summary").click();
    const vwap = page.locator('[data-control="toggle-flow-vwap"]');
    if (await vwap.isEnabled()) {
      const wasOn = await vwap.getAttribute("aria-pressed") === "true";
      await vwap.click();
      assert.equal(await page.locator(".spot-vwap-line").count(), wasOn ? 0 : 1);
      report.orderFlow = "Backend candle-approximation VWAP toggle rendered correctly";
    } else report.orderFlow = await page.locator("#order-flow-menu .chart-menu-panel").innerText();
    await page.keyboard.press("Escape");
    await page.locator("#pro-signals").click();
    assert.equal(await page.locator("#marker-strategy").inputValue(), "");
    await page.locator("#marker-strategy").selectOption("range-reversion-4h@1");
    await page.waitForFunction(() => !/Loading strategy markers/.test(document.querySelector("#markers-body").textContent), null, { timeout: 60000 });
    report.markers = await page.locator("#markers-body").innerText();
    report.verdict = await page.locator("#markers-banner").innerText();
    if (await page.locator("#markers-body [data-marker-index]").count()) {
      await page.locator("#markers-body [data-marker-index]").first().click();
      report.evidence = await page.locator("#marker-detail").innerText();
    }
    report.captures.push(await captureScreenshot(page, "signals-evidence", viewport));
    await page.locator("#fullscreen-button").click();
    report.captures.push(await captureScreenshot(page, "fullscreen-toolbar", viewport));
    await page.keyboard.press("Escape");
    await page.setViewportSize({ width: 700, height: 900 });
    await page.locator("#chart-overflow > summary").click();
    await page.locator("#indicators-menu > summary").click();
    report.captures.push(await captureScreenshot(page, "narrow-toolbar", { width: 700, height: 900 }));
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.keyboard.press("Escape");
    await page.setViewportSize(viewport);
    // Rapid selection uses only the stored read path; no refresh and no study.
    await page.locator("#chart-market").selectOption("ETH-USDT-SPOT");
    await page.locator("#chart-market").selectOption("BTC-USDT-SPOT");
    await page.locator("#chart-market").selectOption("ETH-USDT-SPOT");
    await page.locator('[data-control="interval-shortcut-1d"]').click();
    await page.waitForFunction(() => !/Reading|Loading/.test(document.querySelector("#snapshot-status").textContent), null, { timeout: 60000 });
    assert.match(await page.locator("#chart-heading").innerText(), /ETH/);
    assert.match(await page.locator("#chart-container svg").getAttribute("aria-label"), /ETHUSDT 1d/);
    report.finalSelection = { market: await page.locator("#chart-heading").innerText(), status: await page.locator("#snapshot-status").innerText(), evidence: await page.locator("#markers-body").innerText() };
    await page.reload();
    await page.locator("#chart-type-menu > summary").waitFor();
    assert.equal(await page.locator('[data-control="style-shortcut-line"]').count(), 1);
    assert.equal(await page.locator('[data-control="interval-shortcut-1h"]').count(), 0);
  }
  assert.deepEqual(report.errors, []);
} finally {
  await mkdir(dir, { recursive: true });
  await writeFile(join(dir, `${phase}-preview.json`), JSON.stringify(report, null, 2) + "\n");
  await browser.close();
}
console.log(JSON.stringify({ phase, status: report.status, chart: report.chart, errors: report.errors, resources: report.resources }));
