"""Vendor-neutral, fail-closed independent reviewer execution contract."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
import time
import uuid
from typing import Any, Callable, Mapping

from orchestrator import CAPABILITY_TIERS, GovernanceError, REVIEW_TIERS, detect_secret

DISPOSITIONS = ("approved", "changes-requested", "blocked")
SEVERITIES = ("info", "low", "medium", "high", "critical")
CATEGORIES = (
    "architecture", "security", "governance", "correctness", "testing",
    "statistical", "risk", "execution", "maintainability", "scope", "other",
)
TIER_MODELS = {
    "economical-fast": "gpt-5.6-luna",
    "strong-coding-reasoning": "gpt-5.6-terra",
    "premium-strongest-available": "gpt-5.6-sol",
}
TIER_RANK = {tier: index for index, tier in enumerate(REVIEW_TIERS)}


class ReviewerExecutionError(GovernanceError):
    """A provider, contract, integrity, or current-head failure."""


@dataclass(frozen=True)
class Finding:
    finding_id: str
    severity: str
    category: str
    title: str
    summary: str
    blocking: bool
    recommended_action: str
    path: str = ""
    line_or_location: str = ""
    contract_or_policy_reference: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Finding":
        required = ("finding_id", "severity", "category", "title", "summary",
                    "blocking", "recommended_action")
        if any(not isinstance(value.get(key), (str, bool)) for key in required):
            raise ReviewerExecutionError("model finding is malformed")
        if value["severity"] not in SEVERITIES or value["category"] not in CATEGORIES:
            raise ReviewerExecutionError("model finding taxonomy is invalid")
        if not isinstance(value["blocking"], bool):
            raise ReviewerExecutionError("finding blocking flag is invalid")
        fields = {key: str(value.get(key) or "") for key in
                  ("path", "line_or_location", "contract_or_policy_reference")}
        return cls(*(str(value[key]) if key != "blocking" else value[key]
                     for key in required), **fields)


@dataclass(frozen=True)
class ReviewerExecutionRequest:
    schema_version: str
    repository: str
    pr_number: int
    head_sha: str
    base_branch: str
    github_issue_id: int
    canonical_issue_id: int
    agent_role: str
    reviewer_role: str
    required_review_tier: str
    capability_tier: str
    context_pack_id: str
    context_pack_version: str
    implementation_session_id: str
    review_execution_id: str
    allowed_paths: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    changed_files: tuple[str, ...]
    diff_reference: str
    required_checks: tuple[str, ...]
    safety_invariants: tuple[str, ...]
    controller_policy_version: str
    created_at: str
    integrity_hash: str

    def validate(self) -> None:
        if self.schema_version != "1.0" or not self.repository or not self.head_sha:
            raise ReviewerExecutionError("review request schema or head is invalid")
        if self.base_branch != "dev" or self.required_review_tier not in REVIEW_TIERS:
            raise ReviewerExecutionError("review request base or tier is invalid")
        if self.capability_tier not in CAPABILITY_TIERS:
            raise ReviewerExecutionError("review request capability tier is invalid")
        if not self.implementation_session_id or not self.review_execution_id:
            raise ReviewerExecutionError("review sessions are required")
        if not self.context_pack_id or not self.context_pack_version:
            raise ReviewerExecutionError("bounded context pack is required")
        if not self.allowed_paths or not self.changed_files or not self.required_checks:
            raise ReviewerExecutionError("review scope/checks are incomplete")
        if self.review_execution_id == self.implementation_session_id:
            raise ReviewerExecutionError("reviewer and implementation sessions must differ")
        rank = TIER_RANK
        minimum = {"R1": "economical-fast", "R2": "strong-coding-reasoning",
                   "R3": "premium-strongest-available"}[self.required_review_tier]
        if CAPABILITY_TIERS.index(self.capability_tier) < CAPABILITY_TIERS.index(minimum):
            raise ReviewerExecutionError("capability tier is below required tier")
        expected = request_integrity(self)
        if self.integrity_hash != expected:
            raise ReviewerExecutionError("review request integrity validation failed")


@dataclass(frozen=True)
class ReviewerExecutionResult:
    schema_version: str
    review_execution_id: str
    repository: str
    pr_number: int
    head_sha: str
    context_pack_id: str
    context_pack_version: str
    required_review_tier: str
    actual_review_tier: str
    reviewer_role: str
    disposition: str
    findings: tuple[Finding, ...]
    deterministic_check_refs: tuple[str, ...]
    provider_execution_ref: str
    provider_name: str
    model_name: str
    model_version: str
    usage: Mapping[str, Any] | None
    estimated_cost: float | None
    actual_cost: float | None
    started_at: str
    completed_at: str
    result_integrity_hash: str

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["findings"] = [asdict(item) for item in self.findings]
        return result

    def validate_against(self, request: ReviewerExecutionRequest) -> None:
        request.validate()
        if (self.schema_version != "1.0" or
                self.review_execution_id != request.review_execution_id or
                self.repository != request.repository or self.pr_number != request.pr_number or
                self.head_sha != request.head_sha or
                self.context_pack_id != request.context_pack_id or
                self.context_pack_version != request.context_pack_version or
                self.required_review_tier != request.required_review_tier or
                self.actual_review_tier not in REVIEW_TIERS or
                TIER_RANK[self.actual_review_tier] < TIER_RANK[request.required_review_tier] or
                self.disposition not in DISPOSITIONS or
                not self.provider_execution_ref or not self.provider_name or not self.model_name):
            raise ReviewerExecutionError("review result does not match the request")
        if self.disposition == "approved" and any(item.blocking for item in self.findings):
            raise ReviewerExecutionError("approved review contains a blocking finding")
        if not self.reviewer_role or detect_secret(json.dumps(self.to_dict(), sort_keys=True)):
            raise ReviewerExecutionError("review result contains unsafe or secret content")
        body = dict(self.to_dict())
        body.pop("result_integrity_hash", None)
        if self.result_integrity_hash != integrity_hash(body):
            raise ReviewerExecutionError("review result integrity validation failed")


def integrity_hash(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             default=list).encode()).hexdigest()


def request_integrity(request: ReviewerExecutionRequest) -> str:
    body = asdict(request)
    body.pop("integrity_hash", None)
    return integrity_hash(body)


def build_request(**values: Any) -> ReviewerExecutionRequest:
    values = dict(values)
    values.setdefault("schema_version", "1.0")
    values.setdefault("review_execution_id", "review-" + uuid.uuid4().hex)
    values.setdefault("created_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    for key in ("allowed_paths", "forbidden_paths", "changed_files",
                "required_checks", "safety_invariants"):
        values[key] = tuple(values.get(key, ()))
    request = ReviewerExecutionRequest(**values, integrity_hash="")
    request = ReviewerExecutionRequest(**{**asdict(request),
                                          "integrity_hash": request_integrity(request)})
    request.validate()
    return request


class IndependentReviewerAdapter:
    """Provider-neutral boundary; it has no repository or merge authority."""

    def review(self, request: ReviewerExecutionRequest) -> ReviewerExecutionResult:
        raise NotImplementedError

