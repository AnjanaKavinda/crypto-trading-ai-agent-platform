"""Deterministic current-head R1 human gate.

R1 deliberately has no reviewer execution result or provider provenance.  The
only approval evidence is the authenticated GitHub review by the repository
owner, bound to the freshly fetched head and successful required checks.
"""
from __future__ import annotations

import fnmatch
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping

from orchestrator import (GovernanceError, detect_high_confidence_secret_material,
                          extract_bounded_path_section)
from review_provenance import derive_current_dispatch_key
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
    comments: Iterable[Mapping[str, Any]] = (),
    changed_files: Iterable[str] = (),
    diff: str = "",
    forbidden_paths: Iterable[str] = (
        "secrets/**", "**/secrets/**", ".env", "**/.env",
        "services/execution/**",
    ),
) -> dict[str, Any]:
    """Return a deterministic, aggregated result for the current head."""
    failures: list[str] = []
    head = str((pr.get("head") or {}).get("sha") or "")
    if not head:
        failures.append("current PR head is missing")
    if (pr.get("base") or {}).get("ref") != "dev":
        failures.append("PR base branch is not dev")
    author = pr.get("user") or {}
    if (author.get("login"), author.get("type"), author.get("id")) != (
            "Copilot", "Bot", 198982749):
        failures.append("PR author is not the governed Copilot identity")
    try:
        issue_id = extract_linked_issue(pr.get("body") or "")
    except GovernanceError as error:
        failures.append(str(error))
        issue_id = None
    if issue_id is not None and issue.get("number") is not None and int(issue["number"]) != issue_id:
        failures.append("R1 gate issue binding is invalid")
    if required_review_tier_from_labels(issue.get("labels", [])) != "R1":
        return {"state": "not-applicable", "head_sha": head, "reason": "review tier is not R1"}
    required = tuple(str(name).strip() for name in required_checks if str(name).strip())
    if not required:
        failures.append("required deterministic checks are not configured")
    try:
        dispatch_key = derive_current_dispatch_key(
            comments=comments, pr_number=int(pr["number"]), issue_id=int(issue_id or -1),
            base=(pr.get("base") or {}).get("ref", ""), head_sha=head,
            pr_body=pr.get("body") or "")
    except (GovernanceError, KeyError, TypeError, ValueError) as error:
        failures.append(f"current trusted PR dispatch binding is invalid: {error}")
        dispatch_key = ""
    try:
        allowed = extract_bounded_path_section(issue.get("body") or "")
    except GovernanceError as error:
        failures.append(f"allowed path scope is invalid: {error}")
        allowed = ()
    paths = tuple(str(path) for path in changed_files)
    if not paths:
        failures.append("complete changed-file list is missing")
    if not diff:
        failures.append("complete PR diff is missing")
    elif detect_high_confidence_secret_material(diff):
        failures.append("complete PR diff contains credential material")
    for path in paths:
        try:
            normalized = str(PurePosixPath(path))
            if (not path or path.startswith("/") or "\\" in path or
                    any(part in ("", ".", "..") for part in PurePosixPath(path).parts)):
                raise ValueError
        except (ValueError, TypeError):
            failures.append(f"changed path is unsafe: {path}")
            continue
        if any(fnmatch.fnmatchcase(normalized, pattern) for pattern in forbidden_paths):
            failures.append(f"changed path is forbidden: {path}")
        if allowed and not any(fnmatch.fnmatchcase(normalized, pattern) for pattern in allowed):
            failures.append(f"changed path is outside governed scope: {path}")
    checks = _checks(status, check_runs)
    missing = [name for name in required if checks.get(name) != "success"]
    failures.extend(f"required check is missing or failed: {name}" for name in missing)
    approved = any(
        review.get("user", {}).get("login") == controller
        and str(review.get("commit_id") or "") == head
        and str(review.get("state") or "").upper() == "APPROVED"
        for review in reviews
    )
    if not approved and not failures:
        return {"state": "pending", "head_sha": head, "reason": "current-head human approval is pending"}
    if not approved:
        failures.append("current-head human approval is pending")
    if failures:
        return {"state": "failure", "head_sha": head,
                "reason": "deterministic R1 controls failed",
                "failures": failures, "dispatch_key": dispatch_key}
    return {"state": "success", "head_sha": head,
            "reason": "current-head AnjanaKavinda approval and deterministic checks passed",
            "dispatch_key": dispatch_key}
