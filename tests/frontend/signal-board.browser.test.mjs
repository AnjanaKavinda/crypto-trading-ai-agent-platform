import assert from "node:assert/strict";
import { once } from "node:events";
import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { extname, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { id } from "./evidence-fixture.mjs";

const require = createRequire(new URL("../../apps/web/package.json", import.meta.url));
const { chromium } = require("playwright");
const root = fileURLToPath(new URL("../../apps/web", import.meta.url));
function record(n) {
  return { reference: { contract_id: "C-026", artifact_id: id(n), schema_version: "2", content_sha256: "a".repeat(64) },
    occurred_at: "2026-01-01T00:00:00Z", as_of: null, valid_until: "2026-01-01T01:00:00Z",
    projection_state: "NO_TRADE", reasons: ["VALIDATION_MISSING"], lineage: [], lifecycle_events: [] };
}
test("board shows NO_TRADE without invented evidence, safe history, selector clearing and exact links", async () => {
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
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    const first = record(1); const second = record(2);
    const evidence = { ...first.reference, contract_id: "C-024", artifact_id: id(20) };
    second.lineage = [evidence];
    second.lifecycle_events = [{ event_id: id(30), prior_state: "CANDIDATE", resulting_state: "NO_TRADE",
      event_type: "NO_TRADE", cause: '<img src=x onerror="window.injected=true">', correlation_id: "fixture-correlation",
      event_time: first.occurred_at, recorded_at: first.occurred_at, source_references: [evidence] }];
    const calls = [];
    await page.route("http://127.0.0.1:8000/api/research/strategy-signals**", async (route) => {
      const req = route.request(); const url = new URL(req.url()); calls.push({ method: req.method(), url: req.url() });
      const detail = url.pathname !== "/api/research/strategy-signals";
      const value = detail ? (url.pathname.endsWith(id(1)) ? first : second)
        : { items: url.searchParams.get("contract_id") === "C-026" ? [first, second] : [],
          next_cursor: null, watch_status: "UNAVAILABLE_NOT_PRODUCED" };
      await route.fulfill({ status: 200, headers: { "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*", "Cache-Control": "no-store" }, body: JSON.stringify(value) });
    });
    const origin = "http://127.0.0.1:" + server.address().port;
    await page.goto(origin + "/signals.html");
    const choices = page.locator("#record-list button");
    await choices.nth(0).click();
    await page.getByRole("heading", { name: "Recorded reason codes", exact: true }).waitFor();
    assert.match(await page.locator("#record-detail").innerText(), /VALIDATION_MISSING/);
    assert.match(await page.locator("#record-detail").innerText(), /No evidence package is linked/);
    assert.match(await page.locator("#record-detail").innerText(), /EXPIRED/);
    await choices.nth(1).click();
    await page.locator("#record-detail details summary").click();
    assert.match(await page.locator("#record-detail").innerText(), /fixture-correlation/);
    assert.equal(await page.locator("#record-detail img").count(), 0);
    assert.equal(await page.evaluate(() => window.injected), undefined);
    const bound = page.locator('#record-detail a[href*="evidence.html"]');
    assert.equal(await bound.count(), 1);
    assert.ok((await bound.getAttribute("href")).includes(evidence.artifact_id));
    const link = await page.getByRole("link", { name: "Link to this exact record" }).getAttribute("href");
    await page.locator("#record-kind").selectOption("CANDIDATE");
    await page.getByText("No stored records match this selection. An empty list is not a NO_TRADE decision or a signal.", { exact: true }).waitFor();
    assert.equal(await page.locator("#record-detail").textContent(), "");
    const before = calls.length;
    await page.goto(origin + "/" + link.replace(/^\.\//, ""));
    await page.getByRole("heading", { name: "Recorded reason codes", exact: true }).waitFor();
    assert.equal(calls.length, before + 1);
    assert.ok(calls.every((call) => call.method === "GET"));
    assert.equal(await page.getByRole("button", { name: /approve|execute|evaluate|refresh from provider/i }).count(), 0);
  } finally {
    await browser?.close();
    await new Promise((done) => server.close(done));
  }
});
