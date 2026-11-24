// Synthetic wire-shape fixture only; no market data or qualification claim.
export const id = (n) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
export function evidenceFixture(n = 1) {
  const ref = (artifact_type, value) => ({ artifact_type, artifact_id: id(value),
    version: artifact_type === "C-021" ? "1.2.3" : "2", content_sha256: "a".repeat(64) });
  const selected = { contract_id: "C-024", artifact_id: id(n), schema_version: "2", content_sha256: "b".repeat(64) };
  const created = "2026-01-01T00:00:00Z";
  const expiry = "2026-01-01T01:00:00Z";
  const support = ref("C-008", 10);
  const contradiction = ref("C-008", 11);
  return {
    artifact: { reference: selected, occurred_at: created, valid_until: expiry,
      projection_state: "NO_TRADE", reasons: ["VALIDATION_MISSING"], lineage: [], lifecycle_events: [] },
    evidence: { contract_id: "C-024", schema_version: "2", package_id: id(n), content_sha256: selected.content_sha256,
      created_at: created, expires_at: expiry, candidate: ref("C-023", 2), strategy_version: ref("C-021", 3),
      eligibility: ref("C-022", 4), market_context: ref("C-006", 5), analysis_snapshot: ref("C-007", 6),
      data_quality_report: ref("C-003", 7), confluence: ref("C-009", 8),
      candidate_valid_until: expiry, market_context_valid_until: expiry, analysis_snapshot_valid_until: expiry,
      evidence_references: [support, contradiction], supporting_evidence: [support], contradictory_evidence: [contradiction],
      conflicts: [ref("C-010", 20)], uncertainties: [ref("C-069", 21)], adversarial_assessment: null,
      adversarial_assessment_required: false, dependence: { assessment: ref("C-093", 22), state: "UNKNOWN" },
      graph: { nodes: [
        { node_id: id(30), node_type: "EVIDENCE", reference: support, dependence: "UNKNOWN", observed_at: created,
          valid_until: expiry, method: ref("METHOD", 40) },
        { node_id: id(31), node_type: "FINDING", reference: ref("C-008", 12), dependence: "HIGHLY_CORRELATED",
          observed_at: created, valid_until: expiry, method: ref("METHOD", 41) },
      ], edges: [{ source_node_id: id(30), target_node_id: id(31), relationship: "SUPPORTS" }] },
    },
  };
}
