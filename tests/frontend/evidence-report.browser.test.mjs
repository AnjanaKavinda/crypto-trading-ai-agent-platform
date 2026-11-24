import assert from "node:assert/strict";
import { once } from "node:events";
import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { extname, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { evidenceFixture } from "./evidence-fixture.mjs";

const require = createRequire(new URL("../../apps/web/package.json", import.meta.url));
const { chromium } = require("playwright");
const root = fileURLToPath(new URL("../../apps/web", import.meta.url));

test("evidence page renders exact graph safely, clears failed selection and deep-links without writes", async () => {
  const server = createServer(async (request, response) => {
    try {
      const path = resolve(root, `.${new URL(request.url, "http://localhost").pathname}`);
      const rel = relative(root, path);
      if (rel.startsWith(`..${sep}`) || rel === "..") throw new Error("outside web root");
      const body = await readFile(path);
      response.writeHead(200, { "Content-Type": {
        ".html": "text/html", ".mjs": "application/javascript", ".css": "text/css",
      }[extname(path)] ?? "application/octet-stream" });
      response.end(body);
    } catch { response.writeHead(404); response.end(); }
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  let browser;
  try {
    browser = await chromium.launch({ headless: true,
      ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
        ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : {}),
    });
    const page = await browser.newPage();
    const fixture = evidenceFixture();
    fixture.evidence.graph.edges[0].relationship = '<img src=x onerror="window.injected=true">';
    const calls = [];
    let missing = false;
    await page.route("http://127.0.0.1:8000/api/research/strategy-signals**", async (route) => {
      const request = route.request();
      calls.push({ method: request.method(), url: request.url() });
      const detail = new URL(request.url()).pathname.endsWith("/evidence");
      await route.fulfill({ status: missing && detail ? 503 : 200, headers: {
        "Content-Type": "application/json", "Access-Control-Allow-Origin": "*", "Cache-Control": "no-store",
      }, body: JSON.stringify(detail ? fixture : { items: [fixture.artifact], next_cursor: null }) });
    });
    const origin = `http://127.0.0.1:${server.address().port}`;
    await page.goto(`${origin}/evidence.html`);
    const choice = page.locator("#package-list button");
    await choice.click();
    await page.locator("#evidence-report table").first().waitFor();
    assert.match(await page.locator("#evidence-report").innerText(), /EXPIRED/);
    assert.match(await page.locator("#evidence-report").innerText(), /Contradictory evidence/);
    assert.match(await page.locator("#evidence-report").innerText(), /HIGHLY_CORRELATED/);
    assert.match(await page.locator("#evidence-report").innerText(), /1\.2\.3/);
    assert.equal(await page.locator("#evidence-report img").count(), 0);
    assert.equal(await page.evaluate(() => window.injected), undefined);
    const selfLink = await page.getByRole("link", { name: "Link to this exact report" }).getAttribute("href");
    assert.ok(selfLink.includes(fixture.evidence.content_sha256));
    assert.equal(await page.locator("#evidence-report tbody tr").count(), 3);
    missing = true;
    await choice.click();
    await page.getByText("The evidence API is unavailable or could not verify the stored evidence.", { exact: true }).waitFor();
    assert.equal(await page.locator("#evidence-report table").count(), 0);
    missing = false;
    const before = calls.length;
    await page.goto(`${origin}/${selfLink.replace(/^\.\//, "")}`);
    await page.locator("#evidence-report table").first().waitFor();
    assert.equal(calls.length, before + 1);
    assert.ok(calls.at(-1).url.includes("/evidence?"));
    assert.ok(calls.every((request) => request.method === "GET"));
    assert.equal(await page.getByRole("button", { name: /approve|execute|evaluate|refresh from provider/i }).count(), 0);
  } finally {
    await browser?.close();
    await new Promise((done) => server.close(done));
  }
});
