import { API_ORIGIN } from "./runtime-config.mjs";
import { evidenceLink, validityLabel } from "./evidence-report.mjs";

export const KINDS = Object.freeze({
  NO_TRADE: Object.freeze({ contract: "C-026", schema: "2", label: "NO_TRADE decision" }),
  CANDIDATE: Object.freeze({ contract: "C-023", schema: "1", label: "Candidate record" }),
  SIGNAL: Object.freeze({ contract: "C-070", schema: "2", label: "Signal record" }),
});
const API = API_ORIGIN + "/api/research/strategy-signals";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const SHA = /^[0-9a-f]{64}$/;
const STATES = new Set(["DRAFT", "CANDIDATE", "QUALIFIED", "WATCH", "REJECTED", "NO_TRADE", "EXPIRED", "SUPERSEDED"]);
function check(ok) {
  if (!ok) throw new Error("The board response or selected reference is invalid or unsupported.");
}
function text(value, max = 256) { return typeof value === "string" && value.length > 0 && value.length <= max; }
function time(value) {
  check(text(value, 64) && /(?:Z|[+-]\d\d:\d\d)$/.test(value) && Number.isFinite(Date.parse(value)));
}
function nullableTime(value) { if (value !== null) time(value); }
export function validateReference(r, board = false) {
  check(r && text(r.contract_id, 32) && UUID.test(r.artifact_id) && text(r.schema_version, 128) && SHA.test(r.content_sha256));
  if (board) check(Object.values(KINDS).some((k) => k.contract === r.contract_id && k.schema === r.schema_version));
  return r;
}
function references(values, max = 64) {
  check(Array.isArray(values) && values.length <= max);
  values.forEach((r) => validateReference(r));
}
export function validateRecord(record, selected = null) {
  validateReference(record?.reference, true);
  if (selected) check(["contract_id", "artifact_id", "schema_version", "content_sha256"]
    .every((name) => record.reference[name] === selected[name]));
  time(record.occurred_at);
  nullableTime(record.as_of);
  nullableTime(record.valid_until);
  check(record.projection_state === null || text(record.projection_state, 32));
  check(Array.isArray(record.reasons) && record.reasons.length <= 32 && record.reasons.every((r) => text(r)));
  references(record.lineage);
  check(Array.isArray(record.lifecycle_events) && record.lifecycle_events.length <= 64);
  const seen = new Set();
  for (const event of record.lifecycle_events) {
    check(UUID.test(event.event_id) && !seen.has(event.event_id));
    seen.add(event.event_id);
    check(event.prior_state === null || text(event.prior_state, 32));
    check(text(event.resulting_state, 32) && text(event.event_type, 128) &&
      text(event.cause, 128) && text(event.correlation_id));
    time(event.event_time);
    time(event.recorded_at);
    references(event.source_references, 32);
  }
  return record;
}
function kind(value) { check(Object.hasOwn(KINDS, value)); return KINDS[value]; }
function filters(value) {
  const k = kind(value.kind);
  check(value.state === "" || STATES.has(value.state));
  check(value.cursor === null || text(value.cursor, 4096));
  return k;
}
async function get(fetcher, path) {
  const controller = new AbortController();
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => {
      controller.abort();
      reject(new Error("The board request timed out. No record was accepted."));
    }, 15000);
  });
  const perform = async () => {
    let result;
    try {
      result = await fetcher(API + path, { method: "GET", credentials: "omit", cache: "no-store",
        headers: { Accept: "application/json" }, signal: controller.signal });
    } catch { throw new Error("The local research API is unreachable."); }
    if (!result.ok) throw new Error(result.status === 404 ? "No stored record matches this exact reference."
      : result.status === 422 ? "The API does not support this record reference or filter."
        : "The board API is unavailable or could not verify the stored record.");
    try { return await result.json(); }
    catch { throw new Error("The board API returned an unreadable response."); }
  };
  try { return await Promise.race([perform(), timeout]); }
  finally { clearTimeout(timer); }
}
export async function listRecords(fetcher, selection) {
  const k = filters(selection);
  const query = new URLSearchParams({ contract_id: k.contract, schema_version: k.schema, limit: "20" });
  if (selection.state) query.set("projection_state", selection.state);
  if (selection.cursor !== null) query.set("cursor", selection.cursor);
  const page = await get(fetcher, "?" + query);
  check(page && Array.isArray(page.items) && page.items.length <= 20 &&
    (page.next_cursor === null || text(page.next_cursor, 4096)) && text(page.watch_status, 128));
  const seen = new Set();
  for (const record of page.items) {
    validateRecord(record);
    check(record.reference.contract_id === k.contract && record.reference.schema_version === k.schema);
    if (selection.state) check(record.projection_state === selection.state);
    const key = record.reference.artifact_id;
    check(!seen.has(key)); seen.add(key);
  }
  return page;
}
export async function readRecord(fetcher, reference) {
  validateReference(reference, true);
  const query = new URLSearchParams({ schema_version: reference.schema_version, content_sha256: reference.content_sha256 });
  return validateRecord(await get(fetcher, "/" + reference.contract_id + "/" + reference.artifact_id + "?" + query), reference);
}
export function recordLink(r) {
  validateReference(r, true);
  return "./signals.html?" + new URLSearchParams({ contract_id: r.contract_id, artifact_id: r.artifact_id,
    schema_version: r.schema_version, content_sha256: r.content_sha256 });
}
export function recordFromQuery(search) {
  const query = new URLSearchParams(search);
  const fields = ["contract_id", "artifact_id", "schema_version", "content_sha256"];
  if (!fields.some((name) => query.has(name))) return null;
  check(fields.every((name) => query.getAll(name).length === 1));
  return validateReference(Object.fromEntries(fields.map((name) => [name, query.get(name)])), true);
}
export function evidenceReferences(record) {
  const result = new Map();
  for (const ref of [...record.lineage, ...record.lifecycle_events.flatMap((event) => event.source_references)]) {
    if (ref.contract_id === "C-024" && ref.schema_version === "2") {
      validateReference(ref);
      result.set(ref.artifact_id + ":" + ref.content_sha256, ref);
    }
  }
  return [...result.values()];
}
export function stateLabel(state) {
  return STATES.has(state) ? "Recorded projection: " + state
    : state === null ? "Recorded projection unavailable" : "Unsupported recorded projection: " + state;
}
export function createSelectionLoader({ fetcher, clear, show, fail }) {
  let sequence = 0;
  return {
    reset() { sequence++; clear(false); },
    async load(reference) {
      const current = ++sequence;
      clear(true);
      try {
        const record = await readRecord(fetcher, reference);
        if (current === sequence) show(record);
      } catch (error) { if (current === sequence) fail(error); }
    },
  };
}
function el(document, tag, value) {
  const node = document.createElement(tag);
  if (value !== undefined) node.textContent = String(value);
  return node;
}
function refText(r) {
  return r.contract_id + " / schema " + r.schema_version + " / " + r.artifact_id + " / SHA-256 " + r.content_sha256;
}
function refList(document, parent, title, values) {
  parent.append(el(document, "h3", title));
  if (!values.length) { parent.append(el(document, "p", "No references supplied in this record.")); return; }
  const list = el(document, "ul");
  for (const r of values) list.append(el(document, "li", refText(r)));
  parent.append(list);
}
export function renderRecord(document, parent, record, now = Date.now()) {
  parent.replaceChildren();
  const r = record.reference;
  const k = Object.values(KINDS).find((value) => value.contract === r.contract_id);
  parent.append(el(document, "h3", k.label), el(document, "p", stateLabel(record.projection_state)));
  const metadata = el(document, "dl"); metadata.className = "metadata-grid";
  const validity = record.valid_until === null ? "Validity unavailable"
    : validityLabel(record.occurred_at, record.valid_until, now);
  for (const [label, value] of [
    ["Exact record", refText(r)], ["Occurred (UTC)", record.occurred_at],
    ["As of (UTC)", record.as_of ?? "Not supplied"],
    ["Valid until (UTC)", record.valid_until ?? "Not supplied"],
    ["Display-time validity hint", validity], ["Hint checked at (UTC)", new Date(now).toISOString()],
  ]) {
    const pair = el(document, "div"); pair.append(el(document, "dt", label), el(document, "dd", value)); metadata.append(pair);
  }
  parent.append(metadata);
  const link = el(document, "a", "Link to this exact record"); link.href = recordLink(r); parent.append(link);
  parent.append(el(document, "h3", "Recorded reason codes"));
  const reasons = el(document, "ul");
  for (const reason of record.reasons) reasons.append(el(document, "li", reason));
  parent.append(record.reasons.length ? reasons : el(document, "p", "Reason codes not supplied. No reason is inferred."));
  parent.append(el(document, "h3", "Bound evidence reports"));
  const evidence = evidenceReferences(record);
  if (!evidence.length) parent.append(el(document, "p",
    "No evidence package is linked to this record. A NO_TRADE decision may exist without a package; none is guessed."));
  for (const ref of evidence) {
    const item = el(document, "p"); const a = el(document, "a", refText(ref));
    a.href = evidenceLink(ref); item.append(a); parent.append(item);
  }
  refList(document, parent, "Exact lineage references", record.lineage);
  parent.append(el(document, "h3", "Recorded lifecycle history"));
  if (!record.lifecycle_events.length) parent.append(el(document, "p", "Lifecycle history not supplied."));
  for (const event of record.lifecycle_events) {
    const item = el(document, "details");
    item.append(el(document, "summary", event.event_time + " / " + event.resulting_state));
    for (const [label, value] of [["Event", event.event_id], ["Prior state", event.prior_state ?? "None"],
      ["Type", event.event_type], ["Cause", event.cause], ["Recorded at", event.recorded_at],
      ["Correlation ID", event.correlation_id]]) item.append(el(document, "p", label + ": " + value));
    refList(document, item, "Event source references", event.source_references);
    parent.append(item);
  }
  parent.append(el(document, "p", "Timing hints apply at the displayed check time only; evidence can expire while the page stays open. Backend projection state is preserved. This view does not revalidate qualification or authorize a trade."));
}
export async function bootstrapBoard({ document, fetcher = globalThis.fetch, search = "" }) {
  const byId = (id) => document.getElementById(id);
  const kindSelect = byId("record-kind"); const stateSelect = byId("record-state");
  const rows = byId("record-list"); const summary = byId("board-status");
  const watch = byId("watch-status"); const detail = byId("record-detail"); const detailStatus = byId("detail-status");
  const first = byId("read-records"); const next = byId("next-records");
  let cursor = null; let pageSequence = 0;
  const loader = createSelectionLoader({ fetcher,
    clear(loading) { detail.replaceChildren(); detailStatus.textContent = loading ? "Reading the exact stored record…" : "Select a record. No detail is displayed."; },
    show(record) { renderRecord(document, detail, record); detailStatus.textContent = "Stored research record loaded. This is not a trade instruction."; },
    fail(error) { detail.replaceChildren(); detailStatus.textContent = error.message; },
  });
  async function page(requestedCursor) {
    const current = ++pageSequence;
    loader.reset(); rows.replaceChildren(); next.disabled = true; first.disabled = true;
    watch.textContent = "WATCH availability not yet supplied.";
    summary.textContent = "Reading persisted research records…";
    const selected = { kind: kindSelect.value, state: stateSelect.value, cursor: requestedCursor };
    try {
      const result = await listRecords(fetcher, selected);
      if (current !== pageSequence) return;
      cursor = result.next_cursor;
      summary.textContent = result.items.length ? result.items.length + " stored records on this page."
        : "No stored records match this selection. An empty list is not a NO_TRADE decision or a signal.";
      watch.textContent = "Server WATCH status: " + result.watch_status;
      for (const record of result.items) {
        const card = el(document, "section"); card.className = "panel";
        card.append(el(document, "h3", KINDS[selected.kind].label), el(document, "p", stateLabel(record.projection_state)),
          el(document, "p", record.occurred_at), el(document, "p", refText(record.reference)),
          el(document, "p", record.reasons.length ? record.reasons.join(" · ") : "Reason codes not supplied."));
        const button = el(document, "button", "Read exact record"); button.type = "button";
        button.addEventListener("click", () => { void loader.load(record.reference); });
        card.append(button); rows.append(card);
      }
      next.disabled = cursor === null;
    } catch (error) { if (current === pageSequence) { cursor = null; summary.textContent = error.message; } }
    finally { if (current === pageSequence) first.disabled = false; }
  }
  kindSelect.addEventListener("change", () => { void page(null); });
  stateSelect.addEventListener("change", () => { void page(null); });
  first.addEventListener("click", () => { void page(null); });
  next.addEventListener("click", () => { if (cursor !== null) void page(cursor); });
  try {
    const reference = recordFromQuery(search);
    if (reference) {
      kindSelect.value = Object.entries(KINDS).find(([, k]) => k.contract === reference.contract_id)[0];
      summary.textContent = "Exact record link selected. Read the first page to browse.";
      await loader.load(reference); return;
    }
  } catch (error) { summary.textContent = "Invalid exact-record link."; detailStatus.textContent = error.message; return; }
  await page(null);
}
if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", () => {
    void bootstrapBoard({ document, search: globalThis.location.search });
  }, { once: true });
}
