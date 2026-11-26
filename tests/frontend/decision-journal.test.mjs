import test from "node:test";
import assert from "node:assert/strict";
import { validateEntry, renderEntry, renderJournalForm, journalRequest, snapshotDecisionEligibility, snapshotTarget } from "../../apps/web/src/decision-journal.mjs";
const id = n => "00000000-0000-4000-8000-" + String(n).padStart(12,"0");
const source = {artifact_type:"C-026", artifact_id:id(1), version:"2", content_sha256:"a".repeat(64)};
function entry(request = {}) { return {contract_id:"C-107", schema_version:"1", entry_id:id(2), request_id:request.request_id ?? id(3), request_sha256:"b".repeat(64), content_sha256:"c".repeat(64), source, market_context:{...source,artifact_type:"C-006",version:"5"}, source_observation:{projection_state:"NO_TRADE", reasons:["MISSING_DATA"]}, declared_action:request.declared_action ?? "ABSTAIN", declared_at:request.declared_at ?? "2026-11-25T00:00:00Z", recorded_at:"2026-12-25T00:00:00Z", note:request.note ?? "", supersedes:null, correction_reason:null, profile:"PERSONAL_SPOT_RESEARCH",operating_mode:"RESEARCH",origin:"LOCAL_USER_DECLARATION",identity_assurance:"LOCAL_SESSION_UNAUTHENTICATED",qualification_authorized:false,approval_authorized:false,execution_authorized:false,trade_facts_verified:false}; }
class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.listeners = {}; this.value = ""; this.textContent = ""; }
  append(...nodes) { this.children.push(...nodes); }
  setAttribute() {}
  addEventListener(name, fn) { this.listeners[name] = fn; }
}
const document = {createElement:tag => new Node(tag)};
function flatten(n) { return [n,...n.children.flatMap(flatten)]; }
test("closed journal identity and authority reject unsupported/misleading responses", () => {
  assert.equal(validateEntry(entry()).declared_action, "ABSTAIN");
  for (const changes of [{execution_authorized:true}, {identity_assurance:"OWNER_VERIFIED"}, {schema_version:"2"}, {declared_action:"EXECUTE"}, {source:{...source,artifact_type:"C-044",version:undefined}}, {declared_at:"2027-01-01T00:00:00Z"}]) assert.throws(() => validateEntry({...entry(),...changes}));
});
test("rendered notes and reasons are text, not HTML", () => {
  const parent = new Node("div"); const value = entry({note:'<img src=x onerror="window.injected=true">'});
  renderEntry(document,parent,value);
  assert.ok(flatten(parent).some(n => n.textContent.includes(value.note)));
  assert.equal(flatten(parent).filter(n => n.tag === "img").length,0);
});
test("explicit save freezes content and preserves request identity across an uncertain retry", async () => {
  const parent = new Node("div"); const calls = []; let accepted = 0;
  const form = renderJournalForm(document,parent,{contract_id:"C-026",artifact_id:id(1),schema_version:"2",content_sha256:source.content_sha256},{uuid:()=>id(7),saved:()=>accepted++,fetcher:async(url,options)=>{ const body = JSON.parse(options.body); calls.push({url,options,body}); if(calls.length===1) throw new TypeError("network lost"); return {ok:true,json:async()=>entry(body)}; }});
  assert.equal(calls.length,0);
  const nodes = flatten(form); nodes.find(n=>n.tag==="select").value = "EXTERNAL_TRADE_INTENT"; nodes.find(n=>n.tag==="textarea").value = "user note";
  const submit = ()=>form.listeners.submit({preventDefault(){}});
  await submit(); assert.equal(accepted,0); assert.equal(nodes.find(n=>n.tag==="select").disabled,true);
  await submit(); assert.equal(accepted,1); assert.deepEqual(calls[0].body,calls[1].body);
  assert.equal(calls[0].options.cache,"no-store"); assert.equal(calls[0].options.credentials,"omit");
  assert.equal(calls[0].body.source.contract_id,"C-026"); assert.equal(calls[0].body.request_id,id(7));
  assert.equal(nodes.find(n=>n.tag==="button").hidden,true);
});
test("API conflict and invalid save acknowledgement do not confirm a declaration",async()=>{
  await assert.rejects(journalRequest(async()=>({ok:false,status:409}),"",{}),/different content/);
  const parent = new Node("div"); let accepted = false;
  const form = renderJournalForm(document,parent,{contract_id:"C-026",artifact_id:id(1),schema_version:"2",content_sha256:source.content_sha256},{uuid:()=>id(7),saved:()=>{accepted=true;},fetcher:async()=>({ok:true,json:async()=>entry({request_id:id(8)})})});
  flatten(form).find(n=>n.tag==="select").value="ABSTAIN";
  await form.listeners.submit({preventDefault(){}}); assert.equal(accepted,false);
});

