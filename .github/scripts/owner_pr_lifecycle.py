"""Explicit, append-only state bindings for direct-owner PRs."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from orchestrator import GovernanceError
from review_provenance import extract_linked_issue

OWNER_MARKER = "<!-- governed-direct-owner-pr:v1 -->"
OWNER_RECORD_PREFIX = "OWNER_PR_STATE "
OWNER_STATES = {
    "workflow:review", "workflow:changes-requested", "workflow:ready-to-merge",
    "workflow:human-decision-required", "workflow:complete",
}


def validate_direct_owner_pr(pr: Mapping[str, Any], issue: Mapping[str, Any], *,
                             repository: str, controller: str,
                             target_state: str, event_action: str,
                             comments: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Validate owner origin and exact issue/repository/base/head binding."""
    try:
        linked_issue = extract_linked_issue(str(pr.get("body") or ""))
    except GovernanceError as error:
        raise GovernanceError("direct-owner PR must link exactly one valid issue") from error
    head = pr.get("head") or {}
    base = pr.get("base") or {}
    author = (pr.get("user") or {}).get("login")
    if (not controller or author != controller or target_state not in OWNER_STATES
            or str(base.get("ref") or "") != "dev"
            or str(head.get("sha") or "") == ""
            or (issue.get("state") != "open" and
                not (target_state == "workflow:complete" and pr.get("merged")))
            or int(issue.get("number", -1)) != linked_issue
            or (base.get("repo") or {}).get("full_name") not in (None, repository)
            or (head.get("repo") or {}).get("full_name") not in (None, repository)):
        raise GovernanceError("direct-owner PR origin or binding is invalid")

    previous = latest_owner_record(comments, repository=repository,
                                   pr_number=int(pr["number"]))
    if target_state == "workflow:review":
        if event_action not in {"opened", "reopened", "synchronize"}:
            raise GovernanceError("direct-owner review entry requires an open or sync event")
        if event_action == "synchronize":
            if previous is None:
                raise GovernanceError("direct-owner synchronize has no prior owner binding")
            if (previous.get("issue_id") != linked_issue or
                    previous.get("base_branch") != "dev" or
                    previous.get("implementation_identity") != f"github-user:{controller}"):
                raise GovernanceError("direct-owner synchronize conflicts with prior binding")
        elif previous is not None and (
                previous.get("issue_id") != linked_issue or
                previous.get("base_branch") != "dev" or
                previous.get("controller_identity") != controller):
            raise GovernanceError("direct-owner PR has a conflicting prior binding")
    else:
        if previous is None or not owner_record_matches(
                previous, repository=repository, pr_number=int(pr["number"]),
                issue_id=linked_issue, head_sha=str(head["sha"]), base_branch="dev",
                controller=controller):
            raise GovernanceError("direct-owner lifecycle is not bound to the current PR head")
        if target_state == "workflow:complete":
            if not pr.get("merged") or target_state not in OWNER_STATES:
                raise GovernanceError("direct-owner completion requires a merged PR")
            if previous.get("state") != "workflow:ready-to-merge":
                raise GovernanceError("direct-owner completion lacks current-head ready state")
        elif target_state in {"workflow:ready-to-merge", "workflow:changes-requested"}:
            expected = {"workflow:ready-to-merge": "approved",
                        "workflow:changes-requested": "changes-requested"}[target_state]
            # The caller passes a verified signed review result after this validator.
            if previous.get("state") not in {
                    "workflow:review", "workflow:changes-requested"}:
                raise GovernanceError("direct-owner review transition is invalid")
            return {"issue_id": linked_issue, "previous": previous,
                    "expected_disposition": expected, "head_sha": str(head["sha"])}
        elif target_state == "workflow:human-decision-required":
            if previous.get("state") not in OWNER_STATES:
                raise GovernanceError("direct-owner human decision transition is invalid")
    return {"issue_id": linked_issue, "previous": previous,
            "head_sha": str(head["sha"])}


def owner_record_matches(record: Mapping[str, Any], *, repository: str,
                         pr_number: int, issue_id: int, head_sha: str,
                         base_branch: str, controller: str) -> bool:
    return (record.get("origin") == "DIRECT_OWNER"
            and record.get("repository") == repository
            and record.get("pr_number") == pr_number
            and record.get("issue_id") == issue_id
            and record.get("head_sha") == head_sha
            and record.get("base_branch") == base_branch
            and record.get("controller_identity") == controller
            and record.get("implementation_identity") == f"github-user:{controller}")


def latest_owner_record(comments: Iterable[Mapping[str, Any]], *,
                        repository: str, pr_number: int) -> dict[str, Any] | None:
    records: list[tuple[tuple[int, str], dict[str, Any]]] = []
    for comment in comments:
        if ((comment.get("user") or {}).get("login") != "github-actions[bot]"
                or OWNER_MARKER not in str(comment.get("body") or "")):
            continue
        line = next((line for line in str(comment.get("body") or "").splitlines()
                     if line.startswith(OWNER_RECORD_PREFIX)), None)
        if line is None:
            raise GovernanceError("trusted direct-owner state record is malformed")
        try:
            record = json.loads(line[len(OWNER_RECORD_PREFIX):])
        except (json.JSONDecodeError, TypeError) as error:
            raise GovernanceError("trusted direct-owner state record is malformed") from error
        if not isinstance(record, dict):
            raise GovernanceError("trusted direct-owner state record is malformed")
        if record.get("repository") == repository and record.get("pr_number") == pr_number:
            if (record.get("origin") != "DIRECT_OWNER"
                    or record.get("state") not in OWNER_STATES
                    or not record.get("head_sha") or not record.get("controller_identity")
                    or not record.get("implementation_identity")):
                raise GovernanceError("trusted direct-owner state record is invalid")
            records.append(((int(comment.get("id") or 0),
                             str(comment.get("created_at") or "")), record))
    return max(records, key=lambda item: item[0])[1] if records else None


def make_owner_record(*, repository: str, pr_number: int, issue_id: int,
                      head_sha: str, base_branch: str, controller: str,
                      state: str, event_action: str) -> dict[str, Any]:
    if (not repository or not controller or not head_sha or base_branch != "dev"
            or state not in OWNER_STATES):
        raise GovernanceError("direct-owner state record is incomplete")
    return {
        "origin": "DIRECT_OWNER",
        "implementation_identity": f"github-user:{controller}",
        "controller_identity": controller,
        "repository": repository,
        "issue_id": int(issue_id),
        "pr_number": int(pr_number),
        "head_sha": head_sha,
        "base_branch": base_branch,
        "state": state,
        "event_action": event_action,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
