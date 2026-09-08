"""Vendor-neutral, fail-closed independent reviewer execution contract."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import fnmatch
import hmac
import json
import re
import time
import uuid
from pathlib import PurePosixPath
from typing import Any, Callable, Mapping

from orchestrator import (CAPABILITY_TIERS, GovernanceError, REVIEW_TIERS,
                          detect_high_confidence_secret_material)

DISPOSITIONS = ("approved", "changes-requested", "blocked")
SEVERITIES = ("info", "low", "medium", "high", "critical")
CATEGORIES = (
    "architecture", "security", "governance", "correctness", "testing",
    "statistical", "risk", "execution", "maintainability", "scope", "other",
)
TIER_RANK = {tier: index for index, tier in enumerate(REVIEW_TIERS)}


def _normalized_repo_path(value: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value:
        raise ReviewerExecutionError("review scope contains an invalid repository path")
    parts = PurePosixPath(value).parts
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise ReviewerExecutionError("review scope contains an unsafe repository path")
    return str(PurePosixPath(value))


def _normalized_pattern(value: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value:
        raise ReviewerExecutionError("review scope contains an invalid path pattern")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ReviewerExecutionError("review scope contains an unsafe path pattern")
    return value


def _matches_pattern(path: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(path, pattern)


def validate_changed_path_scope(changed_files: tuple[str, ...],
                                allowed_paths: tuple[str, ...],
                                forbidden_paths: tuple[str, ...]) -> None:
    normalized_changed = tuple(_normalized_repo_path(path) for path in changed_files)
    normalized_allowed = tuple(_normalized_pattern(pattern) for pattern in allowed_paths)
    normalized_forbidden = tuple(_normalized_pattern(pattern) for pattern in forbidden_paths)
    for path in normalized_changed:
        if any(_matches_pattern(path, pattern) for pattern in normalized_forbidden):
            raise ReviewerExecutionError(f"changed path is forbidden by review policy: {path}")
        if not any(_matches_pattern(path, pattern) for pattern in normalized_allowed):
            raise ReviewerExecutionError(f"changed path is outside governed review scope: {path}")


def extract_allowed_paths_from_issue(issue_body: str) -> tuple[str, ...]:
    """Derive one bounded, unambiguous path section from trusted issue Markdown.

    Markdown headings are syntax, not data.  A path list therefore ends at the
    next heading of the same or higher level (or any heading for an unprefixed
    marker), and malformed bullet entries are rejected rather than ignored.
    """
    body = issue_body or ""
    heading_re = re.compile(r"^( {0,3})(#{1,6})[ \t]+(.+?)\s*#*\s*$")
    markers: list[tuple[int, int]] = []
    lines = body.splitlines()
    for index, line in enumerate(lines):
        heading = heading_re.match(line)
        if heading and heading.group(3).strip().casefold() in {
                "allowed paths", "expected paths"}:
            markers.append((index, len(heading.group(2))))
            continue
        if re.match(r"^\s*(?:Allowed paths|Expected paths)"
                    r"(?:\s*\([^:\n]*\))?\s*:\s*$", line, re.I):
            markers.append((index, 0))
    if len(markers) != 1:
        raise ReviewerExecutionError(
            "linked issue governed review paths are absent or ambiguous")
    marker_line, level = markers[0]
    end = len(lines)
    for index in range(marker_line + 1, len(lines)):
        heading = heading_re.match(lines[index])
        if heading and (level == 0 or len(heading.group(2)) <= level):
            end = index
            break
    paths = []
    for line in lines[marker_line + 1:end]:
        if not line.strip():
            continue
        bullet = re.match(r"^\s*[-*+]\s+(.*)$", line)
        if not bullet:
            continue
        match = re.fullmatch(r"`([^`]+)`", bullet.group(1).strip())
        if not match:
            raise ReviewerExecutionError(
                "linked issue governed review paths contain an unsafe or ambiguous entry")
        candidate = match.group(1).strip()
        normalized = _normalized_pattern(candidate)
        if normalized not in paths:
            paths.append(normalized)
        if (candidate.endswith("/test_orchestrator.py") and
                "narrowly scoped new tests" in line.lower()):
            test_pattern = candidate.rsplit("/", 1)[0] + "/test_*.py"
            if test_pattern not in paths:
                paths.append(_normalized_pattern(test_pattern))
    if not paths:
        raise ReviewerExecutionError("linked issue governed review paths are empty")
    return tuple(paths)


def assert_current_head(expected_head: str, actual_head: str) -> None:
    if not expected_head or not actual_head or expected_head != actual_head:
        raise ReviewerExecutionError("PR head changed during independent review execution")


def request_from_mapping(raw: Mapping[str, Any]) -> "ReviewerExecutionRequest":
    return ReviewerExecutionRequest(
        **{**raw, "allowed_paths": tuple(raw["allowed_paths"]),
           "forbidden_paths": tuple(raw["forbidden_paths"]),
           "changed_files": tuple(raw["changed_files"]),
           "required_checks": tuple(raw["required_checks"]),
           "safety_invariants": tuple(raw["safety_invariants"])})


def _handoff_payload(request: "ReviewerExecutionRequest",
                     result: "ReviewerExecutionResult") -> dict[str, str]:
    return {
        "request_integrity_hash": request.integrity_hash,
        "diff_reference": request.diff_reference,
        "review_execution_id": result.review_execution_id,
        "result_integrity_hash": result.result_integrity_hash,
        "provider_execution_ref": result.provider_execution_ref,
    }


def sign_execution_handoff(request: "ReviewerExecutionRequest",
                           result: "ReviewerExecutionResult", secret: str) -> dict[str, str]:
    if not secret:
        raise ReviewerExecutionError("review result handoff signing secret is unavailable")
    body = _handoff_payload(request, result)
    derived = hmac.new(secret.encode("utf-8"), b"independent-review-handoff-v1",
                       sha256).digest()
    signature = hmac.new(
        derived,
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        sha256,
    ).hexdigest()
    return {**body, "signature": signature}


def verify_execution_handoff(request: "ReviewerExecutionRequest",
                             result: "ReviewerExecutionResult",
                             handoff: Mapping[str, Any], secret: str) -> None:
    expected = sign_execution_handoff(request, result, secret)
    if not isinstance(handoff, Mapping):
        raise ReviewerExecutionError("review result handoff attestation is malformed")
    if set(handoff) != set(expected):
        raise ReviewerExecutionError("review result handoff attestation is incomplete")
    for key, value in expected.items():
        actual = str(handoff.get(key) or "")
        if key == "signature":
            if not hmac.compare_digest(actual, value):
                raise ReviewerExecutionError("review result handoff attestation is invalid")
        elif actual != value:
            raise ReviewerExecutionError("review result handoff is not bound to the original request")


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
                    "blocking", "recommended_action", "path", "line_or_location",
                    "contract_or_policy_reference")
        if set(value) != set(required):
            raise ReviewerExecutionError("model finding does not match strict schema")
        string_fields = tuple(key for key in required if key != "blocking")
        if any(not isinstance(value[key], str) for key in string_fields):
            raise ReviewerExecutionError("model finding string fields are malformed")
        if not isinstance(value["blocking"], bool):
            raise ReviewerExecutionError("finding blocking flag is invalid")
        if value["severity"] not in SEVERITIES or value["category"] not in CATEGORIES:
            raise ReviewerExecutionError("model finding taxonomy is invalid")
        if any(not value[key].strip() for key in
               ("finding_id", "severity", "category", "title", "summary",
                "recommended_action")):
            raise ReviewerExecutionError("model finding required text is empty")
        return cls(
            finding_id=value["finding_id"], severity=value["severity"],
            category=value["category"], title=value["title"], summary=value["summary"],
            blocking=value["blocking"], recommended_action=value["recommended_action"],
            path=value["path"], line_or_location=value["line_or_location"],
            contract_or_policy_reference=value["contract_or_policy_reference"])


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
        validate_changed_path_scope(self.changed_files, self.allowed_paths, self.forbidden_paths)
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
        if (not self.reviewer_role or
                detect_high_confidence_secret_material(json.dumps(self.to_dict(), sort_keys=True))):
            raise ReviewerExecutionError("review result contains credential material")
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
