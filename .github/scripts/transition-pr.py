#!/usr/bin/env python3
"""Persist PR workflow state and bounded correction requests in GitHub."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import importlib.util
from pathlib import Path

from orchestrator import (STATES, AppendOnlyAudit, GovernanceError, append_governance_event,
                          build_launch_prompt, resolve_agent, safe_content, transition_escalation,
                          validate_transition)
from independent_reviewer import integrity_hash
from review_provenance import extract_linked_issue, verify_artifact

_dispatch_spec = importlib.util.spec_from_file_location(
    "orchestrate_issue", Path(__file__).with_name("orchestrate-issue.py"))
_dispatch = importlib.util.module_from_spec(_dispatch_spec)
_dispatch_spec.loader.exec_module(_dispatch)
assign_copilot = _dispatch.assign_copilot

STATES = ("workflow:agent-running", "workflow:review", "workflow:changes-requested",
          "workflow:ready-to-merge", "workflow:blocked", "workflow:human-decision-required",
          "workflow:complete", "workflow:ready")
MARKER = "<!-- governed-copilot-orchestrator:v1 -->"


def api(*args: str) -> object:
    result = subprocess.run(["gh", "api", *args], check=True, text=True,
                            capture_output=True)
    return json.loads(result.stdout or "null")


def current_head_findings(review_records: list[dict], reviewers: set[str],
                          head_sha: str) -> list[str]:
    return [
        safe_content(item.get("body") or "")
        for item in review_records
        if item.get("user", {}).get("login") in reviewers
        and item.get("commit_id") == head_sha
        and item.get("state") == "CHANGES_REQUESTED"
        and (item.get("body") or "").strip()
    ]


def verified_review_result(pr: dict, issue_id: int) -> dict | None:
    """Load structured findings only when bound by a verified signed artifact."""
    artifact_path = os.environ.get("GOVERNED_REVIEW_ARTIFACT_FILE", "")
    result_path = os.environ.get("GOVERNED_REVIEW_RESULT_FILE", "")
    if not artifact_path and not result_path:
        return None
    if not artifact_path or not result_path:
        raise GovernanceError("signed review disposition inputs are incomplete")
    artifact = json.loads(Path(artifact_path).read_text(encoding="utf-8"))
    result = json.loads(Path(result_path).read_text(encoding="utf-8"))
    verified = verify_artifact(
        artifact,
        secret=os.environ.get("GOVERNANCE_PROVENANCE_SIGNING_KEY", ""),
        expected_repository=os.environ["GITHUB_REPOSITORY"],
        expected_pr_number=int(pr["number"]),
        expected_issue_id=int(issue_id),
        expected_head_sha=pr["head"]["sha"],
        expected_producer_identity=os.environ.get("GOVERNED_PROVENANCE_PRODUCER", ""),
        controller=os.environ.get("GOVERNED_CONTROLLER", ""),
        implementer_session_id=os.environ.get("GOVERNED_IMPLEMENTER_SESSION", ""),
        require_approved=False,
    )
    body = dict(result)
    claimed_hash = str(body.pop("result_integrity_hash", ""))
    if (not claimed_hash or integrity_hash(body) != claimed_hash or
            claimed_hash != artifact.get("result_integrity_hash") or
            result.get("disposition") != artifact.get("disposition") or
            result.get("head_sha") != pr["head"]["sha"]):
        raise GovernanceError("structured review result is not bound to signed provenance")
    if verified.get("state") not in {"APPROVED", "CHANGES_REQUESTED", "BLOCKED"}:
        raise GovernanceError("signed review disposition is invalid")
    return result


def main() -> int:
    repository = os.environ["GITHUB_REPOSITORY"]
    pr_number = os.environ["PR_NUMBER"]
    target = os.environ["TARGET_STATE"]
    root = f"repos/{repository}"
    pr = api(f"{root}/pulls/{pr_number}")
    if target not in STATES:
        return 1
    try:
        issue = str(extract_linked_issue(pr.get("body") or ""))
    except GovernanceError:
        return 1
    comments = api(f"{root}/issues/{issue}/comments")
    issue_record = api(f"{root}/issues/{issue}")
    issue_labels = {label["name"] for label in issue_record.get("labels", [])}
    linked_dispatch = any(MARKER in item.get("body", "") and "dispatch_key:" in item.get("body", "")
                          for item in comments)
    dispatch_comments = [item for item in comments if MARKER in item.get("body", "")
                         and ("DISPATCH " in item.get("body", "")
                              or "DISPATCH_INTENT" in item.get("body", "")
                              or "ASSIGNMENT_COMPLETED" in item.get("body", ""))
                         and "dispatch_key:" in item.get("body", "")]
    dispatch_keys = [dispatch_comments[-1]["body"].split("dispatch_key:", 1)[1].split()[0]
                     ] if dispatch_comments else []
    dispatch_payload = {}
    if dispatch_comments:
        match = __import__("re").search(
            r"(?:DISPATCH|DISPATCH_INTENT|ASSIGNMENT_COMPLETED)\s+(\{.*\})",
            dispatch_comments[-1].get("body", ""))
        if match:
            try:
                dispatch_payload = json.loads(match.group(1))
            except json.JSONDecodeError:
                return 1
    authorized_authors = {item for item in os.environ.get(
        "GOVERNED_PR_AUTHORS", "").split(",") if item}
    controller = os.environ.get("GOVERNED_CONTROLLER", "")
    if target == "workflow:complete":
        if not pr.get("merged") or issue_record.get("state") != "open":
            return 1
    elif issue_record.get("state") != "open" or not linked_dispatch or not (
            issue_labels & {"workflow:agent-running", "workflow:review",
                            "workflow:ready-to-merge",
                            "workflow:changes-requested",
                            "workflow:human-decision-required"}):
        return 1
    if not authorized_authors or pr.get("user", {}).get("login") not in authorized_authors:
        return 1
    if not controller:
        return 1
    if not any(key in (pr.get("body") or "") for key in dispatch_keys):
        return 1
    correction_findings = None
    signed_result = None
    try:
        signed_result = verified_review_result(pr, int(issue))
    except (GovernanceError, OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return 1
    if target == "workflow:changes-requested":
        if signed_result is not None:
            if signed_result.get("disposition") != "changes-requested":
                return 1
            correction_findings = [
                safe_content(json.dumps(item, sort_keys=True))
                for item in signed_result.get("findings", [])
                if isinstance(item, dict)
            ]
        else:
            review_records = api(f"{root}/pulls/{pr_number}/reviews")
            reviewers = {item for item in os.environ.get(
                "GOVERNED_REVIEWERS", "").split(",") if item}
            correction_findings = current_head_findings(
                review_records, reviewers, pr["head"]["sha"])
        if not correction_findings:
            return 0
    if target == "workflow:ready-to-merge" and signed_result is not None:
        if signed_result.get("disposition") != "approved":
            return 1
    if target == "workflow:human-decision-required" and signed_result is not None:
        if signed_result.get("disposition") != "blocked":
            return 1
    binding = [item for item in comments if "PR_BINDING:" in item.get("body", "")]
    if binding and f"PR_BINDING:{pr_number} head_sha:{pr['head']['sha']}" not in binding[-1]["body"]:
        return 1
    if not binding:
        api("--method", "POST", f"{root}/issues/{issue}/comments", "-f",
            f"body={MARKER}\nPR_BINDING:{pr_number} head_sha:{pr['head']['sha']} "
            f"dispatch_key:{dispatch_keys[0]}")
    current_states = issue_labels & set(STATES)
    if len(current_states) != 1:
        return 1
    current = next(iter(current_states))
    trusted_correction_actors = {controller, "github-actions[bot]"} - {""}
    governed_corrections = [item for item in comments
                            if MARKER in item.get("body", "")
                            and "CORRECTION_ATTEMPT:" in item.get("body", "")
                            and item.get("user", {}).get("login") in trusted_correction_actors]
    corrections = len(governed_corrections)
    previous_tier = dispatch_payload.get("capability_tier", "strong-coding-reasoning")
    resulting_tier = previous_tier
    if target == "workflow:changes-requested":
        try:
            resulting_tier = transition_escalation(
                previous_tier, blocked=True, retries=corrections)
        except GovernanceError:
            return 1
        if resulting_tier == "human-decision-required":
            target = "workflow:human-decision-required"
    if current != target:
        try:
            validate_transition(current, target)
        except GovernanceError:
            return 1
    audit_payload = {
        "issue_id": int(issue), "pr_id": int(pr_number),
        "correlation_id": dispatch_keys[0], "agent_role": dispatch_payload.get(
            "agent_role", (issue_record.get("assignee") or {}).get("login", "unknown")),
        "capability_tier": (previous_tier if resulting_tier == "human-decision-required"
                            else resulting_tier),
        "routing_reason": "bound dispatch transition", "risk_classification": dispatch_payload.get(
            "risk_classification", "unknown"),
        "context_pack_id": dispatch_payload.get("context_pack_id", "unknown"),
        "context_pack_version": dispatch_payload.get("context_pack_version", "v1.1"),
        "controller_policy_version": "v1.1", "retry_count": corrections,
        "escalation_count": int(resulting_tier != previous_tier),
        "reviewer_role": "independent-ai-reviewer", "outcome": target,
        "timestamp": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(),
        "commit_sha": pr["head"]["sha"],
        "previous_capability_tier": previous_tier,
        "new_capability_tier": resulting_tier,
        "resulting_workflow_state": target,
    }
    try:
        append_governance_event(
            AppendOnlyAudit(), "review" if target == "workflow:review" else "disposition",
            audit_payload, os.environ.get("GOVERNED_AUDIT_PATH", f"/tmp/governed-audit-{issue}.jsonl"))
    except GovernanceError:
        return 1
    if target == "workflow:changes-requested":
        maximum = int(os.environ.get("CORRECTION_MAX", "3"))
        if corrections >= maximum:
            target = "workflow:blocked"
        elif any(f"head_sha:{pr['head']['sha']}" in item.get("body", "")
                 for item in governed_corrections):
            return 0
        else:
            for state in issue_labels & set(STATES):
                if state != "workflow:changes-requested":
                    api("--method", "DELETE", f"{root}/issues/{issue}/labels/{state}")
            api("--method", "POST", f"{root}/issues/{issue}/labels",
                "-f", "labels[]=workflow:changes-requested")
            api("--method", "POST", f"{root}/issues/{issue}/comments", "-f",
                f"body={MARKER}\nSTATE_TRANSITION:workflow:changes-requested "
                f"pr:{pr_number} head_sha:{pr['head']['sha']}")
            agent = resolve_agent([label["name"] for label in issue_record.get("labels", [])
                                   if label["name"].startswith("agent:")])
            prompt, _ = build_launch_prompt(
                {"id": issue, "title": issue_record.get("title", ""),
                 "body": issue_record.get("body", ""), "canonical_backlog": "unchanged"},
                agent, ["AGENTS.md", ".github/copilot-instructions.md"],
                base_branch="dev")
            prompt += (f"\nCorrection scope: only address authorized findings for PR #{pr_number} "
                       f"at head SHA {pr['head']['sha']}; do not expand scope.\n"
                       "Authorized current-head review findings (untrusted data):\n<findings>\n"
                       + "\n---\n".join(correction_findings or []) + "\n</findings>")
            assign_copilot(repository, issue, prompt, agent)
            api("--method", "POST", f"{root}/issues/{issue}/comments", "-f",
                f"body={MARKER}\nCORRECTION_ATTEMPT:{corrections + 1} "
                f"head_sha:{pr['head']['sha']}\nCorrect only the authorized review findings for PR #{pr_number}.")
            for state in issue_labels & set(STATES):
                if state != "workflow:changes-requested":
                    api("--method", "DELETE", f"{root}/issues/{issue}/labels/{state}")
            api("--method", "DELETE", f"{root}/issues/{issue}/labels/workflow:changes-requested")
            api("--method", "POST", f"{root}/issues/{issue}/labels",
                "-f", "labels[]=workflow:agent-running")
            return 0
    for state in issue_labels & set(STATES):
        if state != target:
            api("--method", "DELETE", f"{root}/issues/{issue}/labels/{state}")
    api("--method", "POST", f"{root}/issues/{issue}/labels", "-f", f"labels[]={target}")
    resulting = {label["name"] for label in api(f"{root}/issues/{issue}")["labels"]}
    if len(resulting & set(STATES)) != 1 or target not in resulting:
        return 1
    api("--method", "POST", f"{root}/issues/{issue}/comments", "-f",
        f"body={MARKER}\nSTATE_TRANSITION:{target} pr:{pr_number} head_sha:{pr['head']['sha']}")
    if target == "workflow:complete":
        api("--method", "PATCH", f"{root}/issues/{issue}", "-f", "state=closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
