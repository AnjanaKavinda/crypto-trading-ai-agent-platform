import {
  createReportLoader, evidenceLink, listEvidence, referenceFromQuery, validityLabel,
} from "./evidence-report.mjs";

function element(document, tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}

function referenceText(r) {
  return `${r.artifact_type} · version ${r.version} · ${r.artifact_id} · SHA-256 ${r.content_sha256}`;
}

function referenceList(document, parent, title, references) {
  parent.append(element(document, "h3", title));
  if (!references.length) {
    parent.append(element(document, "p", "None recorded in this package. This does not establish absence outside its scope.", "muted"));
    return;
  }
  const list = element(document, "ul");
  for (const r of references) list.append(element(document, "li", referenceText(r)));
  parent.append(list);
}

function table(document, parent, headers, rows) {
  const container = element(document, "div", undefined, "table-scroll");
  const result = element(document, "table");
  const head = element(document, "thead");
  const heading = element(document, "tr");
  for (const name of headers) {
    const cell = element(document, "th", name);
    cell.setAttribute("scope", "col");
    heading.append(cell);
  }
  head.append(heading);
  const body = element(document, "tbody");
  for (const { id, cells } of rows) {
    const row = element(document, "tr");
    if (id) row.id = `node-${id}`;
    for (const value of cells) {
      const cell = element(document, "td");
      if (typeof value === "string") cell.textContent = value;
      else cell.append(value);
      row.append(cell);
    }
    body.append(row);
  }
  result.append(head, body);
  container.append(result);
  parent.append(container);
}

export function renderEvidenceReport(document, parent, report, now = Date.now()) {
  parent.replaceChildren();
  const p = report.evidence;
  parent.append(element(document, "p", validityLabel(p.created_at, p.expires_at, now), "mode-pill"));
  const metadata = element(document, "dl", undefined, "metadata-grid");
  for (const [name, value] of [
    ["Package", `${p.package_id} · C-024 schema ${p.schema_version}`],
    ["Exact SHA-256", p.content_sha256],
    ["Created / expires (UTC)", `${p.created_at} / ${p.expires_at}`],
    ["Validity labels checked at (UTC)", new Date(now).toISOString()],
    ["Strategy semantic version", p.strategy_version.version],
    ["Recorded lifecycle", report.artifact.projection_state ?? "Not supplied"],
    ["Dependence assessment", p.dependence.state],
  ]) {
    const pair = element(document, "div");
    pair.append(element(document, "dt", name), element(document, "dd", value));
    metadata.append(pair);
  }
  parent.append(metadata);
  const link = element(document, "a", "Link to this exact report");
  link.href = evidenceLink(report.artifact.reference);
  parent.append(link);
  referenceList(document, parent, "Recorded source and context references", [
    p.candidate, p.strategy_version, p.eligibility, p.market_context,
    p.analysis_snapshot, p.data_quality_report, p.confluence, p.dependence.assessment,
  ]);
  parent.append(element(document, "p", "References retain their original versions. The strategy reference version is semantic; it is not a schema number. Full upstream source payloads are not exposed by this report.", "muted"));
  referenceList(document, parent, "Supporting evidence", p.supporting_evidence);
  referenceList(document, parent, "Contradictory evidence", p.contradictory_evidence);
  referenceList(document, parent, "All package evidence references", p.evidence_references);
  referenceList(document, parent, "Conflicts", p.conflicts);
  referenceList(document, parent, "Uncertainties", p.uncertainties);
  referenceList(document, parent, "Adversarial review reference", p.adversarial_assessment ? [p.adversarial_assessment] : []);
  parent.append(element(document, "p", `Adversarial assessment required by package: ${p.adversarial_assessment_required ? "yes" : "no"}.`, "muted"));
  parent.append(element(document, "h3", "Stored evidence graph — nodes"));
  parent.append(element(document, "p", "Complete stored package graph. Source facts, analysis findings, strategy conditions and the candidate retain distinct identities. Dependency labels are recorded assessments, not browser-calculated evidence weights.", "muted"));
  table(document, parent, ["Node / type", "Exact reference", "Dependence", "Observed / valid until", "Recorded validity", "Method reference"],
    p.graph.nodes.map((n) => ({ id: n.node_id, cells: [
      `${n.node_id} / ${n.node_type}`, referenceText(n.reference), n.dependence,
      `${n.observed_at} / ${n.valid_until}`, validityLabel(n.observed_at, n.valid_until, now), referenceText(n.method),
    ] })));
  parent.append(element(document, "h3", "Stored evidence graph — relationships"));
  table(document, parent, ["Source node", "Relationship", "Target node"], p.graph.edges.map((e) => {
    const from = element(document, "a", e.source_node_id);
    from.href = `#node-${e.source_node_id}`;
    const to = element(document, "a", e.target_node_id);
    to.href = `#node-${e.target_node_id}`;
    return { cells: [from, e.relationship, to] };
  }));
  parent.append(element(document, "h3", "Recorded validity boundaries"));
  for (const [name, value] of [["Candidate", p.candidate_valid_until], ["Market context", p.market_context_valid_until], ["Analysis snapshot", p.analysis_snapshot_valid_until]]) {
    parent.append(element(document, "p", `${name} valid until: ${value}`));
  }
  parent.append(element(document, "p", "Validity labels apply at the displayed check time only; evidence can expire while this page stays open. They use the browser clock and are not a new backend validation. Reload the exact report to check availability again; the page does not continuously refresh.", "muted"));
}

