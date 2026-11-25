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
test("journal saves explicitly, retries the same key, renders safe history and appends corrections", async () => {
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
    browser = await chromium.launch({headless:true, ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ? {executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH} : {})});
    const page = await browser.newPage(); const sourceRecord = record(1); const posts = []; const entries = [];
    await page.route("http://127.0.0.1:8000/api/research/strategy-signals**", async route => {
      const detail = new URL(route.request().url()).pathname !== "/api/research/strategy-signals";
      await route.fulfill({status:200,headers:{"Content-Type":"application/json","Access-Control-Allow-Origin":"*"},body:JSON.stringify(detail ? sourceRecord : {items:[sourceRecord],next_cursor:null,watch_status:"UNAVAILABLE_NOT_PRODUCED"})});
    });
    await page.route("http://127.0.0.1:8000/api/research/decision-journal**", async route => {
      const req=route.request(); const headers={"Content-Type":"application/json","Access-Control-Allow-Origin":"*","Access-Control-Allow-Methods":"GET, POST, OPTIONS","Access-Control-Allow-Headers":"content-type"};
      if(req.method()==="OPTIONS") { await route.fulfill({status:204,headers}); return; }
      let result={items:entries,next_cursor:null};
      if(req.method()==="POST") {
        const body=req.postDataJSON(); posts.push(body);
        if(posts.length===1) { await route.fulfill({status:503,headers,body:"{}"}); return; }
        const r=body.source;
        result={contract_id:"C-107",schema_version:"1",entry_id:id(entries.length+50),content_sha256:"b".repeat(64),request_id:body.request_id,request_sha256:"c".repeat(64),profile:"PERSONAL_SPOT_RESEARCH",operating_mode:"RESEARCH",origin:"LOCAL_USER_DECLARATION",identity_assurance:"LOCAL_SESSION_UNAUTHENTICATED",qualification_authorized:false,approval_authorized:false,execution_authorized:false,trade_facts_verified:false,source:{artifact_type:r.contract_id,artifact_id:r.artifact_id,version:r.schema_version,content_sha256:r.content_sha256},market_context:{artifact_type:"C-006",artifact_id:id(99),version:"5",content_sha256:"d".repeat(64)},source_observation:{projection_state:"NO_TRADE",reasons:["VALIDATION_MISSING"]},declared_action:body.declared_action,declared_at:body.declared_at,recorded_at:new Date(Date.now()+1000).toISOString(),note:body.note,supersedes:body.supersedes ? {artifact_type:"C-107",artifact_id:body.supersedes.artifact_id,version:"1",content_sha256:body.supersedes.content_sha256} : null,correction_reason:body.correction_reason};
        entries.push(result);
      }
      await route.fulfill({status:200,headers,body:JSON.stringify(result)});
    });
    const origin="http://127.0.0.1:"+server.address().port;
    await page.goto(origin+"/signals.html"); await page.getByRole("button",{name:"Read exact record",exact:true}).click();
    const action=page.locator("#record-detail form select").first(); await action.waitFor(); assert.equal(posts.length,0);
    await action.selectOption("EXTERNAL_TRADE_INTENT");
    await page.getByLabel("Plain-text note (optional)",{exact:true}).fill('<img src=x onerror="window.injected=true">');
    await page.getByRole("button",{name:"Save declaration",exact:true}).click();
    await page.getByRole("button",{name:"Retry identical declaration",exact:true}).waitFor();
    assert.equal(await action.isDisabled(),true);
    await page.getByRole("button",{name:"Retry identical declaration",exact:true}).click();
    await page.getByText(/Saved unverified research declaration/).waitFor(); assert.deepEqual(posts[0],posts[1]);
    await page.getByRole("button",{name:"Read declaration history",exact:true}).click();
    await page.getByRole("button",{name:"Append correction",exact:true}).click();
    await page.getByRole("heading",{name:"Append a correction",exact:true}).waitFor();
    assert.equal(await page.locator("#record-detail img").count(),0); assert.equal(await page.evaluate(()=>window.injected),undefined);
    const form=page.locator("form").last(); await form.locator("select").selectOption("ABSTAIN");
    await form.getByLabel("Correction reason",{exact:true}).fill("Corrected intent");
    await form.getByRole("button",{name:"Save declaration",exact:true}).click();
    await page.getByText(/Saved unverified research declaration/).nth(1).waitFor();
    assert.equal(posts[2].supersedes.artifact_id,entries[0].entry_id); assert.equal(posts[2].declared_action,"ABSTAIN");
    assert.equal(sourceRecord.projection_state,"NO_TRADE");
  } finally { await browser?.close(); await new Promise(done=>server.close(done)); }
});
