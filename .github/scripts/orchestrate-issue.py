#!/usr/bin/env python3
"""Execute the durable, fail-closed issue dispatch pipeline via the GitHub API."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import re
from datetime import datetime, timezone
from pathlib import Path

from orchestrator import (
    AppendOnlyAudit, GovernanceError, build_launch_prompt, can_dispatch,
    build_canonical_mapping, parse_catalog_dependencies, parse_catalog_titles,
    create_dispatch_request, parse_dependencies, resolve_canonical_number,
    resolve_dependency_github_numbers, validate_issue, verify_protections,
    extract_routing_inputs, select_capability_tier, required_review_tier,
    build_context_pack, append_governance_event, transition_escalation,
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


def gh_paginated(path: str) -> list[dict]:
    result = subprocess.run(["gh", "api", "--paginate", "--slurp", path],
                            check=True, text=True, capture_output=True)
    pages = json.loads(result.stdout or "[]")
    return [item for page in pages for item in page]


def assign_copilot(repository: str, issue_id: str, prompt: str, agent: str,
                   base_branch: str = "dev") -> object:
    """Use GitHub's full Copilot coding-agent assignment request."""
    payload = json.dumps({
        "assignees": ["copilot-swe-agent[bot]"],
        "agent_assignment": {
            "target_repo": repository,
            "base_branch": base_branch,
            "custom_instructions": prompt,
            "custom_agent": agent,
        },
    })
    result = subprocess.run(
        ["gh", "api", "--method", "POST", f"repos/{repository}/issues/{issue_id}/assignees",
         "--input", "-"], input=payload, check=True, text=True, capture_output=True)
    return json.loads(result.stdout or "null")