// Synthetic C-107v2 entry (E2c2 snapshot link); identifiers and digests are placeholders, not market data.
function snapshotEntry(changes = {}) {
  const {source:_s, market_context:_m, source_observation:_o, ...rest} = entry();
  return {...rest, schema_version:"2", source:{artifact_type:"C-002", artifact_id:id(20), version:"1", content_sha256:"d".repeat(64)}, quality_report:{artifact_type:"C-003", artifact_id:id(21), version:"1", content_sha256:"e".repeat(64)}, snapshot_observation:{instrument_id:"BTC-USDT-SPOT", timeframe:"4h", as_of:"2026-12-24T23:00:00Z", last_candle_open_time:"2026-12-24T16:00:00Z", candle_count:50, fresh_until:"2026-12-25T04:00:00Z", quality_status:"VALID"}, ...changes};
}
test("C-107v2 snapshot entries validate and fail closed on stale, wrong-contract or non-VALID links", () => {
  assert.equal(validateEntry(snapshotEntry()).schema_version, "2");
  for (const changes of [{execution_authorized:true}, {quality_report:{artifact_type:"C-006", artifact_id:id(21), version:"1", content_sha256:"e".repeat(64)}}, {snapshot_observation:{...snapshotEntry().snapshot_observation, quality_status:"STALE"}}, {snapshot_observation:{...snapshotEntry().snapshot_observation, fresh_until:"2026-12-24T23:30:00Z"}}, {supersedes:{artifact_type:"C-107", artifact_id:id(9), version:"1", content_sha256:"f".repeat(64)}, correction_reason:"x"}]) assert.throws(() => validateEntry(snapshotEntry(changes)));
  assert.deepEqual(snapshotTarget(snapshotEntry()), {instrument_id:"BTC-USDT-SPOT", timeframe:"4h", snapshot_id:id(20), quality_report_id:id(21)});
});
test("record-my-decision is only offered for a CURRENT, quality-VALID snapshot", () => {
  const snap = {instrument_id:"BTC-USDT-SPOT", timeframe:"4h", snapshot_id:id(20), temporal_context:"CURRENT", data_quality:{status:"VALID", report_id:id(21)}};
  assert.deepEqual(snapshotDecisionEligibility(snap).target, snapshotTarget(snapshotEntry()));
  assert.equal(snapshotDecisionEligibility(null).ok, false);
  assert.match(snapshotDecisionEligibility({...snap, temporal_context:"HISTORICAL"}).reason, /cutoff/);
  assert.match(snapshotDecisionEligibility({...snap, data_quality:{status:"STALE", report_id:id(21)}}).reason, /STALE/);
});
test("a correction of a snapshot entry posts the v2 snapshot shape with a v2 parent", async () => {
  const parent = new Node("div"); const calls = []; const previous = snapshotEntry();
  const form = renderJournalForm(document, parent, null, {previous, snapshot:snapshotTarget(previous), uuid:()=>id(30), fetcher:async(url, options) => { const body = JSON.parse(options.body); calls.push(body); return {ok:true, json:async()=>snapshotEntry({entry_id:id(31), request_id:body.request_id, declared_action:body.declared_action, declared_at:body.declared_at, note:body.note, supersedes:{artifact_type:"C-107", artifact_id:previous.entry_id, version:"2", content_sha256:previous.content_sha256}, correction_reason:body.correction_reason})}; }});
  const nodes = flatten(form); nodes.find(n=>n.tag==="select").value = "EXTERNAL_TRADE_INTENT";
  nodes.filter(n=>n.tag==="textarea")[1].value = "wrong action";
  let accepted = false; await form.listeners.submit({preventDefault(){}});
  accepted = nodes.find(n=>n.tag==="button").hidden;
  assert.equal(accepted, true);
  assert.equal(calls[0].snapshot_id, id(20)); assert.equal(calls[0].quality_report_id, id(21)); assert.equal(calls[0].source, undefined);
  assert.deepEqual(calls[0].supersedes, {contract_id:"C-107", artifact_id:previous.entry_id, schema_version:"2", content_sha256:previous.content_sha256});
});
