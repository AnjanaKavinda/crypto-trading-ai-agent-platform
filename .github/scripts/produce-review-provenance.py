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
from independent_reviewer import (
    DirectOwnerReviewerExecutionRequest, ReviewerExecutionError,
    ReviewerExecutionResult, ReviewerExecutionRequest,
    request_from_mapping, verify_execution_handoff,
)
from review_provenance import (build_artifact, build_direct_owner_artifact, record_event,
                                resolve_direct_owner_review_evidence,
                                resolve_review_evidence, required_review_tier_from_labels,
                                verify_artifact, extract_linked_issue)


def _require(name: str) -> str:
    value = os.environ.get(name, "")
    if not value.strip():
        raise GovernanceError(f"missing required producer input: {name}")
    return value


def _load_json(path: str) -> object:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def resolve_execution_evidence(*, result: dict,
                               original_request: ReviewerExecutionRequest | DirectOwnerReviewerExecutionRequest,
                               execution_handoff: dict, handoff_secret: str,
                               pr: dict, issue: dict, reviewer_configuration: dict,
                               reviewer_roles: dict, implementer_session_id: str,
                               controller: str, preferred_reviewer: str = "",
                               model_mapping: dict[str, str] | None = None) -> dict:
    """Validate a real model result and derive identity/tier from trusted config."""
    try:
        parsed = ReviewerExecutionResult(
            **{**result, "findings": tuple(
                __import__("independent_reviewer", fromlist=["Finding"]).Finding.from_mapping(item)
                for item in result.get("findings", []))})
        issue_id = extract_linked_issue(pr.get("body") or "")
        required = required_review_tier_from_labels(issue.get("labels", []))
        direct_owner = isinstance(original_request, DirectOwnerReviewerExecutionRequest)
        if direct_owner and (issue.get("state") != "open"
                             or int(issue.get("number", -1)) != issue_id):
            raise ReviewerExecutionError("linked issue is not the expected open issue")
        if direct_owner and pr.get("state") != "open":
            raise ReviewerExecutionError("direct-owner review requires an open PR")
        base_value = pr.get("base") or {}
        base_repo = base_value.get("repo") if isinstance(base_value, dict) else {}
        pr_repository = pr.get("repository") or base_repo.get("full_name")
        if (parsed.repository != pr_repository or parsed.pr_number != int(pr["number"]) or
                parsed.head_sha != pr.get("head_sha") or parsed.required_review_tier != required):
            raise ReviewerExecutionError("review result is not bound to the current PR/issue")
        implementation_identity = (original_request.implementation_identity
                                   if direct_owner else
                                   f"agent-session:{implementer_session_id}")
        if direct_owner and (pr.get("author") != controller
                             or original_request.controller_identity != controller
                             or original_request.implementation_origin != "DIRECT_OWNER"):
            raise ReviewerExecutionError("direct-owner request does not match the PR author")
        candidates = [
            (login, config) for login, config in reviewer_configuration.items()
            if login != controller and config.get("session_id") not in {
                implementer_session_id, implementation_identity}
            and config.get("tier") in {"R1", "R2", "R3"}
            and (not preferred_reviewer or login == preferred_reviewer)
        ]
        if len(candidates) != 1:
            raise ReviewerExecutionError("trusted AI reviewer identity is ambiguous")
        login, config = candidates[0]
        mapping = model_mapping or json.loads(
            os.environ.get("GOVERNED_REVIEWER_MODEL_MAPPING", "{}"))
        expected_model = mapping.get({
            "R1": "economical-fast", "R2": "strong-coding-reasoning",
            "R3": "premium-strongest-available"}[parsed.required_review_tier])
        if (parsed.provider_name != "openai" or parsed.model_name != expected_model):
            raise ReviewerExecutionError("review result provider/model is not governed")
        if parsed.actual_review_tier != parsed.required_review_tier or (
                reviewer_roles.get(login) and parsed.reviewer_role != reviewer_roles[login]):
            raise ReviewerExecutionError("review result reviewer identity or required tier is untrusted")
        if {"R1": 0, "R2": 1, "R3": 2}[config["tier"]] < {"R1": 0, "R2": 1, "R3": 2}[required]:
            raise ReviewerExecutionError("configured reviewer tier is below the required tier")
        original_request.validate()
        parsed.validate_against(original_request)
        verify_execution_handoff(
            original_request, parsed, execution_handoff, handoff_secret)
        if (original_request.repository != pr.get("repository") or
                original_request.pr_number != int(pr["number"]) or
                original_request.head_sha != pr.get("head_sha") or
                original_request.base_branch != pr.get("base") or
                original_request.github_issue_id != issue_id or
                original_request.canonical_issue_id != issue_id or
                original_request.required_review_tier != required or
                (direct_owner and original_request.implementation_identity !=
                 f"github-user:{controller}") or
                (not direct_owner and original_request.implementation_session_id !=
                 implementer_session_id)):
            raise ReviewerExecutionError(
                "original reviewer request is not bound to the current PR/issue")
        return {"issue_id": issue_id, "head_sha": parsed.head_sha,
                "required_review_tier": required, "review_id": parsed.review_execution_id,
                "reviewer_identity": login, "reviewer_session_id": config["session_id"],
                "review_tier": parsed.actual_review_tier, "disposition": parsed.disposition,
                "result_integrity_hash": parsed.result_integrity_hash,
                "provider_execution_ref": parsed.provider_execution_ref,
                "provider_model": parsed.model_name,
                "request_integrity_hash": original_request.integrity_hash,
                "diff_reference": original_request.diff_reference,
                "execution_handoff_signature": str(execution_handoff.get("signature") or ""),
                "implementation_origin": "DIRECT_OWNER" if direct_owner else "GOVERNED_AGENT",
                "implementation_identity": implementation_identity,
                "review_evidence_kind": "MODEL",
                "review_evidence_id": parsed.review_execution_id}
    except (KeyError, TypeError, StopIteration, ValueError, ReviewerExecutionError) as error:
        raise GovernanceError(str(error)) from error


