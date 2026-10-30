"""Trusted independent-review producer artifact and provenance verifier.

Implements the Model Routing & AI Usage Governance V1.1 "Implementation
handoff" prerequisite (see
``docs/copilot-team/03-github-workflow/MODEL-ROUTING-GOVERNANCE-V1.1.md``,
section 7): a separately approved producer that emits evidence bound to the
review ID, current PR head SHA, reviewer identity/session, review tier, and
producer identity. Dispatched-agent schema 1.2 retains its required
implementer session; direct-owner schema 1.3 binds an explicit owner origin
and identity without inventing an agent session.

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
import json
import re
import time
from typing import Any, Iterable, Mapping

from orchestrator import AppendOnlyAudit, GovernanceError, REVIEW_TIERS

PROVENANCE_SCHEMA_VERSION = "1.2"
DIRECT_OWNER_PROVENANCE_SCHEMA_VERSION = "1.3"

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
    "reviewer_role",
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
    "provider_model",
    "request_integrity_hash",
    "diff_reference",
    "execution_handoff_signature",
)

# Schema 1.2 is the immutable dispatched-agent format. Schema 1.3 adds an
# explicit owner origin and deliberately has no agent/session fields.
DIRECT_OWNER_FIELDS = tuple(
    field for field in REQUIRED_FIELDS if field != "implementer_session_id"
) + ("implementation_origin", "implementation_identity", "controller_identity",
     "base_branch", "review_evidence_kind", "review_evidence_id")
DIRECT_OWNER_REQUIRED_FIELDS = tuple(
    field for field in DIRECT_OWNER_FIELDS
    if field not in {"provider_execution_ref", "provider_model", "execution_handoff_signature"}
)
PROVENANCE_FIELDS_BY_VERSION = {
    PROVENANCE_SCHEMA_VERSION: REQUIRED_FIELDS,
    DIRECT_OWNER_PROVENANCE_SCHEMA_VERSION: DIRECT_OWNER_FIELDS,
}

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
DISPATCH_MARKER = "<!-- governed-copilot-orchestrator:v1 -->"


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
    """Extract one unambiguous governed linked-issue number from a PR body.

    Closing keywords (Closes/Fixes/Resolves) and the non-closing governance
    reference form 'Related to #N' are accepted. The parser fails closed
    when there is no governed reference or when distinct issue numbers are
    referenced, so a workflow cannot silently choose one of several issues.
    Repeating the same issue number with multiple accepted keywords remains
    unambiguous and is allowed.
    """
    matches = re.findall(
        r"(?im)\b(?:closes|fixes|resolves|related\s+to)\s+#(\d+)",
        body or "",
    )
    issue_ids = {int(value) for value in matches}
    if not issue_ids:
        raise GovernanceError("PR has no recorded linked issue")
    if len(issue_ids) != 1:
        raise GovernanceError("PR has ambiguous linked issues")
    return next(iter(issue_ids))


def derive_current_dispatch_key(*, comments: Iterable[Mapping[str, Any]],
                                pr_number: int, issue_id: int, base: str,
                                head_sha: str, pr_body: str = "",
                                require_current_binding: bool = True) -> str:
    """Derive exactly one current dispatch key from trusted bot evidence.

    The PR body is only a consistency check.  It is not required to carry the
    key, because the authoritative handoff is the controller's comment.
    """
    if base != "dev" or not head_sha:
        raise GovernanceError("dispatch binding has an invalid base or head")
    candidates: set[str] = set()
    stale_seen = False
    for comment in comments:
        if (not isinstance(comment, Mapping) or
                (comment.get("user") or {}).get("login") != "github-actions[bot]"):
            continue
        body = str(comment.get("body") or "")
        if DISPATCH_MARKER not in body:
            continue
        key_match = re.search(r"(?m)(?:^|\s)dispatch_key:([A-Za-z0-9_-]+)(?:\s|$)", body)
        if not key_match:
            continue
        key = key_match.group(1)
        if "PR_BINDING:" in body:
            binding = re.search(
                r"PR_BINDING:(\d+)\s+head_sha:([A-Za-z0-9]+)\s+"
                r"dispatch_key:([A-Za-z0-9_-]+)", body)
            if not binding:
                raise GovernanceError("malformed trusted PR dispatch binding")
            if int(binding.group(1)) != int(pr_number):
                continue
            if binding.group(3) != key:
                raise GovernanceError("dispatch binding key is inconsistent")
            if binding.group(2) != head_sha:
                stale_seen = True
                continue
            candidates.add(key)
            continue
        if require_current_binding:
            # Intent and assignment-completion comments establish lineage only.
            # They are deliberately insufficient as a current PR binding.
            continue
        record_match = re.search(
            r"(?m)^(?:DISPATCH|DISPATCH_INTENT|ASSIGNMENT_COMPLETED)\s+(\{.*\})\s*$",
            body)
        if not record_match:
            continue
        try:
            record = json.loads(record_match.group(1))
        except json.JSONDecodeError as error:
            raise GovernanceError("malformed trusted dispatch evidence") from error
        if (record.get("issue_id") != int(issue_id) or
                record.get("base_branch") not in (None, "dev")):
            raise GovernanceError("dispatch evidence is stale or bound to another issue/base")
        if record.get("pr_id") not in (None, int(pr_number)):
            continue
        if record.get("head_sha") not in (None, head_sha):
            stale_seen = True
            continue
        candidates.add(key)
    body_keys = set(re.findall(r"dispatch_key:([A-Za-z0-9_-]+)", pr_body or ""))
    if body_keys and (len(body_keys) != 1 or candidates != body_keys):
        raise GovernanceError("PR dispatch key does not match trusted current binding")
    if len(candidates) != 1:
        if stale_seen:
            raise GovernanceError("trusted dispatch evidence is stale for the current PR head")
        raise GovernanceError("trusted current dispatch key is missing or ambiguous")
    return next(iter(candidates))

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
        if rank[tier] < rank[required_tier]:
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
            # Configuration is an authorization ceiling.  The review event's
            # effective tier is the policy requirement, not the ceiling.
            "review_tier": required_tier,
            "disposition": disposition,
            "submitted_at": item.get("submitted_at") or "",
        }
        candidate_key = (
            1 if disposition == "approved" else 0,
            rank[required_tier],
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


def resolve_direct_owner_review_evidence(*, pr: Mapping[str, Any], issue: Mapping[str, Any],
                                         reviews: Iterable[Mapping[str, Any]],
                                         reviewer_configuration: Mapping[str, Any],
                                         controller: str,
                                         implementation_identity: str,
                                         expected_base: str = "dev") -> dict:
    """Resolve configured independent review for an explicitly owner-authored PR."""
    head_sha = str(pr.get("head_sha") or "")
    author = str(pr.get("author") or "")
    base = str(pr.get("base") or "")
    if not head_sha or not controller or author != controller or base != expected_base:
        raise GovernanceError("direct-owner PR origin, head, or base is invalid")
    if implementation_identity != f"github-user:{controller}":
        raise GovernanceError("direct-owner implementation identity is invalid")
    issue_id = extract_linked_issue(pr.get("body") or "")
    if issue.get("state") != "open" or int(issue.get("number", -1)) != issue_id:
        raise GovernanceError("direct-owner linked issue is not the expected open issue")
    required_tier = required_review_tier_from_labels(issue.get("labels", []))
    rank = {tier: index for index, tier in enumerate(REVIEW_TIERS)}
    # GitHub returns a history of reviews. Resolve each reviewer's latest
    # submitted state before evaluating it; an earlier approval must not
    # survive a later request for changes or dismissal.
    latest_by_reviewer: dict[str, Mapping[str, Any]] = {}
    for item in reviews:
        if not isinstance(item, Mapping):
            continue
        login = str((item.get("user") or {}).get("login") or "")
        if not login:
            continue
        previous = latest_by_reviewer.get(login)
        item_key = (str(item.get("submitted_at") or ""), int(item.get("id") or 0))
        previous_key = ((str(previous.get("submitted_at") or ""),
                         int(previous.get("id") or 0)) if previous else ("", 0))
        if previous is None or item_key > previous_key:
            latest_by_reviewer[login] = item

    best: dict | None = None
    for item in latest_by_reviewer.values():
        login = str((item.get("user") or {}).get("login") or "")
        config = reviewer_configuration.get(login)
        if not login or login == controller or not isinstance(config, Mapping):
            continue
        session_id = config.get("session_id")
        tier = config.get("tier")
        if (not isinstance(session_id, str) or not session_id.strip()
                or tier not in REVIEW_TIERS or rank[tier] < rank[required_tier]
                or session_id in {controller, implementation_identity}
                or str(item.get("commit_id") or "") != head_sha):
            continue
        disposition = _REVIEW_STATE_DISPOSITIONS.get(str(item.get("state") or "").upper())
        if disposition is None:
            continue
        review_identity = {
            "id": item.get("id"), "login": login,
            "commit_id": item.get("commit_id"), "state": item.get("state"),
            "submitted_at": item.get("submitted_at"),
            "body_sha256": hashlib.sha256(str(item.get("body") or "").encode()).hexdigest(),
        }
        evidence_digest = hashlib.sha256(json.dumps(
            review_identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        candidate = {
            "review_id": item.get("id"),
            "review_execution_id": f"github-review-{item.get('id')}",
            "reviewer_identity": login,
            "reviewer_session_id": session_id,
            "review_tier": required_tier,
            "disposition": disposition,
            "submitted_at": item.get("submitted_at") or "",
            "review_evidence_kind": "GITHUB_REVIEW",
            "review_evidence_id": str(item.get("id") or ""),
            "result_integrity_hash": evidence_digest,
            "provider_execution_ref": "",
            "provider_model": "",
            "execution_handoff_signature": "",
        }
        candidate_key = (1 if disposition == "changes-requested" else 0, rank[required_tier],
                         str(candidate["submitted_at"]))
        if best is None or candidate_key > best["_key"]:
            candidate["_key"] = candidate_key
            best = candidate
    if best is None:
        raise GovernanceError(
            "no current-head independent review at the required tier was found")
    best.pop("_key", None)
    return {"issue_id": issue_id, "head_sha": head_sha,
            "required_review_tier": required_tier, **best}


class StaleProvenanceError(GovernanceError):
    """Raised when a provenance artifact no longer matches the current PR head."""


def _canonical_payload(artifact: Mapping[str, Any]) -> bytes:
    import json

    fields = PROVENANCE_FIELDS_BY_VERSION.get(str(artifact.get("schema_version")))
    if fields is None:
        raise GovernanceError("provenance artifact schema version is unsupported")
    body = {key: artifact[key] for key in fields if key in artifact}
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
                    provider_execution_ref: str = "", provider_model: str = "",
                    request_integrity_hash: str = "legacy-github-review",
                    diff_reference: str = "legacy-github-review",
                    execution_handoff_signature: str = "legacy-github-review") -> dict:
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
        "reviewer_role": reviewer_role or "unclassified-reviewer",
        "review_execution_id": review_execution_id or f"github-review-{review_id}",
        "result_integrity_hash": result_integrity_hash or "legacy-github-review",
        "provider_execution_ref": provider_execution_ref or f"github-review-{review_id}",
        "provider_model": provider_model or "github-review",
        "request_integrity_hash": request_integrity_hash,
        "diff_reference": diff_reference,
        "execution_handoff_signature": execution_handoff_signature,
    }
    artifact["integrity_signature"] = sign_artifact(artifact, secret)
    return artifact


def build_direct_owner_artifact(*, repository: str, pr_number: int, issue_id: int,
                                review_id: Any, head_sha: str, base_branch: str,
                                reviewer_identity: str, reviewer_session_id: str,
                                implementation_identity: str, controller_identity: str,
                                required_review_tier: str, review_tier: str,
                                producer_identity: str, producer_run_id: str,
                                controller_policy_version: str, disposition: str,
                                secret: str, reviewer_role: str = "",
                                timestamp: float | None = None,
                                review_execution_id: str | None = None,
                                result_integrity_hash: str | None = None,
                                provider_execution_ref: str = "",
                                provider_model: str = "",
                                request_integrity_hash: str = "",
                                diff_reference: str = "",
                                execution_handoff_signature: str = "",
                                review_evidence_kind: str = "MODEL",
                                review_evidence_id: str = "") -> dict:
    """Build signed 1.3 provenance for direct-owner implementation."""
    implementation_identity = str(implementation_identity).strip()
    controller_identity = str(controller_identity).strip()
    if (not controller_identity or implementation_identity !=
            f"github-user:{controller_identity}" or reviewer_identity == controller_identity
            or reviewer_session_id in {controller_identity, implementation_identity}):
        raise GovernanceError("direct-owner implementation identity is invalid")
    if not all(isinstance(value, str) and value.strip() for value in
               (repository, head_sha, base_branch, reviewer_identity, reviewer_session_id,
                producer_identity, producer_run_id, controller_policy_version)):
        raise GovernanceError("provenance artifact fields are incomplete")
    if base_branch != "dev":
        raise GovernanceError("direct-owner provenance requires the dev base branch")
    if required_review_tier not in REVIEW_TIERS or review_tier != required_review_tier:
        raise GovernanceError("direct-owner review tier is invalid or insufficient")
    if disposition not in DISPOSITIONS:
        raise GovernanceError("provenance artifact disposition is invalid")
    if review_evidence_kind not in {"MODEL", "GITHUB_REVIEW"}:
        raise GovernanceError("direct-owner review evidence kind is invalid")
    effective_review_execution_id = review_execution_id or f"review-{review_id}"
    if not review_evidence_id:
        review_evidence_id = str(effective_review_execution_id)
    if review_evidence_kind == "MODEL" and not all(
            (provider_execution_ref, provider_model, execution_handoff_signature)):
        raise GovernanceError("model review evidence is incomplete")
    if review_evidence_kind == "MODEL" and str(review_evidence_id) != str(
            effective_review_execution_id):
        raise GovernanceError("model review evidence identity is inconsistent")
    if review_evidence_kind == "GITHUB_REVIEW" and any(
            (provider_execution_ref, provider_model, execution_handoff_signature)):
        raise GovernanceError("GitHub review evidence cannot claim model execution")
    artifact = {
        "schema_version": DIRECT_OWNER_PROVENANCE_SCHEMA_VERSION,
        "repository": repository,
        "pr_number": int(pr_number),
        "issue_id": int(issue_id),
        "review_id": review_id,
        "head_sha": head_sha,
        "reviewer_identity": reviewer_identity,
        "reviewer_session_id": reviewer_session_id,
        "reviewer_role": reviewer_role or "unclassified-reviewer",
        "required_review_tier": required_review_tier,
        "review_tier": review_tier,
        "producer_identity": producer_identity,
        "producer_run_id": producer_run_id,
        "controller_policy_version": controller_policy_version,
        "timestamp": float(timestamp) if timestamp is not None else time.time(),
        "disposition": disposition,
        "review_execution_id": effective_review_execution_id,
        "result_integrity_hash": result_integrity_hash or "",
        "provider_execution_ref": provider_execution_ref,
        "provider_model": provider_model,
        "request_integrity_hash": request_integrity_hash,
        "diff_reference": diff_reference,
        "execution_handoff_signature": execution_handoff_signature,
        "implementation_origin": "DIRECT_OWNER",
        "implementation_identity": implementation_identity,
        "controller_identity": controller_identity,
        "base_branch": base_branch,
        "review_evidence_kind": review_evidence_kind,
        "review_evidence_id": str(review_evidence_id),
    }
    if not all(artifact.get(field) not in (None, "")
               for field in DIRECT_OWNER_REQUIRED_FIELDS):
        raise GovernanceError("direct-owner provenance artifact fields are incomplete")
    artifact["integrity_signature"] = sign_artifact(artifact, secret)
    return artifact


def verify_artifact(artifact: Any, *, secret: str, expected_repository: str,
                     expected_pr_number: int, expected_issue_id: int,
                     expected_head_sha: str, expected_producer_identity: str,
                    controller: str, implementer_session_id: str = "",
                    expected_implementation_origin: str = "GOVERNED_AGENT",
                    expected_implementation_identity: str = "",
                    expected_base_branch: str = "dev",
                     max_age_seconds: float = 24 * 3600,
                     require_approved: bool = True) -> dict:
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
    schema_version = str(artifact.get("schema_version") or "")
    artifact_fields = PROVENANCE_FIELDS_BY_VERSION.get(schema_version)
    if artifact_fields is None:
        raise GovernanceError("provenance artifact schema version is unsupported")
    required_fields = (DIRECT_OWNER_REQUIRED_FIELDS
                       if schema_version == DIRECT_OWNER_PROVENANCE_SCHEMA_VERSION
                       else REQUIRED_FIELDS)
    missing = [key for key in required_fields
               if key not in artifact or artifact[key] in (None, "")]
    if missing or not artifact.get("integrity_signature"):
        raise GovernanceError("provenance artifact is missing required fields")
    if schema_version == PROVENANCE_SCHEMA_VERSION:
        if expected_implementation_origin != "GOVERNED_AGENT":
            raise GovernanceError("agent provenance cannot authorize a direct-owner PR")
        if any(key in artifact for key in (
                "implementation_origin", "implementation_identity", "controller_identity")):
            raise GovernanceError("schema 1.2 artifact contains unsupported origin fields")
    elif expected_implementation_origin != "DIRECT_OWNER":
        raise GovernanceError("direct-owner provenance cannot authorize an agent PR")
    else:
        if any(key in artifact for key in ("implementer_session_id", "agent_role", "dispatch_key")):
            raise GovernanceError("direct-owner provenance contains agent-only fields")
        if set(artifact) != set(DIRECT_OWNER_FIELDS) | {"integrity_signature"}:
            raise GovernanceError("direct-owner provenance contains unsupported fields")
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
    if schema_version == PROVENANCE_SCHEMA_VERSION:
        implementer_session = str(artifact["implementer_session_id"])
        if implementer_session != str(implementer_session_id):
            raise GovernanceError(
                "provenance artifact implementer session does not match the PR")
        if reviewer_session == implementer_session:
            raise GovernanceError(
                "reviewer must be independent from the implementing session")
        implementation_origin = "GOVERNED_AGENT"
        implementation_identity = f"agent-session:{implementer_session}"
    else:
        implementation_origin = str(artifact["implementation_origin"])
        implementation_identity = str(artifact["implementation_identity"])
        owner_identity = str(artifact["controller_identity"])
        if (implementation_origin != "DIRECT_OWNER"
                or owner_identity != str(controller)
                or implementation_identity != f"github-user:{owner_identity}"
                or (expected_implementation_identity and
                    implementation_identity != expected_implementation_identity)
                or str(artifact["base_branch"]) != expected_base_branch
                or reviewer_session == implementation_identity):
            raise GovernanceError("direct-owner provenance identity or base binding is invalid")
        evidence_kind = artifact.get("review_evidence_kind")
        if evidence_kind == "MODEL":
            if not all(artifact.get(key) for key in (
                    "provider_execution_ref", "provider_model", "execution_handoff_signature")):
                raise GovernanceError("direct-owner model review evidence is incomplete")
            if str(artifact.get("review_evidence_id")) != str(artifact.get("review_execution_id")):
                raise GovernanceError("direct-owner model review evidence identity is invalid")
        elif evidence_kind == "GITHUB_REVIEW":
            if (str(artifact.get("review_evidence_id")) != str(artifact.get("review_id"))
                    or any(artifact.get(key) for key in (
                        "provider_execution_ref", "provider_model", "execution_handoff_signature"))):
                raise GovernanceError("direct-owner GitHub review evidence is invalid")
        else:
            raise GovernanceError("direct-owner review evidence kind is unsupported")
    if reviewer == str(controller) or reviewer_session == str(controller):
        raise GovernanceError("reviewer must be independent from the controller")
    if artifact["disposition"] not in DISPOSITIONS:
        raise GovernanceError("provenance artifact contains an invalid disposition")
    if require_approved and artifact["disposition"] != "approved":
        raise GovernanceError("provenance artifact does not record an approved review")
    review_tier = artifact["review_tier"]
    required_tier = artifact["required_review_tier"]
    if review_tier not in REVIEW_TIERS or required_tier not in REVIEW_TIERS:
        raise GovernanceError("provenance artifact contains an invalid review tier")
    if review_tier != required_tier:
        raise GovernanceError("actual review tier must equal the required tier")
    try:
        artifact_time = float(artifact["timestamp"])
    except (TypeError, ValueError):
        raise GovernanceError("provenance artifact timestamp is invalid")
    age = time.time() - artifact_time
    if age < 0 or age > max_age_seconds:
        raise StaleProvenanceError(
            "provenance artifact is expired or has an invalid timestamp")
    normalized_state = {
        "approved": "APPROVED",
        "changes-requested": "CHANGES_REQUESTED",
        "blocked": "BLOCKED",
    }[str(artifact["disposition"])]
    return {
        "state": normalized_state,
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
        "review_execution_id": artifact.get("review_execution_id"),
        "result_integrity_hash": artifact.get("result_integrity_hash"),
        "provider_execution_ref": artifact.get("provider_execution_ref"),
        "provider_model": artifact.get("provider_model"),
        "request_integrity_hash": artifact.get("request_integrity_hash"),
        "diff_reference": artifact.get("diff_reference"),
        "execution_handoff_signature": artifact.get("execution_handoff_signature"),
        "implementation_origin": implementation_origin,
        "implementation_identity": implementation_identity,
        "controller_identity": (artifact.get("controller_identity")
                                if schema_version == DIRECT_OWNER_PROVENANCE_SCHEMA_VERSION
                                else str(controller)),
        "base_branch": (artifact.get("base_branch")
                        if schema_version == DIRECT_OWNER_PROVENANCE_SCHEMA_VERSION
                        else expected_base_branch),
        "review_evidence_kind": (artifact.get("review_evidence_kind")
                                 if schema_version == DIRECT_OWNER_PROVENANCE_SCHEMA_VERSION
                                 else "GOVERNED_AGENT"),
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