export async function bootstrapEvidence({ document, fetcher = globalThis.fetch, search = "" }) {
  const packages = document.getElementById("package-list");
  const packageStatus = document.getElementById("package-status");
  const report = document.getElementById("evidence-report");
  const status = document.getElementById("report-status");
  const next = document.getElementById("next-packages");
  const reload = document.getElementById("reload-packages");
  let cursor = null;
  let pageSequence = 0;
  const select = createReportLoader({
    fetcher,
    clear: () => { report.replaceChildren(); status.textContent = "Loading the exact persisted package…"; },
    show: (value) => { renderEvidenceReport(document, report, value); status.textContent = "Stored evidence package loaded. Statistical qualification is not established by this report."; },
    fail: (error) => { report.replaceChildren(); status.textContent = error.message; },
  });
  const page = async (requestedCursor) => {
    const sequence = ++pageSequence;
    packages.replaceChildren();
    packageStatus.textContent = "Loading stored packages…";
    next.disabled = true;
    reload.disabled = true;
    try {
      const result = await listEvidence(fetcher, requestedCursor);
      if (sequence !== pageSequence) return;
      cursor = result.next_cursor;
      packageStatus.textContent = result.items.length
        ? `${result.items.length} stored packages on this page. Select one to read its evidence.`
        : "No stored evidence packages on this page. Missing inputs or a NO_TRADE outcome may have prevented package creation; no example report is substituted.";
      for (const item of result.items) {
        const button = element(document, "button", `${item.occurred_at} · ${item.reference.artifact_id}`);
        button.type = "button";
        button.addEventListener("click", () => { void select(item.reference); });
        packages.append(button);
      }
      next.disabled = cursor === null;
    } catch (error) {
      if (sequence === pageSequence) { cursor = null; packageStatus.textContent = error.message; }
    } finally {
      if (sequence === pageSequence) reload.disabled = false;
    }
  };
  next.addEventListener("click", () => { if (cursor !== null) void page(cursor); });
  reload.addEventListener("click", () => { void page(null); });
  try {
    const selected = referenceFromQuery(search);
    if (selected) {
      packageStatus.textContent = "Exact report link selected. Read the first page to browse other packages.";
      await select(selected);
      return;
    }
  } catch (error) {
    status.textContent = error.message;
    packageStatus.textContent = "Invalid report link. Read the first page to browse stored packages.";
    return;
  }
  await page(null);
}

if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", () => {
    void bootstrapEvidence({ document, search: globalThis.location.search });
  }, { once: true });
}
