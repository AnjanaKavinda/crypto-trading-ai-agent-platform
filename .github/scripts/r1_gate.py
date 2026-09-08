"""Deterministic current-head R1 human gate.

R1 deliberately has no reviewer execution result or provider provenance.  The
only approval evidence is the authenticated GitHub review by the repository
owner, bound to the freshly fetched head and successful required checks.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from orchestrator import GovernanceError
from review_provenance import extract_linked_issue, required_review_tier_from_labels


def _checks(status: Mapping[str, Any], check_runs: Any) -> dict[str, str]:
    result = {
        str(item["context"]): str(item.get("state") or "pending").lower()
        for item in status.get("statuses", [])
        if item.get("context")
    }
    pages = check_runs if isinstance(check_runs, list) else [check_runs]
    for page in pages:
        for item in page.get("check_runs", []):
            if item.get("name"):
                result[str(item["name"])] = str(
                    item.get("conclusion") or "pending").lower()
    return result


def evaluate_r1_gate(
    pr: Mapping[str, Any],
    reviews: Iterable[Mapping[str, Any]],
    issue: Mapping[str, Any],
    status: Mapping[str, Any],
    check_runs: Any,
    *,
    controller: str = "AnjanaKavinda",
    required_checks: Iterable[str] = (),
) -> dict[str, Any]:
    """Return ``pending`` or ``success`` for the current trusted snapshots."""
    head = str((pr.get("head") or {}).get("sha") or "")
    if not head or (pr.get("base") or {}).get("ref") != "dev":
        raise GovernanceError("R1 gate requires a current dev PR head")
    issue_id = extract_linked_issue(pr.get("body") or "")
    if issue.get("number") is not None and int(issue["number"]) != issue_id:
        raise GovernanceError("R1 gate issue binding is invalid")
    if required_review_tier_from_labels(issue.get("labels", [])) != "R1":
        return {"state": "not-applicable", "head_sha": head, "reason": "review tier is not R1"}
    checks = _checks(status, check_runs)
    missing = [name for name in required_checks if checks.get(name) != "success"]
    approved = any(
        review.get("user", {}).get("login") == controller
        and str(review.get("commit_id") or "") == head
        and str(review.get("state") or "").upper() == "APPROVED"
        for review in reviews
    )
    if not approved:
        return {"state": "pending", "head_sha": head, "reason": "current-head human approval is pending"}
    if missing:
        return {"state": "pending", "head_sha": head,
                "reason": "required deterministic checks are pending or failed",
                "missing_checks": missing}
    return {"state": "success", "head_sha": head,
            "reason": "current-head AnjanaKavinda approval and deterministic checks passed"}
