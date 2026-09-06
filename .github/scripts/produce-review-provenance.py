#!/usr/bin/env python3
"""Trusted independent-review producer.

Runs as a separate governed review execution, independent from the
implementing coding-agent session and from the human orchestration
controller, and emits a signed provenance artifact consumed by
``run-pr-governance.py``. This script never grants merge or repository-owner
authority; it only records findings/approval evidence bound to the current
PR head SHA.

Required environment:

    GOVERNANCE_PROVENANCE_SIGNING_KEY  Signing secret (a GitHub Actions
                                       *secret*, never a repository
                                       *variable* or PR-controlled value).
    GOVERNED_REPOSITORY                 "owner/repo"
    GOVERNED_PR_NUMBER
    GOVERNED_ISSUE_ID
    GOVERNED_HEAD_SHA                   Current PR head SHA under review.
    GOVERNED_REVIEW_ID                  Immutable review artifact/session id.
    GOVERNED_REVIEWER_IDENTITY          Independent reviewer identity.
    GOVERNED_REVIEWER_SESSION_ID        Independent reviewer session id.
    GOVERNED_IMPLEMENTER_SESSION        Implementer session id (must differ).
    GOVERNED_REQUIRED_REVIEW_TIER       R1 | R2 | R3
    GOVERNED_ACTUAL_REVIEW_TIER         R1 | R2 | R3 (tier actually performed)
    GOVERNED_PRODUCER_IDENTITY          Identity of this trusted producer.
    GOVERNED_CONTROLLER                 Controller identity (must differ from
                                         the reviewer identity/session).
    GOVERNED_REVIEW_DISPOSITION         approved | changes-requested
    GOVERNED_REVIEWER_ROLE              Optional reviewer role label.
    GOVERNED_AUDIT_LOG                  Optional append-only audit log path
                                         (defaults to /tmp/governance-audit.jsonl).

On success the signed artifact JSON is written to stdout so the caller can
persist it as an immutable producer output (for example a workflow artifact
or a pointer variable that contains only this verifiable value, never a
free-form trust assertion).
"""
from __future__ import annotations

import json
import os
import sys
import uuid

from orchestrator import AppendOnlyAudit, GovernanceError
from review_provenance import build_artifact, record_event, verify_artifact


def _require(name: str) -> str:
    value = os.environ.get(name, "")
    if not value.strip():
        raise GovernanceError(f"missing required producer input: {name}")
    return value


def main() -> int:
    audit = AppendOnlyAudit()
    audit_path = os.environ.get("GOVERNED_AUDIT_LOG") or "/tmp/governance-audit.jsonl"
    correlation_id = os.environ.get("GOVERNED_REVIEW_ID") or str(uuid.uuid4())
    try:
        repository = _require("GOVERNED_REPOSITORY")
        pr_number = int(_require("GOVERNED_PR_NUMBER"))
        issue_id = int(_require("GOVERNED_ISSUE_ID"))
        head_sha = _require("GOVERNED_HEAD_SHA")
        review_id = _require("GOVERNED_REVIEW_ID")
        reviewer_identity = _require("GOVERNED_REVIEWER_IDENTITY")
        reviewer_session_id = _require("GOVERNED_REVIEWER_SESSION_ID")
        implementer_session_id = _require("GOVERNED_IMPLEMENTER_SESSION")
        required_review_tier = _require("GOVERNED_REQUIRED_REVIEW_TIER")
        review_tier = _require("GOVERNED_ACTUAL_REVIEW_TIER")
        producer_identity = _require("GOVERNED_PRODUCER_IDENTITY")
        controller = _require("GOVERNED_CONTROLLER")
        disposition = _require("GOVERNED_REVIEW_DISPOSITION")
        reviewer_role = os.environ.get("GOVERNED_REVIEWER_ROLE", "")
        secret = _require("GOVERNANCE_PROVENANCE_SIGNING_KEY")
    except GovernanceError as error:
        print(f"{error}; blocked", file=sys.stderr)
        return 1

    try:
        record_event(audit, audit_path, "review-producer-start",
                     correlation_id=correlation_id, repository=repository,
                     pr_number=pr_number, issue_id=issue_id, head_sha=head_sha,
                     reviewer_identity=reviewer_identity,
                     reviewer_session_id=reviewer_session_id,
                     required_review_tier=required_review_tier)
    except GovernanceError as error:
        print(f"audit persistence failed; blocked: {error}", file=sys.stderr)
        return 1

    if reviewer_identity == controller or reviewer_session_id == implementer_session_id:
        try:
            record_event(audit, audit_path, "provenance-rejected",
                         correlation_id=correlation_id,
                         reason="reviewer is not independent from controller/implementer")
        except GovernanceError:
            pass
        print("reviewer must be independent from the controller and implementer; blocked",
              file=sys.stderr)
        return 1

    try:
        artifact = build_artifact(
            repository=repository, pr_number=pr_number, issue_id=issue_id,
            review_id=review_id, head_sha=head_sha,
            reviewer_identity=reviewer_identity,
            reviewer_session_id=reviewer_session_id,
            implementer_session_id=implementer_session_id,
            required_review_tier=required_review_tier, review_tier=review_tier,
            producer_identity=producer_identity,
            controller_policy_version="v1.1", disposition=disposition,
            secret=secret, reviewer_role=reviewer_role)
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
                     correlation_id=correlation_id, review_id=review_id,
                     head_sha=head_sha, review_tier=review_tier,
                     producer_identity=producer_identity, disposition=disposition)
    except GovernanceError as error:
        print(f"audit persistence failed; blocked: {error}", file=sys.stderr)
        return 1

    # Self-verify before publishing so a malformed artifact is never emitted
    # as trusted producer output.
    try:
        verify_artifact(
            artifact, secret=secret, expected_repository=repository,
            expected_pr_number=pr_number, expected_issue_id=issue_id,
            expected_head_sha=head_sha, expected_producer_identity=producer_identity,
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
                     correlation_id=correlation_id, review_id=review_id,
                     disposition=disposition)
    except GovernanceError as error:
        print(f"audit persistence failed; blocked: {error}", file=sys.stderr)
        return 1

    print(json.dumps(artifact, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
