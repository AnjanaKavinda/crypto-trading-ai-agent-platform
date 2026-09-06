#!/usr/bin/env python3
"""Validate GitHub API snapshots using the trusted base-branch controller."""
import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Mapping

from orchestrator import AppendOnlyAudit, GovernanceError, validate_pr, validate_reviewer_configuration
import review_provenance


def normalize_checks(status: dict, check_runs: dict) -> dict[str, str]:
    checks = {item["context"]: (item.get("state") or "pending").lower()
              for item in status.get("statuses", []) if item.get("context")}
    checks.update({item["name"]: (item.get("conclusion") or "pending").lower()
                   for item in check_runs.get("check_runs", []) if item.get("name")})
    return checks


def verify_reviewer_artifacts(raw_artifacts: object, *, audit: AppendOnlyAudit,
                              audit_path: str, **verify_kwargs) -> dict[tuple, dict]:
    """Verify each candidate provenance artifact and audit the outcome.

    Only an HMAC-signed artifact that verifies against the trusted producer
    signing secret and matches every bound field (repository, PR, issue,
    current head SHA, producer identity, reviewer/implementer/controller
    separation, tier hierarchy, freshness) is trusted. Free-form review
    text, PR/issue comments, and mutable repository variables containing an
    unsigned ``verified``/``true`` assertion are never sufficient and are
    rejected here the same as a fabricated or tampered artifact.
    """
    if isinstance(raw_artifacts, dict):
        candidates = list(raw_artifacts.values())
    elif isinstance(raw_artifacts, list):
        candidates = raw_artifacts
    else:
        raise GovernanceError("trusted reviewer artifacts must be a list or object")
    verified: dict[tuple, dict] = {}
    for candidate in candidates:
        fields = candidate if isinstance(candidate, Mapping) else {}
        correlation_id = str(fields.get("review_id") or fields.get("id") or uuid.uuid4())
        try:
            result = review_provenance.verify_artifact(candidate, **verify_kwargs)
        except review_provenance.StaleProvenanceError as error:
            review_provenance.record_event(audit, audit_path, "provenance-stale",
                                           correlation_id=correlation_id, reason=str(error))
            continue
        except GovernanceError as error:
            review_provenance.record_event(audit, audit_path, "provenance-rejected",
                                           correlation_id=correlation_id, reason=str(error))
            continue
        review_provenance.record_event(
            audit, audit_path, "provenance-validated", correlation_id=correlation_id,
            reviewer=result["user"], head_sha=result["commit_id"],
            review_tier=result["review_tier"])
        verified[(result["user"], result["commit_id"])] = result
    return verified


def build_governed_reviews(reviews: list[dict], reviewer_roles: dict,
                           reviewer_configuration: dict,
                           verified_artifacts: dict[tuple, dict]) -> list[dict]:
    """Normalize reviews, trusting independence only for a verified artifact.

    A review is marked independent only when a signed, verified producer
    artifact exists for the exact same reviewer login and current commit
    SHA. Anything else (including any unsigned or unverifiable artifact)
    remains ``independent: False`` and cannot satisfy governance.
    """
    governed = []
    for item in reviews:
        login = item.get("user", {}).get("login")
        commit_id = item.get("commit_id")
        verified = verified_artifacts.get((login, commit_id))
        governed.append({
            "state": item.get("state"), "commit_id": commit_id,
            "user": login, "independent": bool(verified),
            "submitted_at": item.get("submitted_at"), "id": item.get("id"),
            "role": (verified or {}).get("role") or reviewer_roles.get(login),
            "review_tier": (verified or {}).get("review_tier")
                           or reviewer_configuration.get(login, {}).get("tier"),
            "reviewer_session_id": (verified or {}).get("reviewer_session_id", ""),
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
    repository_full_name = pr.get("base", {}).get("repo", {}).get("full_name") or os.environ.get(
        "GITHUB_REPOSITORY", "")
    pr_number = pr.get("number")
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
            os.environ.get("GOVERNED_REVIEW_ARTIFACTS", "[]"))
    except json.JSONDecodeError as error:
        print(f"malformed trusted reviewer artifacts; blocked: {error}", file=sys.stderr)
        return 1
    pr["checks"] = normalize_checks(status, check_runs)
    pr["governed_high_risk"] = any(label.get("name") == "risk:high"
                                    for label in issue.get("labels", []))
    pr["required_review_tier"] = review_provenance.required_review_tier_from_labels(
        issue.get("labels", []))
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
    producer_identity = os.environ.get("GOVERNED_PROVENANCE_PRODUCER", "")
    signing_secret = os.environ.get("GOVERNANCE_PROVENANCE_SIGNING_KEY", "")
    audit_path = os.environ.get("GOVERNED_AUDIT_LOG") or "/tmp/governance-audit.jsonl"
    audit = AppendOnlyAudit()
    if not producer_identity or not signing_secret:
        if reviewer_artifacts:
            print("missing trusted independent-review producer configuration; blocked",
                  file=sys.stderr)
            return 1
        verified_artifacts: dict[tuple, dict] = {}
    else:
        try:
            verified_artifacts = verify_reviewer_artifacts(
                reviewer_artifacts, audit=audit, audit_path=audit_path,
                secret=signing_secret, expected_repository=repository_full_name,
                expected_pr_number=pr_number, expected_issue_id=pr["issue_id"],
                expected_head_sha=pr["head_sha"],
                expected_producer_identity=producer_identity, controller=controller,
                implementer_session_id=pr["implementer_session_id"])
        except GovernanceError as error:
            print(f"{error}; blocked", file=sys.stderr)
            return 1
    reviews = build_governed_reviews(
        reviews, reviewer_roles, reviewer_configuration, verified_artifacts)
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
        try:
            review_provenance.record_event(
                audit, audit_path, "review-disposition", correlation_id=str(pr["issue_id"]),
                head_sha=pr["head_sha"], outcome="blocked", reason=str(error))
        except GovernanceError as audit_error:
            print(f"audit persistence failed; blocked: {audit_error}", file=sys.stderr)
        return 1
    try:
        review_provenance.record_event(
            audit, audit_path, "review-disposition", correlation_id=str(pr["issue_id"]),
            head_sha=pr["head_sha"], outcome="approved")
    except GovernanceError as error:
        print(f"audit persistence failed; blocked: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
