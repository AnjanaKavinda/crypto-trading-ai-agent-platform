"""Trusted independent-review producer artifact and provenance verifier.

Implements the Model Routing & AI Usage Governance V1.1 "Implementation
handoff" prerequisite (see
``docs/copilot-team/03-github-workflow/MODEL-ROUTING-GOVERNANCE-V1.1.md``,
section 7): a separately approved producer that emits evidence bound to the
review ID, current PR head SHA, reviewer identity, reviewer session,
implementer session, review tier, and producer identity.

Trust model
-----------
The only trust anchor recognised by :func:`verify_artifact` is an
HMAC-SHA256 integrity signature computed over the canonical artifact
payload using a signing secret that is available only to the trusted
producer execution (a GitHub Actions *secret*, never a PR-controlled
value, repository *variable*, issue/PR comment, or free-form review
text). A mutable repository variable containing ``verified: true`` (or
any other unsigned assertion) is therefore never sufficient on its own;
a value only becomes trusted once it verifies against the signing
secret and every bound field matches the current PR state.

This module intentionally contains no GitHub client, merge capability, or
repository-owner/controller authority. It only builds and verifies
evidence; final merge authority always remains with the human repository
owner.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any, Mapping

from orchestrator import AppendOnlyAudit, GovernanceError, REVIEW_TIERS

PROVENANCE_SCHEMA_VERSION = "1.1"

# Fields bound into the signed payload. Order is irrelevant (the payload is
# serialized with sorted keys) but every field listed here is mandatory.
REQUIRED_FIELDS = (
    "schema_version",
    "repository",
    "pr_number",
    "issue_id",
    "review_id",
    "head_sha",
    "reviewer_identity",
    "reviewer_session_id",
    "implementer_session_id",
    "required_review_tier",
    "review_tier",
    "producer_identity",
    "controller_policy_version",
    "timestamp",
    "disposition",
)

DISPOSITIONS = ("approved", "changes-requested")


def _canonical_payload(artifact: Mapping[str, Any]) -> bytes:
    import json

    body = {key: artifact[key] for key in REQUIRED_FIELDS if key in artifact}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_artifact(artifact: Mapping[str, Any], secret: str) -> str:
    """Compute the integrity signature for a (not yet signed) artifact body."""
    if not secret or not isinstance(secret, str):
        raise GovernanceError("provenance signing secret is unavailable")
    return hmac.new(secret.encode("utf-8"), _canonical_payload(artifact),
                     hashlib.sha256).hexdigest()


def build_artifact(*, repository: str, pr_number: int, issue_id: int, review_id: Any,
                    head_sha: str, reviewer_identity: str, reviewer_session_id: str,
                    implementer_session_id: str, required_review_tier: str,
                    review_tier: str, producer_identity: str,
                    controller_policy_version: str, disposition: str, secret: str,
                    reviewer_role: str = "", timestamp: float | None = None) -> dict:
    """Build and sign a provenance artifact for a completed independent review.

    Raises ``GovernanceError`` rather than producing an artifact that would
    fail verification (for example when the reviewer session collides with
    the implementer session).
    """
    if not all(isinstance(value, str) and value.strip() for value in
               (repository, head_sha, reviewer_identity, reviewer_session_id,
                implementer_session_id, producer_identity, controller_policy_version)):
        raise GovernanceError("provenance artifact fields are incomplete")
    if reviewer_session_id == implementer_session_id:
        raise GovernanceError(
            "reviewer session must be independent from the implementer session")
    if review_tier not in REVIEW_TIERS or required_review_tier not in REVIEW_TIERS:
        raise GovernanceError("provenance artifact review tier is invalid")
    if disposition not in DISPOSITIONS:
        raise GovernanceError("provenance artifact disposition is invalid")
    artifact = {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "repository": repository,
        "pr_number": int(pr_number),
        "issue_id": int(issue_id),
        "review_id": review_id,
        "head_sha": head_sha,
        "reviewer_identity": reviewer_identity,
        "reviewer_session_id": reviewer_session_id,
        "implementer_session_id": implementer_session_id,
        "required_review_tier": required_review_tier,
        "review_tier": review_tier,
        "producer_identity": producer_identity,
        "controller_policy_version": controller_policy_version,
        "timestamp": float(timestamp) if timestamp is not None else time.time(),
        "disposition": disposition,
        "reviewer_role": reviewer_role,
    }
    artifact["integrity_signature"] = sign_artifact(artifact, secret)
    return artifact


def verify_artifact(artifact: Any, *, secret: str, expected_repository: str,
                     expected_pr_number: int, expected_issue_id: int,
                     expected_head_sha: str, expected_producer_identity: str,
                     controller: str, implementer_session_id: str,
                     max_age_seconds: float = 24 * 3600) -> dict:
    """Verify a producer artifact and return a normalized governed review.

    Fails closed (raises ``GovernanceError``) for any missing field, bad
    signature, mismatched repository/PR/issue, stale head SHA, mismatched or
    untrusted producer identity, implementer/reviewer session collision,
    non-approved disposition, unsatisfied tier hierarchy, or an invalid or
    expired timestamp. Never grants merge or approval authority; it only
    yields evidence for the existing review-tier/current-head validation.
    """
    if not isinstance(artifact, Mapping):
        raise GovernanceError("provenance artifact must be an object")
    missing = [key for key in REQUIRED_FIELDS
               if key not in artifact or artifact[key] in (None, "")]
    if missing or not artifact.get("integrity_signature"):
        raise GovernanceError("provenance artifact is missing required fields")
    if artifact.get("schema_version") != PROVENANCE_SCHEMA_VERSION:
        raise GovernanceError("provenance artifact schema version is unsupported")
    signature = str(artifact.get("integrity_signature"))
    expected_signature = sign_artifact(artifact, secret)
    if not hmac.compare_digest(signature, expected_signature):
        raise GovernanceError("provenance artifact integrity verification failed")
    if str(artifact["repository"]) != str(expected_repository):
        raise GovernanceError("provenance artifact does not match this repository")
    if int(artifact["pr_number"]) != int(expected_pr_number):
        raise GovernanceError("provenance artifact does not match this PR")
    if int(artifact["issue_id"]) != int(expected_issue_id):
        raise GovernanceError("provenance artifact does not match the linked issue")
    if str(artifact["head_sha"]) != str(expected_head_sha):
        raise GovernanceError("provenance artifact is stale; current PR head has changed")
    if str(artifact["producer_identity"]) != str(expected_producer_identity):
        raise GovernanceError("provenance artifact was not created by the trusted producer")
    reviewer = str(artifact["reviewer_identity"])
    reviewer_session = str(artifact["reviewer_session_id"])
    implementer_session = str(artifact["implementer_session_id"])
    if implementer_session != str(implementer_session_id):
        raise GovernanceError(
            "provenance artifact implementer session does not match the PR")
    if reviewer_session == implementer_session:
        raise GovernanceError(
            "reviewer must be independent from the implementing session")
    if reviewer == str(controller) or reviewer_session == str(controller):
        raise GovernanceError("reviewer must be independent from the controller")
    if artifact["disposition"] != "approved":
        raise GovernanceError("provenance artifact does not record an approved review")
    review_tier = artifact["review_tier"]
    required_tier = artifact["required_review_tier"]
    if review_tier not in REVIEW_TIERS or required_tier not in REVIEW_TIERS:
        raise GovernanceError("provenance artifact contains an invalid review tier")
    rank = {tier: index for index, tier in enumerate(REVIEW_TIERS)}
    if rank[review_tier] < rank[required_tier]:
        raise GovernanceError(
            "provenance artifact review tier does not satisfy the required tier")
    try:
        artifact_time = float(artifact["timestamp"])
    except (TypeError, ValueError):
        raise GovernanceError("provenance artifact timestamp is invalid")
    age = time.time() - artifact_time
    if age < 0 or age > max_age_seconds:
        raise GovernanceError("provenance artifact is expired or has an invalid timestamp")
    return {
        "state": "APPROVED",
        "commit_id": artifact["head_sha"],
        "user": reviewer,
        "independent": True,
        "submitted_at": artifact.get("timestamp"),
        "id": artifact.get("review_id"),
        "role": artifact.get("reviewer_role") or "",
        "review_tier": review_tier,
        "reviewer_session_id": reviewer_session,
    }


def record_event(audit: AppendOnlyAudit, path: str, event: str, *,
                  correlation_id: str, **fields: Any) -> None:
    """Append a fail-closed provenance audit event.

    ``event`` must be one of the producer/verifier lifecycle events:
    ``review-producer-start``, ``review-completion``,
    ``provenance-created``, ``provenance-validated``,
    ``provenance-rejected``, ``provenance-stale``, or
    ``review-disposition``. No hidden reasoning traces, credentials, or
    unnecessary model internals may be included in ``fields``.
    """
    payload = {"correlation_id": correlation_id, "timestamp": time.time(), **fields}
    audit.write_jsonl(path, event, payload)
