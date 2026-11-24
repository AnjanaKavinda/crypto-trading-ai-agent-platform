import test from "node:test";
import assert from "node:assert/strict";
import {
  createReportLoader, evidenceLink, listEvidence, packageReference, readEvidence,
  referenceFromQuery, validatePage, validateReport, validityLabel,
} from "../../apps/web/src/evidence-report.mjs";
import { evidenceFixture, id } from "./evidence-fixture.mjs";

const response = (value) => ({ ok: true, json: async () => value });

test("exact report GET and manual cursor pagination keep loopback/no-store boundaries", async () => {
  const report = evidenceFixture();
  const calls = [];
  const page = { items: [report.artifact], next_cursor: "cursor/+&=bounded" };
  const fetcher = async (url, options) => {
    calls.push({ url, options });
    return response(url.includes("/evidence?") ? report : page);
  };
  assert.deepEqual(await listEvidence(fetcher), page);
  await listEvidence(fetcher, page.next_cursor);
  assert.deepEqual(await readEvidence(fetcher, report.artifact.reference), report);
  assert.equal(calls.length, 3);
  for (const { url, options } of calls) {
    assert.equal(new URL(url).origin, "http://127.0.0.1:8000");
    assert.equal(options.method, "GET");
    assert.equal(options.credentials, "omit");
    assert.equal(options.cache, "no-store");
  }
  assert.equal(new URL(calls[1].url).searchParams.get("cursor"), page.next_cursor);
  const last = new URL(calls[2].url);
  assert.equal(last.pathname, `/api/research/strategy-signals/C-024/${id(1)}/evidence`);
  assert.equal(last.searchParams.get("content_sha256"), report.artifact.reference.content_sha256);
});

test("exact deep links round trip and reject duplicate or unsupported identities", () => {
  const selected = evidenceFixture().artifact.reference;
  assert.deepEqual(referenceFromQuery(evidenceLink(selected).split("?")[1]), selected);
  assert.equal(referenceFromQuery(""), null);
  assert.throws(() => referenceFromQuery("package_id=bad&schema_version=2&content_sha256=bad"));
  assert.throws(() => referenceFromQuery(`${evidenceLink(selected).split("?")[1]}&schema_version=2`));
  assert.throws(() => packageReference({ ...selected, schema_version: "3" }));
});

test("invalid selected identity cannot initiate a request", async () => {
  let calls = 0;
  await assert.rejects(readEvidence(async () => { calls++; }, {
    ...evidenceFixture().artifact.reference, artifact_id: "../evaluate",
  }));
  assert.equal(calls, 0);
});

test("report binding rejects swaps, missing graph nodes and malformed evidence classifications", () => {
  const original = evidenceFixture();
  assert.equal(validateReport(original, original.artifact.reference), original);
  for (const mutate of [
    (r) => { r.evidence.package_id = id(99); },
    (r) => { r.evidence.content_sha256 = "c".repeat(64); },
    (r) => { r.evidence.graph.edges[0].source_node_id = id(99); },
    (r) => { r.evidence.graph.nodes[1].node_id = r.evidence.graph.nodes[0].node_id; },
    (r) => { r.evidence.supporting_evidence[0] = { ...r.evidence.supporting_evidence[0], artifact_id: id(99) }; },
    (r) => { r.evidence.expires_at = "not-a-time"; },
    (r) => { r.evidence.graph.nodes[0].method = null; },
  ]) {
    const report = structuredClone(original);
    mutate(report);
    assert.throws(() => validateReport(report, original.artifact.reference));
  }
});

test("empty pages are valid and excessive or mismatched pages fail instead of truncating", () => {
  assert.deepEqual(validatePage({ items: [], next_cursor: null }), { items: [], next_cursor: null });
  assert.throws(() => validatePage({ items: Array(21).fill(evidenceFixture().artifact), next_cursor: null }));
  assert.throws(() => validatePage({ items: [], next_cursor: "" }));
  const item = evidenceFixture().artifact;
  item.reference.contract_id = "C-070";
  assert.throws(() => validatePage({ items: [item], next_cursor: null }));
});

test("validity display preserves expiry and future states without claiming qualification", () => {
  const p = evidenceFixture().evidence;
  assert.match(validityLabel(p.created_at, p.expires_at, Date.parse(p.created_at) - 1), /FUTURE/);
  assert.match(validityLabel(p.created_at, p.expires_at, Date.parse(p.expires_at)), /EXPIRED/);
  assert.match(validityLabel(p.created_at, p.expires_at, Date.parse(p.created_at)), /qualification not established/);
});

test("out-of-order success and failure cannot replace the selected report", async () => {
  const pending = [];
  const shown = [];
  const failed = [];
  let clears = 0;
  const load = createReportLoader({ fetcher: () => new Promise((resolve) => pending.push(resolve)),
    clear: () => clears++, show: (r) => shown.push(r), fail: (e) => failed.push(e) });
  const first = load(evidenceFixture(1).artifact.reference);
  const second = load(evidenceFixture(2).artifact.reference);
  assert.equal(clears, 2);
  pending[1](response(evidenceFixture(2)));
  await second;
  pending[0]({ ok: false, status: 503 });
  await first;
  assert.equal(shown.length, 1);
  assert.equal(shown[0].evidence.package_id, id(2));
  assert.equal(failed.length, 0);
  const third = load(evidenceFixture(3).artifact.reference);
  assert.equal(clears, 3);
  pending[2]({ ok: false, status: 404 });
  await third;
  assert.equal(failed.length, 1);
  assert.match(failed[0].message, /No persisted report/);
});
