import test from "node:test";
import assert from "node:assert/strict";
import { id } from "./evidence-fixture.mjs";
import {
  createSelectionLoader, evidenceReferences, listRecords, readRecord, recordFromQuery,
  recordLink, stateLabel, validateRecord, validateReference,
} from "../../apps/web/src/signal-board.mjs";

function record(n = 1, contract = "C-026", schema = "2") {
  return { reference: { contract_id: contract, artifact_id: id(n), schema_version: schema, content_sha256: "a".repeat(64) },
    occurred_at: "2026-01-01T00:00:00Z", as_of: null, valid_until: "2026-01-01T01:00:00Z",
    projection_state: "NO_TRADE", reasons: ["VALIDATION_MISSING"], lineage: [], lifecycle_events: [] };
}
const response = (value) => ({ ok: true, json: async () => value });
test("board requests pin kind/schema/state/cursor and perform only local no-store GETs", async () => {
  const value = record(); const calls = [];
  const fetcher = async (url, options) => { calls.push({ url, options }); return response({
    items: [value], next_cursor: null, watch_status: "UNAVAILABLE_NOT_PRODUCED",
  }); };
  await listRecords(fetcher, { kind: "NO_TRADE", state: "NO_TRADE", cursor: "opaque/+&=" });
  assert.equal(calls.length, 1);
  const url = new URL(calls[0].url);
  assert.equal(url.origin, "http://127.0.0.1:8000");
  assert.equal(url.searchParams.get("contract_id"), "C-026");
  assert.equal(url.searchParams.get("schema_version"), "2");
  assert.equal(url.searchParams.get("projection_state"), "NO_TRADE");
  assert.equal(url.searchParams.get("cursor"), "opaque/+&=");
  assert.equal(url.searchParams.get("limit"), "20");
  assert.equal(calls[0].options.method, "GET");
  assert.equal(calls[0].options.credentials, "omit");
  assert.equal(calls[0].options.cache, "no-store");
});
test("exact links and detail identity do not permit unsupported versions or swapped records", async () => {
  const value = record(); const ref = value.reference;
  assert.deepEqual(recordFromQuery(new URL(recordLink(ref), "http://desk.invalid/").search), ref);
  assert.equal(recordFromQuery(""), null);
  assert.equal(new URL(recordLink(ref), "http://desk.invalid/").hash, "#my-results");
  assert.throws(() => recordFromQuery(new URL(recordLink(ref), "http://desk.invalid/").search + "&schema_version=3"));
  assert.throws(() => validateReference({ ...ref, schema_version: "3" }, true));
  assert.throws(() => validateReference({ ...ref, artifact_id: "../evaluate" }, true));
  let calls = 0;
  await assert.rejects(readRecord(async () => { calls++; return response(record(2)); }, ref));
  assert.equal(calls, 1);
  await assert.rejects(readRecord(async () => { calls++; }, { ...ref, contract_id: "C-028" }));
  assert.equal(calls, 1);
});
test("empty results are not decisions, and mismatched pages or filters fail closed", async () => {
  const selection = { kind: "NO_TRADE", state: "", cursor: null };
  const empty = { items: [], next_cursor: null, watch_status: "UNAVAILABLE_NOT_PRODUCED" };
  assert.deepEqual(await listRecords(async () => response(empty), selection), empty);
  for (const page of [
    { ...empty, items: Array(21).fill(record()) },
    { ...empty, items: [record(1, "C-070")] },
    { ...empty, next_cursor: "" },
    { ...empty, items: [record(), record()] },
  ]) await assert.rejects(listRecords(async () => response(page), selection));
  let calls = 0;
  await assert.rejects(listRecords(async () => { calls++; }, { ...selection, state: "ARBITRARY" }));
  assert.equal(calls, 0);
});
test("record kind and backend lifecycle projection remain separate and unknown stays unknown", () => {
  const candidate = record(1, "C-023", "1");
  assert.equal(validateRecord(candidate), candidate);
  assert.equal(candidate.projection_state, "NO_TRADE");
  assert.match(stateLabel(candidate.projection_state), /NO_TRADE/);
  assert.match(stateLabel(null), /unavailable/);
  assert.match(stateLabel("CUSTOM_UNKNOWN"), /Unsupported/);
  const missing = record(); delete missing.valid_until;
  assert.throws(() => validateRecord(missing));
});
test("evidence links use only exact returned C-024v2 lineage/history references", () => {
  const value = record(); const ref = { ...record(3).reference, contract_id: "C-024" };
  assert.deepEqual(evidenceReferences(value), []);
  value.lineage = [ref, { ...ref, schema_version: "3" }];
  value.lifecycle_events = [{ source_references: [ref] }];
  assert.deepEqual(evidenceReferences(value), [ref]);
});
test("selector reset rejects late success/failure and clears previous detail immediately", async () => {
  const pending = []; const shown = []; const failures = []; let clears = 0;
  const loader = createSelectionLoader({
    fetcher: () => new Promise((done) => pending.push(done)),
    clear: () => clears++, show: (value) => shown.push(value), fail: (error) => failures.push(error),
  });
  const first = loader.load(record(1).reference);
  loader.reset();
  pending[0](response(record(1))); await first;
  assert.equal(shown.length, 0); assert.equal(clears, 2);
  const second = loader.load(record(2).reference);
  const third = loader.load(record(3).reference);
  pending[2](response(record(3))); await third;
  pending[1]({ ok: false, status: 503 }); await second;
  assert.equal(shown.length, 1); assert.equal(shown[0].reference.artifact_id, id(3));
  assert.equal(failures.length, 0);
  const fourth = loader.load(record(4).reference);
  pending[3]({ ok: false, status: 404 }); await fourth;
  assert.equal(failures.length, 1); assert.match(failures[0].message, /No stored record/);
});
