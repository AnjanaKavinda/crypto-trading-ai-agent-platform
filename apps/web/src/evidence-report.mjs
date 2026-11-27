import { API_ORIGIN } from "./runtime-config.mjs";

const API = `${API_ORIGIN}/api/research/strategy-signals`;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DIGEST = /^[0-9a-f]{64}$/;
export const PAGE_SIZE = 20;

function requireValue(ok) {
  if (!ok) throw new Error("The evidence response is invalid or does not match the selected reference.");
}

function reference(value) {
  requireValue(value && typeof value.artifact_type === "string" &&
    value.artifact_type.length > 0 && UUID.test(value.artifact_id) &&
    typeof value.version === "string" && value.version.length > 0 &&
    DIGEST.test(value.content_sha256));
}

function timestamp(value) {
  requireValue(typeof value === "string" && /(?:Z|[+-]\d\d:\d\d)$/.test(value) &&
    Number.isFinite(Date.parse(value)));
}

function refs(values) {
  requireValue(Array.isArray(values) && values.length <= 64);
  values.forEach(reference);
}

export function packageReference(value) {
  requireValue(value?.contract_id === "C-024" && value.schema_version === "2" &&
    UUID.test(value.artifact_id) && DIGEST.test(value.content_sha256));
  return value;
}

export function validatePage(page) {
  requireValue(page && Array.isArray(page.items) && page.items.length <= PAGE_SIZE &&
    (page.next_cursor === null || typeof page.next_cursor === "string" &&
      page.next_cursor.length > 0 && page.next_cursor.length <= 4096));
  const ids = new Set();
  for (const item of page.items) {
    packageReference(item.reference);
    timestamp(item.occurred_at);
    const id = `${item.reference.artifact_id}:${item.reference.content_sha256}`;
    requireValue(!ids.has(id));
    ids.add(id);
  }
  return page;
}

export function validateReport(report, selected) {
  packageReference(selected);
  const artifact = report?.artifact;
  const p = report?.evidence;
  const actual = packageReference(artifact?.reference);
  requireValue(actual.artifact_id === selected.artifact_id &&
    actual.content_sha256 === selected.content_sha256 &&
    p?.contract_id === "C-024" && p.schema_version === "2" &&
    p.package_id === actual.artifact_id && p.content_sha256 === actual.content_sha256);
  timestamp(p.created_at);
  timestamp(p.expires_at);
  requireValue(Date.parse(p.created_at) < Date.parse(p.expires_at) &&
    Date.parse(artifact.occurred_at) === Date.parse(p.created_at) &&
    Date.parse(artifact.valid_until) === Date.parse(p.expires_at));
  for (const name of ["candidate", "strategy_version", "eligibility", "market_context",
    "analysis_snapshot", "data_quality_report", "confluence"]) reference(p[name]);
  for (const name of ["candidate_valid_until", "market_context_valid_until",
    "analysis_snapshot_valid_until"]) timestamp(p[name]);
  for (const name of ["evidence_references", "supporting_evidence", "contradictory_evidence",
    "conflicts", "uncertainties"]) refs(p[name]);
  if (p.adversarial_assessment !== null) reference(p.adversarial_assessment);
  requireValue(typeof p.adversarial_assessment_required === "boolean");
  reference(p.dependence?.assessment);
  const dependencies = new Set(["INDEPENDENT", "PARTIALLY_DEPENDENT", "HIGHLY_CORRELATED", "UNKNOWN"]);
  requireValue(dependencies.has(p.dependence.state));
  const graph = p.graph;
  requireValue(graph && Array.isArray(graph.nodes) && graph.nodes.length > 0 &&
    graph.nodes.length <= 256 && Array.isArray(graph.edges) && graph.edges.length > 0 &&
    graph.edges.length <= 512);
  const nodes = new Set();
  for (const node of graph.nodes) {
    requireValue(UUID.test(node.node_id) && !nodes.has(node.node_id) &&
      ["EVIDENCE", "FINDING", "STRATEGY_CONDITION", "CANDIDATE"].includes(node.node_type) &&
      dependencies.has(node.dependence));
    nodes.add(node.node_id);
    reference(node.reference);
    reference(node.method);
    timestamp(node.observed_at);
    timestamp(node.valid_until);
    requireValue(Date.parse(node.observed_at) < Date.parse(node.valid_until));
  }
  for (const edge of graph.edges) {
    requireValue(nodes.has(edge.source_node_id) && nodes.has(edge.target_node_id) &&
      typeof edge.relationship === "string" && edge.relationship.length > 0);
  }
  const key = (r) => `${r.artifact_type}:${r.artifact_id}:${r.version}:${r.content_sha256}`;
  const evidence = new Set(p.evidence_references.map(key));
  requireValue([...p.supporting_evidence, ...p.contradictory_evidence].every((r) => evidence.has(key(r))));
  return report;
}

