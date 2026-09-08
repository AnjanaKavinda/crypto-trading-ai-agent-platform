#!/usr/bin/env python3
"""Execute the durable, fail-closed issue dispatch pipeline via the GitHub API."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import re
from hashlib import sha256
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
TRUSTED_COMPLETION_ACTORS = {"github-actions[bot]"}
COPILOT_ASSIGNEE = "copilot-swe-agent[bot]"
HUMAN_CONTROLLER = "AnjanaKavinda"


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


def hydrate_rulesets(repository: str, rulesets: list[dict] | None = None,
                   *, fetcher: callable | None = None) -> list[dict]:
    """Hydrate ruleset collection summaries before branch matching.

    The repository ruleset list endpoint returns summary objects without detailed
    conditions or rules. Matching against those summaries produces false negatives
    for live branch protections and must therefore be followed by an id-based detail
    fetch per ruleset.
    """
    if fetcher is None:
        fetcher = gh
    listing = rulesets if rulesets is not None else fetcher(f"repos/{repository}/rulesets")
    hydrated: list[dict] = []
    for ruleset in listing:
        ruleset_id = ruleset.get("id")
        if ruleset_id is None:
            continue
        detail = fetcher(f"repos/{repository}/rulesets/{ruleset_id}")
        if isinstance(detail, dict):
            hydrated.append(detail)
    return hydrated


def build_protection_snapshot(rulesets: list[dict], *, repository_settings: dict | None = None) -> dict[str, dict]:
    """Build the required protection evidence from detailed rulesets only."""
    repository_settings = repository_settings or {}
    protection: dict[str, dict] = {}
    for branch in ("dev", "main"):
        ref = f"refs/heads/{branch}"
        matches = [detail for detail in rulesets if ref in detail.get("conditions", {})
                   .get("ref_name", {}).get("include", [])]
        required_checks: list[str] = []
        bypass_actors: list[str] = []
        review_counts: list[int] = []
        missing_rules: list[str] = []
        for detail in matches:
            bypass_actors.extend(str(actor) for actor in detail.get("bypass_actors", []) if str(actor).strip())
            for rule in detail.get("rules", []):
                rule_type = rule.get("type")
                if rule_type == "pull_request":
                   review_counts.append(int(rule.get("parameters", {}).get(
                       "required_approving_review_count", 0)))
                elif rule_type == "required_status_checks":
                   params = rule.get("parameters", {})
                   contexts = params.get("required_status_checks", [])
                   for item in contexts:
                       if isinstance(item, dict):
                           context = item.get("context")
                           if context:
                               required_checks.append(str(context))
                       elif isinstance(item, str) and item.strip():
                           required_checks.append(item)
        for rule_name in ("deletion", "non_fast_forward"):
            if not any(rule.get("type") == rule_name for detail in matches
                      for rule in detail.get("rules", [])):
                missing_rules.append(rule_name)
        protection[branch] = {
            "verified": bool(matches) and all(detail.get("enforcement") == "active" for detail in matches),
            "enforcement": "active" if matches else "missing",
            "required_checks": sorted(dict.fromkeys(required_checks)),
            "required_reviews": max(review_counts or [0]),
            "bypass_actors": sorted(dict.fromkeys(bypass_actors)),
            "auto_merge": bool(repository_settings.get("allow_auto_merge")),
            "merge_queue": any(rule.get("type") == "merge_queue" for detail in matches
                              for rule in detail.get("rules", [])),
            "missing_rules": missing_rules,
        }
    return protection


def completed_assignment_keys(comments: list[dict]) -> set[str]:
    """Return only dispatches with persisted assignment completion evidence."""
    completed: set[str] = set()
    for comment in comments:
        body = comment.get("body", "")
        actor = (comment.get("user") or {}).get("login")
        if (actor not in TRUSTED_COMPLETION_ACTORS or MARKER not in body
                or "ASSIGNMENT_COMPLETED" not in body):
            continue
        marker = "dispatch_key:"
        if marker in body:
            completed.add(body.split(marker, 1)[1].split()[0])
    return completed


def parse_handoff_comments(comments: list[dict], kind: str) -> list[dict]:
    records = []
    for comment in comments:
        body = comment.get("body", "")
        if MARKER not in body or f"{kind} " not in body:
            continue
        actor = (comment.get("user") or {}).get("login")
        if actor != "github-actions[bot]":
            continue
        line = next((item for item in body.splitlines() if item.startswith(f"{kind} ")), "")
        try:
            record = json.loads(line.split(" ", 1)[1])
        except (json.JSONDecodeError, IndexError):
            continue
        record["_comment_id"] = comment.get("id")
        records.append(record)
    return records


def validate_assignment_handoff(issue: dict, comments: list[dict], actor: str,
                                assignees: list[dict]) -> dict:
    """Validate the human-triggered Copilot assignment against one ready handoff."""
    if actor != HUMAN_CONTROLLER:
        raise GovernanceError("assignment confirmation requires the human controller")
    if not any(item.get("login") == COPILOT_ASSIGNEE for item in assignees):
        raise GovernanceError("assignment confirmation is not for Copilot")
    ready = parse_handoff_comments(comments, "DISPATCH_READY")
    if len(ready) != 1:
        raise GovernanceError("assignment handoff is missing or ambiguous")
    record = ready[0]
    required = ("issue_id", "base_branch", "agent", "prompt_hash", "dispatch_key", "prompt")
    if any(not record.get(key) for key in required) or record["issue_id"] != issue["number"]:
        raise GovernanceError("assignment handoff is stale or mismatched")
    if sha256(record["prompt"].encode()).hexdigest() != record["prompt_hash"]:
        raise GovernanceError("assignment handoff prompt hash does not match")
    if record["base_branch"] != "dev":
        raise GovernanceError("assignment handoff is already completed or has an invalid base")
    if record["dispatch_key"] in completed_assignment_keys(comments):
        record["_completed"] = True
    return record


def main() -> int:
    repository = os.environ["GITHUB_REPOSITORY"]
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    issue_id = os.environ.get("ISSUE_NUMBER") or str(event["issue"]["number"])
    root = f"repos/{repository}"
    issue = gh(f"{root}/issues/{issue_id}")
    comments = gh(f"{root}/issues/{issue_id}/comments")
    if event.get("action") == "assigned":
        record = validate_assignment_handoff(
            issue, comments, os.environ.get("GITHUB_ACTOR", ""),
            [event.get("assignee") or {}])
        if record.get("_completed"):
            return 0
        append_governance_event(
            AppendOnlyAudit(), "assignment",
            {"issue_id": int(issue_id), "correlation_id": record["dispatch_key"],
             "agent_role": record["agent"], "capability_tier": "strong-coding-reasoning",
             "routing_reason": "human-supervised assignment confirmation",
             "risk_classification": "governed", "context_pack_id": "handoff",
             "context_pack_version": "v1.1", "controller_policy_version": "v1.1",
             "retry_count": 0, "review_tier": "R1", "outcome": "assigned",
             "timestamp": datetime.now(timezone.utc).isoformat(),
             "commit_sha": os.environ.get("GITHUB_SHA", "unknown")},
            os.environ.get("GOVERNED_AUDIT_PATH", f"/tmp/governed-audit-{issue_id}.jsonl"))
        gh_mutate(f"{root}/issues/{issue_id}/comments", "-f",
                  f"body={MARKER}\nASSIGNMENT_COMPLETED "
                  f"{json.dumps(record, sort_keys=True)}\n"
                  f"dispatch_key:{record['dispatch_key']}")
        for state in ("workflow:ready", "workflow:human-decision-required"):
            if state in [item["name"] for item in issue.get("labels", [])]:
                gh_delete(f"{root}/issues/{issue_id}/labels/{state}")
        gh_mutate(f"{root}/issues/{issue_id}/labels", "-f",
                  "labels[]=workflow:agent-running")
        return 0
    catalog_path = Path(__file__).parents[2] / "docs/copilot-team/04-issues/ISSUE-CATALOG.md"
    catalog_titles = parse_catalog_titles(catalog_path.read_text(encoding="utf-8"))
    catalog_dependencies = parse_catalog_dependencies(catalog_path.read_text(encoding="utf-8"))
    allowed_actors = {item for item in os.environ.get("GOVERNED_DISPATCH_ACTORS", "").split(",") if item}
    if not allowed_actors or os.environ.get("GITHUB_ACTOR") not in allowed_actors:
        raise GovernanceError("dispatch actor is not on the governed allowlist")
    if os.environ.get("GOVERNED_PILOT_ENABLED", "").strip().lower() != "true":
        raise GovernanceError("governed automation is disabled by the global kill switch")
    pilot_issues = {item.strip() for item in os.environ.get(
        "GOVERNED_PILOT_ISSUES", "").split(",") if item.strip()}
    if not pilot_issues:
        raise GovernanceError("governed pilot issue allowlist is empty")
    if "*" not in pilot_issues and str(issue_id) not in pilot_issues:
        raise GovernanceError("issue is not on the governed pilot allowlist")
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
    # The ruleset collection endpoint returns summary objects without the detailed
    # conditions/rules payload needed for branch matching. Hydrate those details
    # before matching refs/heads/dev and refs/heads/main.
    rulesets = gh(f"{root}/rulesets")
    repository_settings = gh(root)
    protection = build_protection_snapshot(
        hydrate_rulesets(repository, rulesets, fetcher=lambda path: gh(path)),
        repository_settings=repository_settings,
    )
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
    active = completed_assignment_keys(comments)
    request = create_dispatch_request(issue_input, eligibility, prompt_hash)
    if not can_dispatch(request["dispatch_key"], active):
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
               "prior_state": "workflow:ready", "new_state": "workflow:human-decision-required",
               "implementer_session_id": os.environ.get("GOVERNED_IMPLEMENTER_SESSION", "")}
    if not payload["implementer_session_id"]:
        raise GovernanceError("implementer session is not configured")
    audit_path = os.environ.get("GOVERNED_AUDIT_PATH", f"/tmp/governed-audit-{issue_id}.jsonl")
    append_governance_event(audit, "dispatch", payload, audit_path)
    gh_mutate(f"{root}/issues/{issue_id}/comments", "-f",
              f"body={MARKER}\nDISPATCH_INTENT {json.dumps(payload, sort_keys=True)}\n"
              f"dispatch_key:{request['dispatch_key']}")
    ready = {**payload, "base_branch": eligibility["base_branch"], "agent": eligibility["agent"],
             "prompt": prompt, "outcome": "awaiting-human-copilot-assignment"}
    gh_mutate(f"{root}/issues/{issue_id}/comments", "-f",
              f"body={MARKER}\nDISPATCH_READY {json.dumps(ready, sort_keys=True)}\n"
              f"dispatch_key:{request['dispatch_key']}\n\n{prompt}\n"
              f"Include `dispatch_key:{request['dispatch_key']}` in the PR body.")
    for state in ("workflow:ready", "workflow:agent-running"):
        if state in labels:
            gh_delete(f"{root}/issues/{issue_id}/labels/{state}")
    gh_mutate(f"{root}/issues/{issue_id}/labels", "-f",
              "labels[]=workflow:human-decision-required")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (GovernanceError, KeyError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        print(f"governed dispatch blocked: {error}", file=sys.stderr)
        raise SystemExit(1)