def main() -> int:
    repository = os.environ["GITHUB_REPOSITORY"]
    issue_id = os.environ.get("ISSUE_NUMBER") or str(json.loads(
        Path(os.environ["GITHUB_EVENT_PATH"]).read_text())["issue"]["number"])
    root = f"repos/{repository}"
    issue = gh(f"{root}/issues/{issue_id}")
    catalog_path = Path(__file__).parents[2] / "docs/copilot-team/04-issues/ISSUE-CATALOG.md"
    catalog_titles = parse_catalog_titles(catalog_path.read_text(encoding="utf-8"))
    catalog_dependencies = parse_catalog_dependencies(catalog_path.read_text(encoding="utf-8"))
    allowed_actors = {item for item in os.environ.get("GOVERNED_DISPATCH_ACTORS", "").split(",") if item}
    if not allowed_actors or os.environ.get("GITHUB_ACTOR") not in allowed_actors:
        raise GovernanceError("dispatch actor is not on the governed allowlist")
    labels = [item["name"] for item in issue.get("labels", [])]
    body = issue.get("body") or ""
    current_canonical, _ = resolve_canonical_number(issue.get("body") or "")
    body_dependencies = parse_dependencies(issue.get("body") or "")
    expected_dependencies = catalog_dependencies.get(current_canonical)
    if expected_dependencies is None or (
            body_dependencies and body_dependencies != expected_dependencies):
        raise GovernanceError("issue dependencies do not match approved catalog")
    dependencies = expected_dependencies
    ownership = [label.split(":", 1)[1] for label in labels if label.startswith("ownership:")]
    open_issues = gh_paginated(f"{root}/issues?state=all&per_page=100")
    canonical_to_github = build_canonical_mapping(open_issues, catalog_titles)
    if canonical_to_github.get(4) != 6:
        raise GovernanceError("canonical Issue 004 mapping must resolve to GitHub issue #6")
    if issue.get("title", "").strip() != catalog_titles.get(current_canonical):
        raise GovernanceError("issue title does not match approved canonical catalog")
    if current_canonical == 4 and int(issue_id) != 6:
        raise GovernanceError("canonical Issue 004 is reserved for GitHub issue #6")
    if current_canonical == 4 and os.environ.get("GOVERNED_PILOT_ENABLED") != "true":
        raise GovernanceError("canonical Issue 004 pilot requires explicit human activation")
    dependency_github_numbers = resolve_dependency_github_numbers(
        dependencies, canonical_to_github)
    active_issues = [{"state": item.get("state"),
                      "owned": [label["name"].split(":", 1)[1] for label in item.get(
                          "labels", []) if label["name"].startswith("ownership:")]}
                     for item in open_issues if item.get("number") != int(issue_id)]
    issue_input = {
        "id": int(issue_id), "state": issue["state"], "labels": labels, "body": body,
        "title": issue.get("title", ""), "dependencies": dependencies,
        "active_issues": active_issues, "owned": ownership, "base_branch": None,
    }
    # V1.1 routing metadata is an explicit dispatch prerequisite; never infer it
    # from free-form issue prose.
    routing_inputs = extract_routing_inputs(issue, catalog_titles=catalog_titles)
    capability_tier = select_capability_tier(routing_inputs)
    review_tier = required_review_tier(routing_inputs)
    escalation_tier = transition_escalation(capability_tier, retries=0)
    context_pack = build_context_pack(
        routing_inputs,
        issue_metadata={"issue_id": int(issue_id), "github_title": issue.get("title", ""),
                        "dependencies": dependencies, "base_branch": "dev",
                        "controller_version": "v1.1"},
        references=["AGENTS.md", ".github/copilot-instructions.md",
                    "docs/adr/ADR-0001-governed-copilot-development-orchestration.md",
                    "docs/copilot-team/03-github-workflow/MODEL-ROUTING-GOVERNANCE-V1.1.md"],
        excerpts=[body],
    )
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
            "missing_rules": [rule for rule in ("deletion", "non_fast_forward")
                              if not any(item.get("type") == rule for detail in details
                                         for item in detail.get("rules", []))],
        }
    verify_protections(protection)
    dependency_status = {}
    for canonical, number in zip(dependencies, dependency_github_numbers):
        dependency_issue = gh(f"{root}/issues/{number}")
        dependency_status[canonical] = "closed" if dependency_issue.get("state") == "closed" else "open"
    eligibility = validate_issue(issue_input, dependency_status=dependency_status)
    eligibility.update({"routing_inputs": routing_inputs, "capability_tier": escalation_tier,
                        "review_tier": review_tier, "context_pack": context_pack})
    prompt, prompt_hash = build_launch_prompt(
        {**issue_input, "canonical_backlog": eligibility["canonical_backlog"]},
        eligibility["agent"], ["AGENTS.md", ".github/copilot-instructions.md",
                               "docs/adr/ADR-0001-governed-copilot-development-orchestration.md"],
        context_pack=context_pack,
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
               "agent_role": eligibility["agent"], "capability_tier": capability_tier,
               "routing_reason": "deterministic V1.1 decision table",
               "risk_classification": routing_inputs.risk_label,
               "context_pack_id": context_pack.context_pack_id,
               "context_pack_version": context_pack.version,
               "controller_policy_version": "v1.1", "retry_count": 0,
               "escalation_count": 0, "review_tier": review_tier,
               "reviewer_role": "independent-ai-reviewer", "outcome": "dispatch-intended",
               "timestamp": datetime.now(timezone.utc).isoformat(),
               "commit_sha": os.environ.get("GITHUB_SHA", "unknown"),
               "prompt_hash": prompt_hash, "controller_version": "v1.1",
               "prior_state": "workflow:ready", "new_state": "workflow:agent-running",
               "implementer_session_id": os.environ.get("GOVERNED_IMPLEMENTER_SESSION", "")}
    if not payload["implementer_session_id"]:
        raise GovernanceError("implementer session is not configured")
    audit_path = os.environ.get("GOVERNED_AUDIT_PATH", f"/tmp/governed-audit-{issue_id}.jsonl")
    append_governance_event(audit, "dispatch", payload, audit_path)
    gh_mutate(f"{root}/issues/{issue_id}/comments", "-f",
              f"body={MARKER}\nDISPATCH_INTENT {json.dumps(payload, sort_keys=True)}\n"
              f"dispatch_key:{request['dispatch_key']}")
    # The Copilot coding-agent assignment endpoint is the supported dispatch boundary.
    assign_copilot(repository, issue_id, prompt, eligibility["agent"],
                   eligibility["base_branch"])
    append_governance_event(
        audit, "assignment",
        {**payload, "outcome": "assigned"},
        audit_path,
    )
    gh_mutate(f"{root}/issues/{issue_id}/comments", "-f",
              f"body={MARKER}\nASSIGNMENT_COMPLETED {json.dumps({**payload, 'outcome': 'assigned'}, sort_keys=True)}\n"
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
