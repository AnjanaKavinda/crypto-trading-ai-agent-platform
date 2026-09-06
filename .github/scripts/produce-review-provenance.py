#!/usr/bin/env python3
"""Trusted independent-review producer.

Runs as a separate governed review execution, independent from the
implementing coding-agent session and from the human orchestration
controller, and emits a signed provenance artifact consumed by
``run-pr-governance.py``. This script never grants merge or repository-owner
authority; it only records findings/approval evidence bound to the current
PR head SHA.

Unlike a workflow that accepts ``disposition``/``actual_review_tier``/
``reviewer_identity`` as workflow-dispatch inputs, this producer treats none
of the review outcome as trusted human input. It only signs evidence of a
review that has *already* happened: ``disposition``, ``reviewer_identity``,
``reviewer_session_id`` and the actual ``review_tier`` are all derived by
``review_provenance.resolve_review_evidence`` from an authenticated GitHub
review already submitted, at the PR's current head commit, by a reviewer
present in the trusted reviewer-tier configuration. A human dispatching the
producer workflow supplies only which PR to check; it cannot choose the
disposition, forge a tier, or invent a reviewer identity.

Required input files (verified GitHub API snapshots fetched by the calling
workflow with an authenticated token, mirroring ``run-pr-governance.py``):

    PR.json       ``gh api repos/OWNER/REPO/pulls/{pr}``
    REVIEWS.json  ``gh api --paginate --slurp repos/OWNER/REPO/pulls/{pr}/reviews``
    ISSUE.json    ``gh api repos/OWNER/REPO/issues/{linked_issue}``

Required environment:

    GOVERNANCE_PROVENANCE_SIGNING_KEY  Signing secret (a GitHub Actions
                                       *secret*, never a repository
                                       *variable* or PR-controlled value).
    GITHUB_REPOSITORY                  Platform-provided "owner/repo".
    GITHUB_WORKFLOW_REF                Platform-provided workflow file/ref
                                        identity; becomes ``producer_identity``.
    GITHUB_RUN_ID                      Platform-provided run identity;
                                        becomes ``producer_run_id``.
    GOVERNED_REVIEWER_TIERS            JSON map of authorized reviewer login
                                        -> {"tier": "R1|R2|R3",
                                            "session_id": "..."}.
    GOVERNED_REVIEWER_ROLES            Optional JSON map of reviewer login
                                        -> role label.
    GOVERNED_IMPLEMENTER_SESSION       Implementer session id (must differ
                                        from every configured reviewer
                                        session).
    GOVERNED_CONTROLLER                Controller identity (a controller's
                                        own GitHub review is never treated as
                                        independent AI review).
    GOVERNED_BASE                      Expected PR base branch (default
                                        "dev").
    GOVERNED_AUDIT_LOG                 Optional append-only audit log path
                                        (defaults to /tmp/governance-audit.jsonl).

On success the signed artifact JSON is written to stdout so the caller can
persist it as an immutable producer output (for example a workflow artifact
fetched directly by run identity, or -- only as a pointer/transport -- a
repository variable that contains this verifiable value and never a
free-form trust assertion).
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

from orchestrator import AppendOnlyAudit, GovernanceError
from review_provenance import (build_artifact, record_event,
                                resolve_review_evidence, verify_artifact)


def _require(name: str) -> str:
    value = os.environ.get(name, "")
    if not value.strip():
        raise GovernanceError(f"missing required producer input: {name}")
    return value


def _load_json(path: str) -> object:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: produce-review-provenance.py PR.json REVIEWS.json ISSUE.json",
              file=sys.stderr)
        return 2

    audit = AppendOnlyAudit()
    audit_path = os.environ.get("GOVERNED_AUDIT_LOG") or "/tmp/governance-audit.jsonl"
    correlation_id = str(uuid.uuid4())

    try:
        pr_raw = _load_json(sys.argv[1])
        reviews_raw = _load_json(sys.argv[2])
        issue = _load_json(sys.argv[3])
    except (OSError, json.JSONDecodeError) as error:
        print(f"could not read verified GitHub API snapshots; blocked: {error}",
              file=sys.stderr)
        return 1
    if isinstance(reviews_raw, list) and reviews_raw and isinstance(reviews_raw[0], list):
        reviews_raw = [item for page in reviews_raw for item in page]
    if not isinstance(pr_raw, dict) or not isinstance(issue, dict):
        print("verified GitHub API snapshots are malformed; blocked", file=sys.stderr)
        return 1

    try:
        implementer_session_id = _require("GOVERNED_IMPLEMENTER_SESSION")
        controller = _require("GOVERNED_CONTROLLER")
        # Platform-provided GitHub Actions context, never a repository
        # *variable* or workflow-dispatch input: binds the artifact to
        # which trusted workflow file/ref/run actually produced it.
        producer_identity = _require("GITHUB_WORKFLOW_REF")
        producer_run_id = _require("GITHUB_RUN_ID")
        secret = _require("GOVERNANCE_PROVENANCE_SIGNING_KEY")
        repository = _require("GITHUB_REPOSITORY")
        expected_base = os.environ.get("GOVERNED_BASE") or "dev"
        reviewer_configuration = json.loads(os.environ.get("GOVERNED_REVIEWER_TIERS", "{}"))
        reviewer_roles = json.loads(os.environ.get("GOVERNED_REVIEWER_ROLES", "{}"))
    except (GovernanceError, json.JSONDecodeError) as error:
        print(f"{error}; blocked", file=sys.stderr)
        return 1
    if not isinstance(reviewer_configuration, dict) or not isinstance(reviewer_roles, dict):
        print("trusted reviewer configuration is malformed; blocked", file=sys.stderr)
        return 1

    pr = {
        "head_sha": (pr_raw.get("head") or {}).get("sha"),
        "base": (pr_raw.get("base") or {}).get("ref"),
        "body": pr_raw.get("body"),
    }
    pr_number = pr_raw.get("number")

    try:
        record_event(audit, audit_path, "review-producer-start",
                     correlation_id=correlation_id, repository=repository,
                     pr_number=pr_number, head_sha=pr["head_sha"],
                     producer_identity=producer_identity, producer_run_id=producer_run_id)
    except GovernanceError as error:
        print(f"audit persistence failed; blocked: {error}", file=sys.stderr)
        return 1

    try:
        evidence = resolve_review_evidence(
            pr=pr, issue=issue, reviews=reviews_raw,
            reviewer_configuration=reviewer_configuration,
            implementer_session_id=implementer_session_id, controller=controller,
            expected_base=expected_base)
    except GovernanceError as error:
        try:
            record_event(audit, audit_path, "provenance-rejected",
                         correlation_id=correlation_id, reason=str(error))
        except GovernanceError:
            pass
        print(f"{error}; blocked", file=sys.stderr)
        return 1

    try:
        artifact = build_artifact(
            repository=repository, pr_number=int(pr_number),
            issue_id=evidence["issue_id"], review_id=evidence["review_id"],
            head_sha=evidence["head_sha"], reviewer_identity=evidence["reviewer_identity"],
            reviewer_session_id=evidence["reviewer_session_id"],
            implementer_session_id=implementer_session_id,
            required_review_tier=evidence["required_review_tier"],
            review_tier=evidence["review_tier"], producer_identity=producer_identity,
            producer_run_id=producer_run_id, controller_policy_version="v1.1",
            disposition=evidence["disposition"], secret=secret,
            reviewer_role=reviewer_roles.get(evidence["reviewer_identity"], ""))
    except GovernanceError as error:
        try:
            record_event(audit, audit_path, "provenance-rejected",
                         correlation_id=correlation_id, reason=str(error))
        except GovernanceError:
            pass
        print(f"{error}; blocked", file=sys.stderr)
        return 1

    try:
        record_event(audit, audit_path, "provenance-created",
                     correlation_id=correlation_id, review_id=evidence["review_id"],
                     head_sha=evidence["head_sha"], review_tier=evidence["review_tier"],
                     producer_identity=producer_identity, disposition=evidence["disposition"])
    except GovernanceError as error:
        print(f"audit persistence failed; blocked: {error}", file=sys.stderr)
        return 1

    # Self-verify before publishing so a malformed artifact -- or one whose
    # underlying GitHub review was not actually approved -- is never emitted
    # as trusted producer output.
    try:
        verify_artifact(
            artifact, secret=secret, expected_repository=repository,
            expected_pr_number=int(pr_number), expected_issue_id=evidence["issue_id"],
            expected_head_sha=evidence["head_sha"],
            expected_producer_identity=producer_identity,
            controller=controller, implementer_session_id=implementer_session_id)
    except GovernanceError as error:
        try:
            record_event(audit, audit_path, "provenance-rejected",
                         correlation_id=correlation_id, reason=str(error))
        except GovernanceError:
            pass
        print(f"self-verification failed; blocked: {error}", file=sys.stderr)
        return 1

    try:
        record_event(audit, audit_path, "review-completion",
                     correlation_id=correlation_id, review_id=evidence["review_id"],
                     disposition=evidence["disposition"])
    except GovernanceError as error:
        print(f"audit persistence failed; blocked: {error}", file=sys.stderr)
        return 1

    print(json.dumps(artifact, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
