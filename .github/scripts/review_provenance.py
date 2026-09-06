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

Crucially, the signature alone does not establish that a genuine
independent review occurred -- it only proves the trusted producer
signed *whatever it was given*. :func:`resolve_review_evidence` is the
function that decides what may be signed: it derives ``disposition``,
``reviewer_identity``, ``reviewer_session_id`` and the actual
``review_tier`` exclusively from an authenticated GitHub review already
submitted, at the PR's current head commit, by a reviewer present in the
trusted reviewer-tier configuration. Nothing about the review outcome is
accepted as a workflow-dispatch input or other human-supplied value, so a
human dispatching the producer workflow cannot choose ``approved`` or
fabricate an actual tier -- the producer signs evidence of a review that
already happened, it does not perform or invent one itself. Likewise,
``producer_identity``/``producer_run_id`` must be sourced from the GitHub
Actions platform's own ``GITHUB_WORKFLOW_REF``/``GITHUB_RUN_ID`` context
(never a repository *variable*), so the verifier's trust anchor for the
producer itself is bound to which workflow file/ref/run actually executed
it, not to an editable value that happens to be echoed back.

This module intentionally contains no GitHub client, merge capability, or
repository-owner/controller authority. It only builds and verifies
evidence; final merge authority always remains with the human repository
owner.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import time
from typing import Any, Iterable, Mapping

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
    "producer_run_id",
    "controller_policy_version",
    "timestamp",
    "disposition",
    "review_execution_id",
    "result_integrity_hash",
    "provider_execution_ref",
)

DISPOSITIONS = ("approved", "changes-requested", "blocked")

# Same classification the trusted base-branch controller
# (run-pr-governance.py) uses to derive the required review tier from the
# linked issue's labels. Kept in one place so the producer independently
# derives the same required tier the verifier will enforce, instead of
# trusting a caller-supplied "required_review_tier" value.
HIGH_RISK_REVIEW_LABELS = {
    "risk:high", "risk:critical", "type:architecture", "type:contract",
    "type:security", "impact:architecture", "impact:shared-contract",
    "impact:security", "impact:trading-risk", "impact:approval-execution-ccxt",
}
LOW_RISK_REVIEW_LABELS = {"risk:low", "type:docs", "type:test"}

# GitHub review states that can ever establish disposition. Anything else
# (COMMENTED, DISMISSED, PENDING) is not a completed independent review.
_REVIEW_STATE_DISPOSITIONS = {"APPROVED": "approved", "CHANGES_REQUESTED": "changes-requested"}


def required_review_tier_from_labels(labels: Iterable[Any]) -> str:
    """Classify the required review tier from linked-issue labels.

    Mirrors the label classification in ``run-pr-governance.py`` so the
    producer can derive the requirement independently of any caller input.
    """
    names = {(label.get("name") if isinstance(label, Mapping) else label)
             for label in labels}
    if names & HIGH_RISK_REVIEW_LABELS:
        return "R3"
    if names & LOW_RISK_REVIEW_LABELS:
        return "R1"
    return "R2"


def extract_linked_issue(body: str) -> int:
    """Extract the canonical linked issue number from a PR body.

    Raises ``GovernanceError`` (fail closed) when no linked issue is
    recorded; a PR without a recorded linked issue can never be bound to
    approved provenance.
    """
    match = re.search(r"(?im)\b(?:closes|fixes|resolves)\s+#(\d+)", body or "")
    if not match:
        raise GovernanceError("PR has no recorded linked issue")
    return int(match.group(1))