def main() -> int:
    if len(sys.argv) not in (4, 5, 7):
        print("usage: produce-review-provenance.py PR.json REVIEWS.json ISSUE.json [REQUEST.json | RESULT.json REQUEST.json HANDOFF.json]",
              file=sys.stderr)
        return 2

    audit = AppendOnlyAudit()
    audit_path = os.environ.get("GOVERNED_AUDIT_LOG") or "/tmp/governance-audit.jsonl"
    correlation_id = str(uuid.uuid4())

    try:
        pr_raw = _load_json(sys.argv[1])
        reviews_raw = _load_json(sys.argv[2])
        issue = _load_json(sys.argv[3])
        result_raw = _load_json(sys.argv[4]) if len(sys.argv) == 7 else None
        request_path = sys.argv[5] if len(sys.argv) == 7 else (sys.argv[4] if len(sys.argv) == 5 else None)
        request_raw = _load_json(request_path) if request_path else None
        handoff_raw = _load_json(sys.argv[6]) if len(sys.argv) == 7 else None
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
        controller = _require("GOVERNED_CONTROLLER")
        implementation_origin = ("DIRECT_OWNER" if
                                 (pr_raw.get("user") or {}).get("login") == controller
                                 else "GOVERNED_AGENT")
        implementer_session_id = ("" if implementation_origin == "DIRECT_OWNER" else
                                  _require("GOVERNED_IMPLEMENTER_SESSION"))
        # Platform-provided GitHub Actions context, never a repository
        # *variable* or workflow-dispatch input: binds the artifact to
        # which trusted workflow file/ref/run actually produced it.
        producer_identity = _require("GITHUB_WORKFLOW_REF")
        producer_run_id = _require("GITHUB_RUN_ID")
        secret = _require("GOVERNANCE_PROVENANCE_SIGNING_KEY")
        repository = _require("GITHUB_REPOSITORY")
        handoff_key_file = os.environ.get("GOVERNED_REVIEW_HANDOFF_KEY_FILE", "")
        handoff_secret = (Path(handoff_key_file).read_text(encoding="utf-8").strip()
                          if result_raw is not None and handoff_key_file else "")
        if result_raw is not None and not handoff_secret:
            raise GovernanceError("review result handoff key is unavailable")
        expected_base = os.environ.get("GOVERNED_BASE") or "dev"
        reviewer_configuration = json.loads(os.environ.get("GOVERNED_REVIEWER_TIERS", "{}"))
        reviewer_roles = json.loads(os.environ.get("GOVERNED_REVIEWER_ROLES", "{}"))
    except (GovernanceError, json.JSONDecodeError, OSError) as error:
        print(f"{error}; blocked", file=sys.stderr)
        return 1
    if not isinstance(reviewer_configuration, dict) or not isinstance(reviewer_roles, dict):
        print("trusted reviewer configuration is malformed; blocked", file=sys.stderr)
        return 1

    pr = {
        "number": pr_raw.get("number"),
        "repository": repository,
        "head_sha": (pr_raw.get("head") or {}).get("sha"),
        "base": (pr_raw.get("base") or {}).get("ref"),
        "body": pr_raw.get("body"),
        "author": (pr_raw.get("user") or {}).get("login"),
        "state": pr_raw.get("state"),
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
        if result_raw is not None:
            if not isinstance(request_raw, dict) or not isinstance(handoff_raw, dict):
                raise GovernanceError("review execution request or handoff is malformed")
            original_request = request_from_mapping(request_raw)
            evidence = resolve_execution_evidence(
                result=result_raw, original_request=original_request,
                execution_handoff=handoff_raw, handoff_secret=handoff_secret,
                pr=pr, issue=issue,
                reviewer_configuration=reviewer_configuration, reviewer_roles=reviewer_roles,
                implementer_session_id=implementer_session_id, controller=controller,
                preferred_reviewer=os.environ.get("GOVERNED_AI_REVIEWER", ""),
                model_mapping=json.loads(os.environ.get(
                    "GOVERNED_REVIEWER_MODEL_MAPPING", "{}")))
        else:
            if implementation_origin == "DIRECT_OWNER":
                evidence = resolve_direct_owner_review_evidence(
                    pr=pr, issue=issue, reviews=reviews_raw,
                    reviewer_configuration=reviewer_configuration,
                    controller=controller,
                    implementation_identity=f"github-user:{controller}",
                    expected_base=expected_base)
                if request_raw is None:
                    raise GovernanceError("direct-owner review request binding is required")
                original_request = request_from_mapping(request_raw)
                if not isinstance(original_request, DirectOwnerReviewerExecutionRequest):
                    raise GovernanceError("direct-owner review request has the wrong schema")
                original_request.validate()
                if (original_request.repository != repository
                        or original_request.pr_number != int(pr_number)
                        or original_request.github_issue_id != evidence["issue_id"]
                        or original_request.canonical_issue_id != evidence["issue_id"]
                        or original_request.head_sha != evidence["head_sha"]
                        or original_request.base_branch != pr["base"]
                        or original_request.required_review_tier != evidence["required_review_tier"]
                        or original_request.implementation_identity !=
                        f"github-user:{controller}"):
                    raise GovernanceError("direct-owner review request is stale or mismatched")
                evidence.update({"request_integrity_hash": original_request.integrity_hash,
                                "diff_reference": original_request.diff_reference})
                evidence.update({"implementation_origin": "DIRECT_OWNER",
                                 "implementation_identity": f"github-user:{controller}"})
            else:
                evidence = resolve_review_evidence(
                    pr=pr, issue=issue, reviews=reviews_raw,
                    reviewer_configuration=reviewer_configuration,
                    implementer_session_id=implementer_session_id, controller=controller,
                    expected_base=expected_base)
                evidence.update({"implementation_origin": "GOVERNED_AGENT",
                                 "implementation_identity":
                                     f"agent-session:{implementer_session_id}"})
    except (GovernanceError, KeyError, TypeError, ValueError) as error:
        try:
            record_event(audit, audit_path, "provenance-rejected",
                         correlation_id=correlation_id, reason=str(error))
        except GovernanceError:
            pass
        print(f"{error}; blocked", file=sys.stderr)
        return 1

    try:
        build = (build_direct_owner_artifact if implementation_origin == "DIRECT_OWNER"
                 else build_artifact)
        common = dict(
            repository=repository, pr_number=int(pr_number),
            issue_id=evidence["issue_id"], review_id=evidence["review_id"],
            head_sha=evidence["head_sha"], reviewer_identity=evidence["reviewer_identity"],
            reviewer_session_id=evidence["reviewer_session_id"],
            implementer_session_id=implementer_session_id,
            required_review_tier=evidence["required_review_tier"],
            review_tier=evidence["review_tier"], producer_identity=producer_identity,
            producer_run_id=producer_run_id, controller_policy_version="v1.1",
            disposition=evidence["disposition"], secret=secret,
            reviewer_role=reviewer_roles.get(evidence["reviewer_identity"], ""),
            review_execution_id=evidence.get("review_execution_id", evidence.get("review_id")),
            result_integrity_hash=evidence.get("result_integrity_hash"),
            provider_execution_ref=evidence.get("provider_execution_ref", ""),
            provider_model=evidence.get("provider_model", ""),
            request_integrity_hash=evidence.get("request_integrity_hash", "legacy-github-review"),
            diff_reference=evidence.get("diff_reference", "legacy-github-review"),
            execution_handoff_signature=evidence.get(
                "execution_handoff_signature", "legacy-github-review"))
        if implementation_origin == "DIRECT_OWNER":
            common.update({
                "review_evidence_kind": evidence.get("review_evidence_kind", "MODEL"),
                "review_evidence_id": evidence.get("review_evidence_id", str(evidence.get("review_id"))),
            })
            artifact = build(
                **{key: value for key, value in common.items()
                   if key not in {"implementer_session_id"}},
                base_branch=pr["base"],
                implementation_identity=f"github-user:{controller}",
                controller_identity=controller)
        else:
            artifact = build(**common)
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
                     producer_identity=producer_identity, disposition=evidence["disposition"],
                     implementation_origin=implementation_origin,
                     implementation_identity=evidence.get("implementation_identity", ""))
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
            controller=controller, implementer_session_id=implementer_session_id,
            expected_implementation_origin=implementation_origin,
            expected_implementation_identity=(f"github-user:{controller}"
                                              if implementation_origin == "DIRECT_OWNER" else ""),
            expected_base_branch=pr["base"],
            require_approved=False)
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
