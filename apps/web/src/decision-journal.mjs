import { API_ORIGIN } from "./runtime-config.mjs";
const API = API_ORIGIN + "/api/research/decision-journal";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const SHA = /^[0-9a-f]{64}$/;
function check(value) { if (!value) throw new Error("Invalid journal response. No durable declaration is confirmed."); }
function ref(r, contract, schema) {
  check(r && r.artifact_type === contract && r.version === schema && UUID.test(r.artifact_id) && SHA.test(r.content_sha256));
}
const ts = t => typeof t === "string" && /Z$/.test(t) && Number.isFinite(Date.parse(t));
function common(e) {
  check(UUID.test(e.entry_id) && UUID.test(e.request_id) && SHA.test(e.content_sha256) && SHA.test(e.request_sha256));
  check(e.profile === "PERSONAL_SPOT_RESEARCH" && e.operating_mode === "RESEARCH" && e.origin === "LOCAL_USER_DECLARATION" && e.identity_assurance === "LOCAL_SESSION_UNAUTHENTICATED");
  check(["qualification_authorized", "approval_authorized", "execution_authorized", "trade_facts_verified"].every(k => e[k] === false));
  check(["ABSTAIN", "EXTERNAL_TRADE_INTENT"].includes(e.declared_action) && typeof e.note === "string" && e.note.length <= 2000);
  check([e.declared_at, e.recorded_at].every(ts) && Date.parse(e.declared_at) <= Date.parse(e.recorded_at));
  if (e.supersedes !== null) { ref(e.supersedes, "C-107", e.schema_version); check(typeof e.correction_reason === "string" && e.correction_reason.length > 0); }
  else check(e.correction_reason === null);
}
// C-107v2 (E2c2): a declaration against the exact persisted C-002 snapshot and its C-003 VALID quality report.
function validateSnapshotEntry(e) {
  common(e); ref(e.source, "C-002", "1"); ref(e.quality_report, "C-003", "1");
  const o = e.snapshot_observation;
  check(o && typeof o.instrument_id === "string" && o.instrument_id && typeof o.timeframe === "string" && o.timeframe && Number.isInteger(o.candle_count) && o.candle_count >= 2 && o.quality_status === "VALID");
  check([o.as_of, o.last_candle_open_time, o.fresh_until].every(ts) && Date.parse(o.as_of) <= Date.parse(e.recorded_at) && Date.parse(e.recorded_at) <= Date.parse(o.fresh_until));
  return e;
}
export function validateEntry(e) {
  if (e && e.contract_id === "C-107" && e.schema_version === "2") return validateSnapshotEntry(e);
  check(e && e.contract_id === "C-107" && e.schema_version === "1" && UUID.test(e.entry_id) && UUID.test(e.request_id) && SHA.test(e.content_sha256) && SHA.test(e.request_sha256));
  check(e.profile === "PERSONAL_SPOT_RESEARCH" && e.operating_mode === "RESEARCH" && e.origin === "LOCAL_USER_DECLARATION" && e.identity_assurance === "LOCAL_SESSION_UNAUTHENTICATED");
  check(["qualification_authorized", "approval_authorized", "execution_authorized", "trade_facts_verified"].every(k => e[k] === false));
  check(["ABSTAIN", "EXTERNAL_TRADE_INTENT"].includes(e.declared_action) && typeof e.note === "string" && e.note.length <= 2000);
  check(Object.hasOwn({"C-026":"2", "C-023":"1", "C-070":"2"}, e.source?.artifact_type));
  ref(e.source, e.source?.artifact_type, ({"C-026":"2", "C-023":"1", "C-070":"2"})[e.source?.artifact_type]);
  ref(e.market_context, "C-006", "5");
  check([e.declared_at, e.recorded_at].every(t => typeof t === "string" && /Z$/.test(t) && Number.isFinite(Date.parse(t))) && Date.parse(e.declared_at) <= Date.parse(e.recorded_at));
  check(e.source_observation && (e.source_observation.projection_state === null || typeof e.source_observation.projection_state === "string") && Array.isArray(e.source_observation.reasons));
  if (e.supersedes !== null) { ref(e.supersedes, "C-107", "1"); check(typeof e.correction_reason === "string" && e.correction_reason.length > 0); }
  else check(e.correction_reason === null);
  return e;
}
// Only a CURRENT, quality-VALID snapshot can be declared against (the server re-verifies and fails closed).
export function snapshotDecisionEligibility(snapshot) {
  if (!snapshot) return {ok:false, reason:"No snapshot is loaded. Load a chart first."};
  if (snapshot.temporal_context !== "CURRENT") return {ok:false, reason:"Historical cutoff reads cannot be declared against. Clear the cutoff to record a decision on the current snapshot."};
  if (snapshot.data_quality?.status !== "VALID") return {ok:false, reason:"Snapshot quality is " + (snapshot.data_quality?.status ?? "UNAVAILABLE") + ", not VALID. Refresh before recording a decision."};
  return {ok:true, target:{instrument_id:snapshot.instrument_id, timeframe:snapshot.timeframe, snapshot_id:snapshot.snapshot_id, quality_report_id:snapshot.data_quality.report_id}};
}
export async function journalRequest(fetcher, path, body) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetcher(API + path, { method: body ? "POST" : "GET", credentials: "omit", cache: "no-store", signal: controller.signal,
      headers: body ? {"Content-Type":"application/json", Accept:"application/json"} : {Accept:"application/json"}, ...(body ? {body:JSON.stringify(body)} : {}) });
    if (!response.ok) throw new Error(response.status === 409 ? "This request key already belongs to different content. Recover the original entry; do not retry with a new key." : "Journal request rejected or unconfirmed. Keep the request key and retry the identical declaration after recovery.");
    return await response.json();
  } catch (error) {
    if (error.name === "AbortError" || error instanceof TypeError) throw new Error("Journal save/read is unconfirmed. Keep the same request key and retry; a new key could create a duplicate.");
    throw error;
  } finally { clearTimeout(timer); }
}
function el(document, tag, text) { const n = document.createElement(tag); if (text !== undefined) n.textContent = String(text); return n; }
function apiRef(r) { return {contract_id:r.artifact_type, artifact_id:r.artifact_id, schema_version:r.version, content_sha256:r.content_sha256}; }
// A snapshot target is {instrument_id, timeframe, snapshot_id, quality_report_id} of the chart on screen (C-107v2);
// otherwise `source` is a strategy-record reference (C-107v1). The server resolves and verifies both.
export function snapshotTarget(entry) {
  return {instrument_id:entry.snapshot_observation.instrument_id, timeframe:entry.snapshot_observation.timeframe, snapshot_id:entry.source.artifact_id, quality_report_id:entry.quality_report.artifact_id};
}
function sameRef(a, b) { return (a?.artifact_id ?? null) === (b?.artifact_id ?? null) && (a?.content_sha256 ?? null) === (b?.content_sha256 ?? null); }
function matches(entry, request, source, snapshot) {
  const common = entry.request_id === request.request_id && entry.declared_action === request.declared_action && entry.note === request.note && Date.parse(entry.declared_at) === Date.parse(request.declared_at) && entry.correction_reason === request.correction_reason && sameRef(entry.supersedes, request.supersedes);
  if (snapshot) return common && entry.schema_version === "2" && entry.source.artifact_id === snapshot.snapshot_id && entry.quality_report.artifact_id === snapshot.quality_report_id && entry.snapshot_observation.instrument_id === snapshot.instrument_id && entry.snapshot_observation.timeframe === snapshot.timeframe;
  return common && entry.schema_version === "1" && entry.source.artifact_id === source.artifact_id && entry.source.content_sha256 === source.content_sha256 && entry.source.artifact_type === source.contract_id && entry.source.version === source.schema_version;
}
export function renderJournalForm(document, parent, source, {fetcher = globalThis.fetch, previous = null, saved = () => {}, uuid = () => globalThis.crypto.randomUUID(), snapshot = null} = {}) {
  const form = el(document, "form");
  const title = el(document, "h3", previous ? "Append a correction" : snapshot ? "Record my decision on this snapshot" : "Record your research declaration");
  const action = el(document, "select"); action.required = true;
  for (const [v,t] of [["", "Choose your declared action"], ["ABSTAIN", "Abstain"], ["EXTERNAL_TRADE_INTENT", "External trade intention (no platform authority)"]]) { const n = el(document, "option", t); n.value = v; action.append(n); }
  const note = el(document, "textarea"); note.maxLength = 2000;
  const date = el(document, "input"); date.type = "text"; date.value = new Date().toISOString(); date.required = true;
  const reason = previous ? el(document, "textarea") : null;
  if (reason) { reason.required = true; reason.maxLength = 2000; }
  function label(text, input) { const n = el(document, "label", text); n.append(input); form.append(n); }
  form.append(title, el(document, "p", "Unverified local user declaration. Backend outcome remains separate. External intention is not a recommendation, approval or execution instruction. Backdating does not establish prospective recording. Do not enter credentials."));
  label("Declared action", action); label("Declared at (UTC ISO timestamp)", date); label("Plain-text note (optional)", note);
  if (reason) label("Correction reason", reason);
  const status = el(document, "p"); status.setAttribute("role", "status");
  const key = el(document, "p"); const submit = el(document, "button", "Save declaration"); submit.type = "submit";
  form.append(key, submit, status); parent.append(form);
  let request = null; let busy = false;
  form.addEventListener("submit", async event => {
    event.preventDefault(); if (busy) return;
    if (!request) {
      if (!["ABSTAIN", "EXTERNAL_TRADE_INTENT"].includes(action.value) || !Number.isFinite(Date.parse(date.value)) || !/(?:Z|[+-]\d\d:\d\d)$/.test(date.value) || (reason && !reason.value.trim())) { status.textContent = "Choose an action and supply a valid timezone-aware declaration time and correction reason where applicable."; return; }
      const supersedes = previous ? apiRef({artifact_type:"C-107", artifact_id:previous.entry_id, version:previous.schema_version, content_sha256:previous.content_sha256}) : null;
      request = {request_id:uuid(), ...(snapshot ? {instrument_id:snapshot.instrument_id, timeframe:snapshot.timeframe, snapshot_id:snapshot.snapshot_id, quality_report_id:snapshot.quality_report_id} : {source}), declared_action:action.value, declared_at:new Date(date.value).toISOString(), note:note.value, supersedes, correction_reason:reason ? reason.value : null};
      [action, date, note, ...(reason ? [reason] : [])].forEach(n => n.disabled = true);
      key.textContent = "Request key (retain for recovery): " + request.request_id;
    }
    busy = true; submit.disabled = true; status.textContent = "Saving and verifying durable readback…";
    try {
      const entry = validateEntry(await journalRequest(fetcher, "", request));
      check(matches(entry, request, source, snapshot));
      submit.hidden = true;
      status.textContent = "Saved unverified research declaration " + entry.entry_id + " at " + entry.recorded_at + ". No trade authority granted.";
      saved(entry);
    } catch (error) { status.textContent = (snapshot && /rejected/.test(error.message) ? "The API rejected this snapshot declaration (the snapshot may no longer be the latest VALID one, or it went stale). Reload the chart, then record against the snapshot now on screen. " : "") + error.message; submit.textContent = "Retry identical declaration"; submit.disabled = false; }
    finally { busy = false; }
  });
  return form;
}
export function renderEntry(document, parent, entry) {
  validateEntry(entry);
  const card = el(document, "section"); card.className = "panel";
  const o = entry.snapshot_observation;
  const context = entry.schema_version === "2"
    ? [["Snapshot", entry.source.artifact_id + " / " + entry.source.content_sha256], ["Quality report", entry.quality_report.artifact_id + " · " + o.quality_status], ["Market", o.instrument_id + " · " + o.timeframe + " · " + o.candle_count + " candles"], ["Snapshot as of", o.as_of], ["Last candle open", o.last_candle_open_time], ["Fresh until", o.fresh_until]]
    : [["Source", entry.source.artifact_type + " / " + entry.source.artifact_id + " / " + entry.source.content_sha256], ["Recorded backend projection", entry.source_observation.projection_state ?? "Unavailable"], ["Recorded backend reasons", entry.source_observation.reasons.join(" · ")]];
  for (const [label, value] of [["User declaration", entry.declared_action], ["Entry", entry.entry_id], ["Request key", entry.request_id], ["SHA-256", entry.content_sha256], ...context, ["Declared at", entry.declared_at], ["Recorded at", entry.recorded_at], ["Note", entry.note], ["Supersedes", entry.supersedes?.artifact_id ?? "None"], ["Correction reason", entry.correction_reason ?? "None"]]) card.append(el(document, "p", label + ": " + value));
  card.append(el(document, "p", "LOCAL_SESSION_UNAUTHENTICATED · trade facts unverified · no qualification, approval or execution authority. Corrections are not independent performance samples."));
  parent.append(card); return card;
}
export function mountJournal(document, parent, source, fetcher = globalThis.fetch, {snapshot = null} = {}) {
  const section = el(document, "section"); section.className = "panel";
  parent.append(section);
  const savedBox = el(document, "div");
  renderJournalForm(document, section, source, {fetcher, snapshot, saved: entry => { savedBox.replaceChildren(); renderEntry(document, savedBox, entry); }});
  section.append(savedBox);
  const history = el(document, "div"); const status = el(document, "p"); status.setAttribute("role", "status");
  const refresh = el(document, "button", "Read declaration history"); refresh.type = "button";
  const next = el(document, "button", "Next declarations"); next.type = "button"; next.disabled = true;
  section.append(el(document, "h3", "Research declaration history"), refresh, next, status, history);
  let cursor = null;
  async function load(after) {
    refresh.disabled = true; next.disabled = true; history.replaceChildren();
    try {
      const page = await journalRequest(fetcher, "?limit=20" + (after ? "&cursor=" + encodeURIComponent(after) : ""));
      check(page && Array.isArray(page.items) && page.items.length <= 20 && (page.next_cursor === null || UUID.test(page.next_cursor)));
      page.items.forEach(validateEntry);
      for (const entry of page.items) {
        const card = renderEntry(document, history, entry);
        const correct = el(document, "button", "Append correction"); correct.type = "button"; card.append(correct);
        correct.addEventListener("click", () => { correct.disabled = true; renderJournalForm(document, card, entry.schema_version === "2" ? null : apiRef(entry.source), {fetcher, previous:entry, snapshot:entry.schema_version === "2" ? snapshotTarget(entry) : null}); });
      }
      cursor = page.next_cursor; next.disabled = cursor === null; status.textContent = page.items.length ? "Stored declarations. Originals and corrections remain visible." : "No saved declarations.";
    } catch(error) { cursor = null; status.textContent = error.message; }
    finally { refresh.disabled = false; }
  }
  refresh.addEventListener("click", () => { void load(null); }); next.addEventListener("click", () => { if (cursor) void load(cursor); });
}
