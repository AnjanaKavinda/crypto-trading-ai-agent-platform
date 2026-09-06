#!/usr/bin/env python3
"""Validate GitHub API snapshots using the trusted base-branch controller."""
import json
import os
import re
import sys
from pathlib import Path

from orchestrator import GovernanceError, validate_pr, validate_reviewer_configuration


def normalize_checks(status: dict, check_runs: dict) -> dict[str, str]:
    checks = {item["context"]: (item.get("state") or "pending").lower()
              for item in status.get("statuses", []) if item.get("context")}
    checks.update({item["name"]: (item.get("conclusion") or "pending").lower()
                   for item in check_runs.get("check_runs", []) if item.get("name")})
    return checks


def build_governed_reviews(reviews: list[dict], reviewer_roles: dict,
                           reviewer_configuration: dict,
                           artifacts: dict) -> list[dict]:
    """Bind approval evidence to trusted workflow artifacts, never review text."""
    governed = []
    for item in reviews:
        login = item.get("user", {}).get("login")
        artifact = artifacts.get(str(item.get("id")), {})
        artifact_matches = (
            artifact.get("verified") is True
            and artifact.get("reviewer") == login
            and artifact.get("head_sha") == item.get("commit_id")
            and isinstance(artifact.get("session_id"), str)
            and bool(artifact["session_id"].strip())
        )
        governed.append({
            "state": item.get("state"), "commit_id": item.get("commit_id"),
            "user": login, "independent": artifact_matches,
            "submitted_at": item.get("submitted_at"), "id": item.get("id"),
            "role": reviewer_roles.get(login),
            "review_tier": reviewer_configuration.get(login, {}).get("tier"),
            "reviewer_session_id": artifact.get("session_id", "") if artifact_matches else "",
        })
    return governed


def main() -> int:
    if len(sys.argv) != 6:
        print("usage: run-pr-governance.py PR.json REVIEWS.json STATUS.json CHECKS.json ISSUE.json", file=sys.stderr)
        return 2
    pr = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    reviews = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    status = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
    check_runs = json.loads(Path(sys.argv[4]).read_text(encoding="utf-8"))
    issue = json.loads(Path(sys.argv[5]).read_text(encoding="utf-8"))
    if isinstance(reviews, list) and reviews and isinstance(reviews[0], list):
        reviews = [item for page in reviews for item in page]
    if isinstance(check_runs, list):
        check_runs = {"check_runs": [run for page in check_runs
                                     for run in page.get("check_runs", [])]}
    pr = {"issue_id": None, "base": pr.get("base", {}).get("ref"),
          "head_sha": pr.get("head", {}).get("sha"),
          "author": pr.get("user", {}).get("login"), "body": pr.get("body")}
    try:
        reviewer_roles = json.loads(os.environ.get("GOVERNED_REVIEWER_ROLES", "{}"))
        reviewer_configuration = json.loads(
            os.environ.get("GOVERNED_REVIEWER_TIERS", "{}"))
    except json.JSONDecodeError as error:
        print(f"malformed trusted reviewer configuration; blocked: {error}", file=sys.stderr)
        return 1
    try:
        reviewer_artifacts = json.loads(
            os.environ.get("GOVERNED_REVIEW_ARTIFACTS", "{}"))
    except json.JSONDecodeError as error:
        print(f"malformed trusted reviewer artifacts; blocked: {error}", file=sys.stderr)
        return 1
    if not isinstance(reviewer_artifacts, dict):
        print("trusted reviewer artifacts must be an object; blocked", file=sys.stderr)
        return 1
    reviews = build_governed_reviews(
        reviews, reviewer_roles, reviewer_configuration, reviewer_artifacts)
    pr["checks"] = normalize_checks(status, check_runs)
    pr["governed_high_risk"] = any(label.get("name") == "risk:high"
                                    for label in issue.get("labels", []))
    labels = {label.get("name") for label in issue.get("labels", [])}
    pr["required_review_tier"] = (
        "R3" if labels & {"risk:high", "risk:critical", "type:architecture",
                          "type:contract", "type:security", "impact:architecture",
                          "impact:shared-contract", "impact:security",
                          "impact:trading-risk", "impact:approval-execution-ccxt"}
        else "R1" if labels & {"risk:low", "type:docs", "type:test"}
        else "R2"
    )
    issue_match = re.search(r"(?im)\b(?:closes|fixes|resolves)\s+#(\d+)", pr.get("body") or "")
    issue_id = os.environ.get("GOVERNED_ISSUE_ID") or (issue_match.group(1) if issue_match else "")
    if not issue_id:
        print("PR has no recorded linked issue; blocked", file=sys.stderr)
        return 1
    pr["issue_id"] = int(issue_id)
    pr["authorized_reviewers"] = [name for name in
                                  os.environ.get("GOVERNED_REVIEWERS", "").split(",") if name]
    try:
        configured_reviewers, configured_sessions = validate_reviewer_configuration(
            reviewer_configuration, pr["required_review_tier"])
    except GovernanceError as error:
        print(f"missing trusted reviewer-tier configuration; blocked: {error}", file=sys.stderr)
        return 1
    if set(pr["authorized_reviewers"]) != set(configured_reviewers):
        print("reviewer allowlist and reviewer-tier configuration disagree; blocked",
              file=sys.stderr)
        return 1
    pr["authorized_reviewer_sessions"] = configured_sessions
    pr["implementer_session_id"] = os.environ.get("GOVERNED_IMPLEMENTER_SESSION", "")
    if not pr["implementer_session_id"]:
        print("missing trusted implementer session configuration; blocked", file=sys.stderr)
        return 1
    required = [name for name in os.environ.get("REQUIRED_CHECKS", "").split(",") if name]
    required_roles = [role for role in os.environ.get(
        "REQUIRED_REVIEWER_ROLES", "").split(",") if role]
    controller = os.environ.get("GOVERNED_CONTROLLER")
    if not required or not pr["authorized_reviewers"] or not controller or (
            pr["governed_high_risk"] and not required_roles):
        print("missing trusted reviewer/check configuration; blocked", file=sys.stderr)
        return 1
    try:
        validate_pr(pr, issue_id=pr["issue_id"],
                    expected_base=os.environ.get("GOVERNED_BASE", "dev"),
                    required_checks=required, reviews=reviews,
                    controller=controller,
                    high_risk_text=pr.get("body") or "",
                    required_reviewer_roles=required_roles,
                    governed_high_risk=pr["governed_high_risk"])
    except (GovernanceError, KeyError, ValueError) as error:
        print(f"governance blocked: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