def resolve_review_evidence(*, pr: Mapping[str, Any], issue: Mapping[str, Any],
                             reviews: Iterable[Mapping[str, Any]],
                             reviewer_configuration: Mapping[str, Any],
                             implementer_session_id: str, controller: str,
                             expected_base: str = "dev") -> dict:
    """Derive review disposition, tier, and reviewer identity from GitHub state.

    Nothing returned here is a trusted human/workflow-dispatch input.
    ``disposition``, ``reviewer_identity``, ``reviewer_session_id`` and the
    actual ``review_tier`` are derived only from an authenticated GitHub
    review that is currently submitted, at the PR's current head commit, by
    a reviewer present in the trusted reviewer-tier configuration
    (``GOVERNED_REVIEWER_TIERS``). A human dispatching the producer workflow
    cannot choose the disposition, the actual tier, or the reviewer identity
    -- those values only exist if a real, current-head GitHub review already
    contains them. Raises ``GovernanceError`` (fail closed) when no such
    review exists, so no artifact is ever produced for a PR that has not
    actually been independently reviewed at its current head.
    """
    head_sha = str(pr.get("head_sha") or "")
    base = str(pr.get("base") or "")
    if not head_sha:
        raise GovernanceError("current PR head SHA could not be determined")
    if base != expected_base:
        raise GovernanceError(f"PR base must be {expected_base!r}, found {base!r}")
    issue_id = extract_linked_issue(pr.get("body") or "")
    issue_number = issue.get("number")
    if issue_number is not None and int(issue_number) != issue_id:
        raise GovernanceError("fetched issue does not match the PR's linked issue")
    required_tier = required_review_tier_from_labels(issue.get("labels", []))
    rank = {tier: index for index, tier in enumerate(REVIEW_TIERS)}
    best: dict | None = None
    for item in reviews:
        if not isinstance(item, Mapping):
            continue
        login = (item.get("user") or {}).get("login")
        if not isinstance(login, str) or login not in reviewer_configuration:
            continue
        if login == controller:
            continue
        config = reviewer_configuration.get(login) or {}
        session_id = config.get("session_id")
        tier = config.get("tier")
        if tier not in REVIEW_TIERS or not isinstance(session_id, str) or not session_id.strip():
            continue
        if session_id == implementer_session_id:
            continue
        if str(item.get("commit_id") or "") != head_sha:
            continue
        disposition = _REVIEW_STATE_DISPOSITIONS.get(str(item.get("state") or "").upper())
        if disposition is None:
            continue
        candidate = {
            "review_id": item.get("id"),
            "reviewer_identity": login,
            "reviewer_session_id": session_id,
            "review_tier": tier,
            "disposition": disposition,
            "submitted_at": item.get("submitted_at") or "",
        }
        candidate_key = (
            1 if disposition == "approved" else 0,
            rank[tier],
            str(candidate["submitted_at"]),
        )
        if best is None or candidate_key > best["_key"]:
            candidate["_key"] = candidate_key
            best = candidate
    if best is None:
        raise GovernanceError(
            "no current-head independent review from a configured reviewer was found")
    best.pop("_key", None)
    return {"issue_id": issue_id, "head_sha": head_sha,
            "required_review_tier": required_tier, **best}


class StaleProvenanceError(GovernanceError):
    """Raised when a provenance artifact no longer matches the current PR head."""


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
                    review_tier: str, producer_identity: str, producer_run_id: str,
                    controller_policy_version: str, disposition: str, secret: str,
                    reviewer_role: str = "", timestamp: float | None = None,
                    review_execution_id: str | None = None,
                    result_integrity_hash: str | None = None,
                    provider_execution_ref: str = "") -> dict:
    """Build and sign a provenance artifact for a completed independent review.

    ``producer_identity`` and ``producer_run_id`` must be sourced from the
    GitHub Actions platform's own workflow-ref/run-id context, never a
    repository *variable* or other caller-supplied value, so the signature
    binds the artifact to which trusted workflow/run actually produced it.

    Raises ``GovernanceError`` rather than producing an artifact that would
    fail verification (for example when the reviewer session collides with
    the implementer session).
    """
    if not all(isinstance(value, str) and value.strip() for value in
               (repository, head_sha, reviewer_identity, reviewer_session_id,
                implementer_session_id, producer_identity, producer_run_id,
                controller_policy_version)):
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
        "producer_run_id": producer_run_id,
        "controller_policy_version": controller_policy_version,
        "timestamp": float(timestamp) if timestamp is not None else time.time(),
        "disposition": disposition,
        "reviewer_role": reviewer_role,
        "review_execution_id": review_execution_id or f"github-review-{review_id}",
        "result_integrity_hash": result_integrity_hash or "legacy-github-review",
        "provider_execution_ref": provider_execution_ref,
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
        raise StaleProvenanceError("provenance artifact is stale; current PR head has changed")
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
        raise StaleProvenanceError(
            "provenance artifact is expired or has an invalid timestamp")
    return {
        "state": "APPROVED",
        "commit_id": artifact["head_sha"],
        "user": reviewer,
        "independent": True,
        "submitted_at": artifact.get("timestamp"),
        "id": artifact.get("review_id"),
        "role": artifact.get("reviewer_role") or "",
        "producer_identity": artifact.get("producer_identity"),
        "producer_run_id": artifact.get("producer_run_id"),
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
