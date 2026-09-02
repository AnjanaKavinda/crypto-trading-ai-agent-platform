#!/usr/bin/env python3
"""Execute the durable, fail-closed issue dispatch pipeline via the GitHub API."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import re
from hashlib import sha256
from pathlib import Path

from orchestrator import (
    AppendOnlyAudit, GovernanceError, build_launch_prompt, can_dispatch,
    create_dispatch_request, validate_issue, verify_protections,
)

MARKER = "<!-- governed-copilot-orchestrator:v1 -->"


def gh(*args: str) -> object:
    result = subprocess.run(["gh", "api", *args], check=True, text=True,
                            capture_output=True)
    return json.loads(result.stdout or "null")


def gh_mutate(*args: str) -> object:
    return gh("--method", "POST", *args)


def gh_delete(*args: str) -> object:
    return gh("--method", "DELETE", *args)


def main() -> int:
    repository = os.environ["GITHUB_REPOSITORY"]
    issue_id = os.environ.get("ISSUE_NUMBER") or str(json.loads(
        Path(os.environ["GITHUB_EVENT_PATH"]).read_text())["issue"]["number"])
    root = f"repos/{repository}"
    issue = gh(f"{root}/issues/{issue_id}")
    allowed_actors = {item for item in os.environ.get("GOVERNED_DISPATCH_ACTORS", "").split(",") if item}
    if not allowed_actors or os.environ.get("GITHUB_ACTOR") not in allowed_actors:
        raise GovernanceError("dispatch actor is not on the governed allowlist")
    labels = [item["name"] for item in issue.get("labels", [])]
    body = issue.get("body") or ""
    dependency_text = os.environ.get("DEPENDENCIES", "")
    match = re.search(r"(?im)^\s*dependencies\s*:\s*([^\n]+)", issue.get("body") or "")
    dependency_text = dependency_text or (match.group(1) if match else "")
    dependencies = [int(value) for value in re.findall(r"\b\d{1,3}\b", dependency_text)]
    ownership = [label.split(":", 1)[1] for label in labels if label.startswith("ownership:")]
    open_issues = gh(f"{root}/issues?state=open&per_page=100")
    active_issues = [{"state": item.get("state"),
                      "owned": [label["name"].split(":", 1)[1] for label in item.get(
                          "labels", []) if label["name"].startswith("ownership:")]}
                     for item in open_issues if item.get("number") != int(issue_id)]
    issue_input = {
        "id": int(issue_id), "state": issue["state"], "labels": labels, "body": body,
        "title": issue.get("title", ""), "dependencies": dependencies,
        "active_issues": active_issues, "owned": ownership, "base_branch": None,
    }
    # Repository rulesets are the durable protection source; absence is unsafe.
    rulesets = gh(f"{root}/rulesets")
    repository_settings = gh(root)
    protection = {}
    for branch in ("dev", "main"):
        matches = [item for item in rulesets
                   if f"refs/heads/{branch}" in item.get("conditions", {}).get(
                       "ref_name", {}).get("include", [])]
        details = [gh(f"{root}/rulesets/{item['id']}") for item in matches if item.get("id")]
        pull_rules = [rule for detail in details for rule in detail.get("rules", [])
                      if rule.get("type") == "pull_request"]
        check_rules = [rule for detail in details for rule in detail.get("rules", [])
                       if rule.get("type") == "required_status_checks"]
        required_checks = [context for rule in check_rules
                           for context in rule.get("parameters", {}).get("required_status_checks", [])]
        protection[branch] = {
            "verified": bool(matches) and all(item.get("enforcement") == "active" for item in matches),
            "enforcement": "active",
            "required_checks": [item.get("context") for item in required_checks
                                if item.get("context")],
            "required_reviews": max([rule.get("parameters", {}).get(
                "required_approving_review_count", 0) for rule in pull_rules] or [0]),
            "bypass_actors": [actor for detail in details for actor in detail.get("bypass_actors", [])],
            "auto_merge": bool(repository_settings.get("allow_auto_merge")),
            "merge_queue": any(rule.get("type") == "merge_queue" for detail in details
                               for rule in detail.get("rules", [])),
        }
    verify_protections(protection)
    dependency_status = {}
    for number in dependencies:
        dependency_issue = gh(f"{root}/issues/{number}")
        dependency_status[number] = "closed" if dependency_issue.get("state") == "closed" else "open"
    eligibility = validate_issue(issue_input, dependency_status=dependency_status)
    prompt, prompt_hash = build_launch_prompt(
        {**issue_input, "canonical_backlog": eligibility["canonical_backlog"]},
        eligibility["agent"], ["AGENTS.md", ".github/copilot-instructions.md",
                               "docs/adr/ADR-0001-governed-copilot-development-orchestration.md"],
    )
    comments = gh(f"{root}/issues/{issue_id}/comments")
    active = [comment for comment in comments if MARKER in comment.get("body", "")
              and "DISPATCH" in comment.get("body", "")
              and "dispatch_key:" in comment.get("body", "")]
    request = create_dispatch_request(issue_input, eligibility, prompt_hash)
    if not can_dispatch(request["dispatch_key"], [comment["body"].split("dispatch_key:", 1)[1].split()[0]
                                                  for comment in active]):
        if "workflow:agent-running" not in labels:
            if "workflow:ready" in labels:
                gh_delete(f"{root}/issues/{issue_id}/labels/workflow:ready")
            gh_mutate(f"{root}/issues/{issue_id}/labels", "-f",
                      "labels[]=workflow:agent-running")
        return 0
    audit = AppendOnlyAudit()
    payload = {"correlation_id": request["dispatch_key"], "issue_id": int(issue_id),
               "canonical_backlog": eligibility["canonical_backlog"], "agent": eligibility["agent"],
               "prompt_hash": prompt_hash, "controller_version": "v1",
               "prior_state": "workflow:ready", "new_state": "workflow:agent-running"}
    audit.append("dispatch", payload)
    gh_mutate(f"{root}/issues/{issue_id}/comments", "-f",
              f"body={MARKER}\nAUDIT {json.dumps(payload, sort_keys=True)}\n"
              f"dispatch_key:{request['dispatch_key']}")
    # The Copilot coding-agent assignment endpoint is the supported dispatch boundary.
    gh_mutate(f"{root}/issues/{issue_id}/assignees", "-f", "assignees[]=copilot-swe-agent")
    gh_mutate(f"{root}/issues/{issue_id}/comments", "-f",
              f"body={MARKER}\nDISPATCH {json.dumps(payload, sort_keys=True)}\n"
              f"dispatch_key:{request['dispatch_key']}\n\n{prompt}\n"
              f"Include `dispatch_key:{request['dispatch_key']}` in the PR body.")
    for state in ("workflow:ready", "workflow:agent-running", "workflow:review",
                  "workflow:changes-requested", "workflow:ready-to-merge",
                  "workflow:blocked", "workflow:human-decision-required",
                  "workflow:complete"):
        if state in labels and state != "workflow:agent-running":
            gh_delete(f"{root}/issues/{issue_id}/labels/{state}")
    gh_mutate(f"{root}/issues/{issue_id}/labels", "-f",
              "labels[]=workflow:agent-running")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (GovernanceError, KeyError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        print(f"governed dispatch blocked: {error}", file=sys.stderr)
        raise SystemExit(1)
