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
from independent_reviewer import (ReviewerExecutionError, ReviewerExecutionResult,
                                  build_request, CAPABILITY_TIERS)
from review_provenance import (build_artifact, record_event,
                                resolve_review_evidence, required_review_tier_from_labels,
                                verify_artifact, extract_linked_issue)


def _require(name: str) -> str:
    value = os.environ.get(name, "")
    if not value.strip():
        raise GovernanceError(f"missing required producer input: {name}")
    return value


def _load_json(path: str) -> object:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def resolve_execution_evidence(*, result: dict, pr: dict, issue: dict,
                               reviewer_configuration: dict, reviewer_roles: dict,
                               implementer_session_id: str, controller: str,
                               preferred_reviewer: str = "",
                               model_mapping: dict[str, str] | None = None) -> dict:
    """Validate a real model result and derive identity/tier from trusted config."""
    try:
        parsed = ReviewerExecutionResult(
            **{**result, "findings": tuple(
                __import__("independent_reviewer", fromlist=["Finding"]).Finding.from_mapping(item)
                for item in result.get("findings", []))})
        issue_id = extract_linked_issue(pr.get("body") or "")
        required = required_review_tier_from_labels(issue.get("labels", []))
        if (parsed.repository != pr.get("repository") or parsed.pr_number != int(pr["number"]) or
                parsed.head_sha != pr.get("head_sha") or parsed.required_review_tier != required):
            raise ReviewerExecutionError("review result is not bound to the current PR/issue")
        candidates = [
            (login, config) for login, config in reviewer_configuration.items()
            if login != controller and config.get("session_id") != implementer_session_id
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
        if parsed.provider_name != "openai" or parsed.model_name != expected_model:
            raise ReviewerExecutionError("review result provider/model is not governed")
        if parsed.actual_review_tier != config["tier"] or (
                reviewer_roles.get(login) and parsed.reviewer_role != reviewer_roles[login]):
            raise ReviewerExecutionError("review result reviewer identity or tier is untrusted")
        parsed.validate_against(build_request(
                schema_version="1.0", repository=parsed.repository, pr_number=parsed.pr_number,
                head_sha=parsed.head_sha, base_branch=pr.get("base", "dev"),
                github_issue_id=issue_id, canonical_issue_id=issue_id,
                agent_role="unknown", reviewer_role=parsed.reviewer_role,
                required_review_tier=parsed.required_review_tier,
                capability_tier=next(tier for tier in CAPABILITY_TIERS
                                     if tier == {"R1": "economical-fast", "R2": "strong-coding-reasoning",
                                                 "R3": "premium-strongest-available"}[parsed.required_review_tier]),
                context_pack_id=parsed.context_pack_id,
                context_pack_version=parsed.context_pack_version,
                implementation_session_id=implementer_session_id,
                review_execution_id=parsed.review_execution_id,
                allowed_paths=("**",), forbidden_paths=("secrets/**",),
                changed_files=("review",), diff_reference="execution-result",
                required_checks=parsed.deterministic_check_refs,
                safety_invariants=("no-merge",), controller_policy_version="v1.1"),
        )
        return {"issue_id": issue_id, "head_sha": parsed.head_sha,
                "required_review_tier": required, "review_id": parsed.review_execution_id,
                "reviewer_identity": login, "reviewer_session_id": config["session_id"],
                "review_tier": parsed.actual_review_tier, "disposition": parsed.disposition,
                "result_integrity_hash": parsed.result_integrity_hash,
                "provider_execution_ref": parsed.provider_execution_ref,
                "provider_model": parsed.model_name}
    except (KeyError, TypeError, StopIteration, ValueError, ReviewerExecutionError) as error:
        raise GovernanceError(str(error)) from error


def main() -> int:
    if len(sys.argv) not in (4, 5):
        print("usage: produce-review-provenance.py PR.json REVIEWS.json ISSUE.json [RESULT.json]",
              file=sys.stderr)
        return 2

    audit = AppendOnlyAudit()
    audit_path = os.environ.get("GOVERNED_AUDIT_LOG") or "/tmp/governance-audit.jsonl"
    correlation_id = str(uuid.uuid4())

    try:
        pr_raw = _load_json(sys.argv[1])
        reviews_raw = _load_json(sys.argv[2])
        issue = _load_json(sys.argv[3])
        result_raw = _load_json(sys.argv[4]) if len(sys.argv) == 5 else None
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
        "number": pr_raw.get("number"),
        "repository": repository,
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
        if result_raw is not None:
            evidence = resolve_execution_evidence(
                result=result_raw, pr=pr, issue=issue,
                reviewer_configuration=reviewer_configuration, reviewer_roles=reviewer_roles,
                implementer_session_id=implementer_session_id, controller=controller,
                preferred_reviewer=os.environ.get("GOVERNED_AI_REVIEWER", ""),
                model_mapping=json.loads(os.environ.get(
                    "GOVERNED_REVIEWER_MODEL_MAPPING", "{}")))
        else:
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
            reviewer_role=reviewer_roles.get(evidence["reviewer_identity"], ""),
            review_execution_id=evidence.get("review_id"),
            result_integrity_hash=evidence.get("result_integrity_hash"),
            provider_execution_ref=evidence.get("provider_execution_ref", ""),
            provider_model=evidence.get("provider_model", ""))
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
            controller=controller, implementer_session_id=implementer_session_id,
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
