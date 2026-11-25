import assert from "node:assert/strict";
import { once } from "node:events";
import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { extname, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const require = createRequire(new URL("../../apps/web/package.json", import.meta.url));
const { chromium } = require("playwright");
const root = fileURLToPath(new URL("../../apps/web", import.meta.url));

test("desk tabs fold in existing pages lazily, route by hash and fail closed on freshness", async () => {
  const server = createServer(async (request, response) => {
    try {
      const path = resolve(root, "." + new URL(request.url, "http://localhost").pathname);
      const rel = relative(root, path);
      if (rel.startsWith(".." + sep) || rel === "..") throw new Error("outside root");
      const body = await readFile(path);
      response.writeHead(200, { "Content-Type": { ".html": "text/html", ".mjs": "application/javascript",
        ".css": "text/css" }[extname(path)] ?? "application/octet-stream" });
      response.end(body);
    } catch { response.writeHead(404); response.end(); }
  });
  server.listen(0, "127.0.0.1"); await once(server, "listening");
  const origin = `http://127.0.0.1:${server.address().port}`;
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    const apiCalls = [];
    // The local API is down: every read fails, nothing is invented.
    await page.route("http://127.0.0.1:8000/**", (route) => {
      apiCalls.push({ url: route.request().url(), method: route.request().method() });
      return route.fulfill({ status: 503, contentType: "application/json", body: "{}" });
    });
    await page.goto(`${origin}/desk.html`);
    const tabs = page.getByRole("tab");
    assert.deepEqual(await tabs.allTextContents(), ["Today", "Charts", "Strategy lab", "My results"]);
    assert.equal(await page.getByRole("tab", { name: "Today" }).getAttribute("aria-selected"), "true");
    await page.locator("#panel-today iframe").waitFor();
    assert.equal(await page.locator("iframe").count(), 1, "only the visible tab loads");
    assert.match(await page.locator("#desk-live").textContent(), /Live trading: OFF/);
    await page.waitForFunction(() => document.querySelector("#desk-freshness").dataset.state === "error");
    assert.match(await page.locator("#desk-freshness").textContent(), /unavailable/);

    await page.getByRole("tab", { name: "Charts" }).click();
    assert.match(page.url(), /#charts$/);
    assert.equal(await page.locator("#panel-today").isHidden(), true);
    const charts = page.frameLocator("#panel-charts iframe");
    await charts.getByRole("heading", { name: "Asset analysis workspace" }).waitFor();

    await page.getByRole("tab", { name: "Charts" }).focus();
    await page.keyboard.press("ArrowRight");
    assert.equal(await page.getByRole("tab", { name: "Strategy lab" }).getAttribute("aria-selected"), "true");
    await page.frameLocator("#panel-strategy-lab iframe").getByRole("heading", { name: "Evidence report" }).waitFor();

    await page.goto(`${origin}/desk.html#my-results`);
    assert.equal(await page.getByRole("tab", { name: "My results" }).getAttribute("aria-selected"), "true");
    await page.frameLocator("#panel-my-results iframe")
      .getByRole("heading", { name: "Research records and NO_TRADE" }).waitFor();
    assert.ok(apiCalls.every(({ method }) => method === "GET" || method === "OPTIONS"), "desk never writes");
    assert.ok(apiCalls.every(({ url }) => !url.includes("/refresh")), "desk never refreshes providers");
  } finally {
    await browser?.close();
    server.close();
  }
});