async function get(fetcher, path, timeoutMs = 15000) {
  const controller = new AbortController();
  let timer;
  const deadline = new Promise((_, reject) => {
    timer = setTimeout(() => {
      controller.abort();
      reject(new Error("The evidence request timed out. No report was accepted."));
    }, timeoutMs);
  });
  const perform = async () => {
    let response;
    try {
      response = await fetcher(`${API}${path}`, {
        method: "GET", credentials: "omit", cache: "no-store",
        headers: { Accept: "application/json" }, signal: controller.signal,
      });
    } catch {
      throw new Error("The local evidence API is unreachable.");
    }
    if (!response.ok) {
      throw new Error(response.status === 404
        ? "No persisted report matches this exact package reference."
        : response.status === 422
          ? "The API does not support this evidence reference."
          : "The evidence API is unavailable or could not verify the stored evidence.");
    }
    try { return await response.json(); }
    catch { throw new Error("The evidence API returned an unreadable response."); }
  };
  try { return await Promise.race([perform(), deadline]); }
  finally { clearTimeout(timer); }
}

export async function listEvidence(fetcher = globalThis.fetch, cursor = null) {
  requireValue(cursor === null || typeof cursor === "string" && cursor.length > 0 && cursor.length <= 4096);
  const query = new URLSearchParams({ contract_id: "C-024", schema_version: "2", limit: String(PAGE_SIZE) });
  if (cursor !== null) query.set("cursor", cursor);
  return validatePage(await get(fetcher, `?${query}`));
}

export async function readEvidence(fetcher, selected) {
  packageReference(selected);
  const query = new URLSearchParams({ schema_version: "2", content_sha256: selected.content_sha256 });
  return validateReport(await get(fetcher, `/C-024/${selected.artifact_id}/evidence?${query}`), selected);
}

export function referenceFromQuery(search) {
  const query = new URLSearchParams(search);
  if (!["package_id", "schema_version", "content_sha256"].some((name) => query.has(name))) return null;
  requireValue([...query.keys()].every((name) => query.getAll(name).length === 1));
  return packageReference({ contract_id: "C-024", artifact_id: query.get("package_id"),
    schema_version: query.get("schema_version"), content_sha256: query.get("content_sha256") });
}

export function evidenceLink(selected) {
  packageReference(selected);
  return `./index.html?${new URLSearchParams({ package_id: selected.artifact_id,
    schema_version: selected.schema_version, content_sha256: selected.content_sha256 })}#strategy-lab`;
}

export function validityLabel(start, end, now = Date.now()) {
  return now < Date.parse(start) ? "FUTURE-DATED — not current"
    : now >= Date.parse(end) ? "EXPIRED — historical evidence"
      : "Within recorded validity window — qualification not established";
}

export function createReportLoader({ fetcher, clear, show, fail }) {
  let sequence = 0;
  return async (selected) => {
    const current = ++sequence;
    clear();
    try {
      const report = await readEvidence(fetcher, selected);
      if (current === sequence) show(report);
    } catch (error) {
      if (current === sequence) fail(error);
    }
  };
}
