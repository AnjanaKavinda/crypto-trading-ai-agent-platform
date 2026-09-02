#!/usr/bin/env python3
"""Persist PR workflow state and bounded correction requests in GitHub."""
from __future__ import annotations

import json
import os
import subprocess
import sys

from orchestrator import STATES, GovernanceError, validate_transition

STATES = ("workflow:agent-running", "workflow:review", "workflow:changes-requested",
          "workflow:ready-to-merge", "workflow:blocked", "workflow:human-decision-required",
          "workflow:complete", "workflow:ready")
MARKER = "<!-- governed-copilot-orchestrator:v1 -->"


def api(*args: str) -> object:
    result = subprocess.run(["gh", "api", *args], check=True, text=True,
                            capture_output=True)
    return json.loads(result.stdout or "null")


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
    authorized_authors = {item for item in os.environ.get(
        "GOVERNED_PR_AUTHORS", "").split(",") if item}
    if issue_record.get("state") != "open" or not linked_dispatch or not (
            issue_labels & {"workflow:agent-running", "workflow:review",
                            "workflow:ready-to-merge",
                            "workflow:changes-requested"}):
        return 1
    if not authorized_authors or pr.get("user", {}).get("login") not in authorized_authors:
        return 1
    if not any(key in (pr.get("body") or "") for key in dispatch_keys):
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
    if current != target:
        try:
            validate_transition(current, target)
        except GovernanceError:
            return 1
    corrections = sum("CORRECTION_ATTEMPT" in item.get("body", "") for item in comments)
    if target == "workflow:changes-requested":
        maximum = int(os.environ.get("CORRECTION_MAX", "3"))
        if corrections >= maximum:
            target = "workflow:blocked"
        elif any(f"head_sha:{pr['head']['sha']}" in item.get("body", "") for item in comments
                 if "CORRECTION_ATTEMPT" in item.get("body", "")):
            return 0
        else:
            api("--method", "POST", f"{root}/issues/{issue}/assignees",
                "-f", "assignees[]=copilot-swe-agent")
            api("--method", "POST", f"{root}/issues/{issue}/comments", "-f",
                f"body={MARKER}\nCORRECTION_ATTEMPT:{corrections + 1} "
                f"head_sha:{pr['head']['sha']}\nCorrect only the authorized review findings for PR #{pr_number}.")
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
