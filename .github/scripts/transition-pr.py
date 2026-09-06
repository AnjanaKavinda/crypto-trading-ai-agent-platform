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


def main() -> int:
    repository = os.environ["GITHUB_REPOSITORY"]
    pr_number = os.environ["PR_NUMBER"]
    target = os.environ["TARGET_STATE"]
    root = f"repos/{repository}"
    pr = api(f"{root}/pulls/{pr_number}")
    issue_match = __import__("re").search(r"(?im)\b(?:closes|fixes|resolves)\s+#(\d+)",
                                          pr.get("body") or "")
    if not issue_match or target not in STATES:
        return 1
    issue = issue_match.group(1)
    comments = api(f"{root}/issues/{issue}/comments")
    issue_record = api(f"{root}/issues/{issue}")
    issue_labels = {label["name"] for label in issue_record.get("labels", [])}
    linked_dispatch = any(MARKER in item.get("body", "") and "dispatch_key:" in item.get("body", "")
                          for item in comments)
    dispatch_comments = [item for item in comments if MARKER in item.get("body", "")
                         and "DISPATCH" in item.get("body", "")
                         and "dispatch_key:" in item.get("body", "")]
    dispatch_keys = [dispatch_comments[-1]["body"].split("dispatch_key:", 1)[1].split()[0]
                     ] if dispatch_comments else []
    dispatch_payload = {}
    if dispatch_comments:
        match = __import__("re").search(r"DISPATCH\s+(\{.*\})", dispatch_comments[-1].get("body", ""))
        if match:
            try:
                dispatch_payload = json.loads(match.group(1))
            except json.JSONDecodeError:
                return 1
    authorized_authors = {item for item in os.environ.get(
        "GOVERNED_PR_AUTHORS", "").split(",") if item}
    controller = os.environ.get("GOVERNED_CONTROLLER", "")
    if issue_record.get("state") != "open" or not linked_dispatch or not (
            issue_labels & {"workflow:agent-running", "workflow:review",
                            "workflow:ready-to-merge",
                            "workflow:changes-requested"}):
        return 1
    if not authorized_authors or pr.get("user", {}).get("login") not in authorized_authors:
        return 1
    if not controller:
        return 1
    if not any(key in (pr.get("body") or "") for key in dispatch_keys):
        return 1
    correction_findings = None
    if target == "workflow:changes-requested":
        review_records = api(f"{root}/pulls/{pr_number}/reviews")
        reviewers = {item for item in os.environ.get(
            "GOVERNED_REVIEWERS", "").split(",") if item}
        correction_findings = current_head_findings(
            review_records, reviewers, pr["head"]["sha"])
        if not correction_findings:
            # Waiting for review/checks is not a correction request.
            return 0
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
    if current != target:
        try:
            validate_transition(current, target)
        except GovernanceError:
            return 1
    audit_payload = {
        "issue_id": int(issue), "pr_id": int(pr_number),
        "correlation_id": dispatch_keys[0], "agent_role": dispatch_payload.get(
            "agent_role", (issue_record.get("assignee") or {}).get("login", "unknown")),
        "capability_tier": dispatch_payload.get("capability_tier", "strong-coding-reasoning"),
        "routing_reason": "bound dispatch transition", "risk_classification": dispatch_payload.get(
            "risk_classification", "unknown"),
        "context_pack_id": dispatch_payload.get("context_pack_id", "unknown"),
        "context_pack_version": dispatch_payload.get("context_pack_version", "v1.1"),
        "controller_policy_version": "v1.1", "retry_count": 0,
        "escalation_count": 0, "review_tier": dispatch_payload.get("review_tier", "R1"),
        "reviewer_role": "independent-ai-reviewer", "outcome": target,
        "timestamp": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(),
        "commit_sha": pr["head"]["sha"],
    }
    try:
        append_governance_event(
            AppendOnlyAudit(), "review" if target == "workflow:review" else "disposition",
            audit_payload, os.environ.get("GOVERNED_AUDIT_PATH", f"/tmp/governed-audit-{issue}.jsonl"))
    except GovernanceError:
        return 1
    governed_corrections = [item for item in comments
                            if MARKER in item.get("body", "")
                            and "CORRECTION_ATTEMPT:" in item.get("body", "")
                            and (not controller or item.get("user", {}).get("login") == controller)]
    corrections = len(governed_corrections)
    if target == "workflow:changes-requested":
        try:
            escalation = transition_escalation(
                dispatch_payload.get("capability_tier", "strong-coding-reasoning"),
                blocked=True, retries=corrections)
        except GovernanceError:
            return 1
        if escalation == "human-decision-required":
            target = "workflow:human-decision-required"
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
