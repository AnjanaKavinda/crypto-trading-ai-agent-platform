"""Immutable observation-only C-106 validation freshness assessment."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid5

from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.validation.contracts_v2 import (
    QualificationGateResultV2,
    QualificationGateV2,
    QualificationValidationResultV2,
    ValidationArtifactReferenceV2,
    ValidationOutcomeV2,
)

_NAMESPACE = UUID("5b51253e-ffdb-5d1b-a878-75d19797b530")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_IDENTITY_NAMES = (
    "candidate",
    "strategy_version",
    "evidence_package",
    "data_quality_report",
    "dataset",
    "cost_assumptions",
    "methodology",
    "rule_set",
    "market_context",
    "asset",
    "instrument_type",
    "timeframe",
    "regime",
    "regime_validation",
    "code_build",
)
_IdentityValue = ValidationArtifactReferenceV2 | str


class FreshnessContractError(ValueError):
    """Malformed or internally inconsistent C-106 observation."""


class ValidationFreshnessStateV1(StrEnum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    EXPIRED = "EXPIRED"
    INCONCLUSIVE = "INCONCLUSIVE"


class PerformanceDecayStateV1(StrEnum):
    NOT_ASSESSED = "NOT_ASSESSED"


class GovernanceReviewStateV1(StrEnum):
    CURRENT_FOR_GOVERNANCE_REVIEW = "CURRENT_FOR_GOVERNANCE_REVIEW"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"


def _time(name: str, value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise FreshnessContractError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


def _reference(
    name: str,
    value: object,
    contract_id: str | None = None,
) -> ValidationArtifactReferenceV2:
    if type(value) is not ValidationArtifactReferenceV2 or (
        contract_id is not None and value.artifact_type != contract_id
    ):
        raise FreshnessContractError(f"{name} is not the required typed reference.")
    return value


@dataclass(frozen=True, slots=True)
class ValidationFreshnessSnapshotV1:
    """Explicit point-in-time references; absent identities remain absent."""

    candidate: ValidationArtifactReferenceV2 | None
    strategy_version: ValidationArtifactReferenceV2 | None
    evidence_package: ValidationArtifactReferenceV2 | None
    data_quality_report: ValidationArtifactReferenceV2 | None
    dataset: ValidationArtifactReferenceV2 | None
    cost_assumptions: ValidationArtifactReferenceV2 | None
    methodology: ValidationArtifactReferenceV2 | None
    rule_set: ValidationArtifactReferenceV2 | None
    market_context: ValidationArtifactReferenceV2 | None
    asset: str | None
    instrument_type: str | None
    timeframe: str | None
    regime: str | None
    regime_validation: ValidationArtifactReferenceV2 | None
    code_build: ValidationArtifactReferenceV2 | None
    observed_at: datetime

    def __post_init__(self) -> None:
        contracts = {
            "candidate": "C-023",
            "strategy_version": "C-021",
            "evidence_package": "C-024",
            "data_quality_report": "C-003",
            "dataset": "C-092",
            "cost_assumptions": "C-027",
            "rule_set": "C-025-RULESET",
            "market_context": "C-006",
            "regime_validation": "C-074",
        }
        for name, contract_id in contracts.items():
            value = getattr(self, name)
            if value is not None:
                _reference(name, value, contract_id)
        if self.methodology is not None:
            _reference("methodology", self.methodology)
        for name in ("asset", "instrument_type", "timeframe", "regime"):
            value = getattr(self, name)
            if value is not None and (
                type(value) is not str or not value.strip() or value != value.strip()
            ):
                raise FreshnessContractError(
                    f"{name} must be a non-blank trimmed string when supplied."
                )
        if self.code_build is not None:
            _reference("code_build", self.code_build, "CODE_BUILD")
        object.__setattr__(self, "observed_at", _time("observed_at", self.observed_at))


@dataclass(frozen=True, slots=True)
class FreshnessIdentityComparisonV1:
    identity: str
    original: _IdentityValue | None
    current: _IdentityValue | None
    matches: bool | None

    def __post_init__(self) -> None:
        if type(self.identity) is not str or not self.identity.strip():
            raise FreshnessContractError("identity must be non-blank.")
        for name, value in (("original", self.original), ("current", self.current)):
            if isinstance(value, ValidationArtifactReferenceV2):
                _reference(name, value)
            elif value is not None and (
                type(value) is not str or not value.strip() or value != value.strip()
            ):
                raise FreshnessContractError(
                    f"{name} must be a typed reference or non-blank scope value."
                )
        expected = (
            None
            if self.original is None or self.current is None
            else self.original == self.current
        )
        if self.matches is not expected:
            raise FreshnessContractError("identity comparison is inconsistent.")


@dataclass(frozen=True, slots=True)
class ValidationFreshnessAssessmentV1:
    """Deterministic C-106 report; never changes the supplied C-028 outcome."""

    assessment_id: UUID
    validation_result_id: UUID
    validation_schema_version: str
    validation_result_sha256: str
    evidence_package_id: UUID
    evidence_package_schema_version: str
    evidence_package_sha256: str
    current_snapshot_sha256: str
    current_snapshot_observed_at: datetime
    as_of: datetime
    freshness: ValidationFreshnessStateV1
    original_validation_outcome: ValidationOutcomeV2
    original_gates: tuple[QualificationGateResultV2, ...]
    governance_review_state: GovernanceReviewStateV1
    identity_comparisons: tuple[FreshnessIdentityComparisonV1, ...]
    reasons: tuple[str, ...]
    declared_expiries: tuple[datetime, ...]
    expires_at: datetime | None
    performance_decay: PerformanceDecayStateV1
    performance_decay_reason: str
    qualification_changed: bool
    production_eligibility: bool
    approval_granted: bool
    activation_granted: bool
    readiness_granted: bool
    content_sha256: str
    contract_id: str = field(default="C-106", init=False)
    schema_version: str = field(default="1", init=False)

    def __post_init__(self) -> None:
        if type(self.assessment_id) is not UUID:
            raise FreshnessContractError("assessment_id must be a UUID.")
        if type(self.validation_result_id) is not UUID:
            raise FreshnessContractError("validation_result_id must be a UUID.")
        if type(self.evidence_package_id) is not UUID:
            raise FreshnessContractError("evidence_package_id must be a UUID.")
        if (
            self.validation_schema_version != "2"
            or self.evidence_package_schema_version != "2"
        ):
            raise FreshnessContractError("C-106 schema 1 requires C-028v2/C-024v2.")
        for name in (
            "validation_result_sha256",
            "evidence_package_sha256",
            "current_snapshot_sha256",
            "content_sha256",
        ):
            value = getattr(self, name)
            if type(value) is not str or _SHA256.fullmatch(value) is None:
                raise FreshnessContractError(f"{name} must be lowercase SHA-256.")
        object.__setattr__(self, "as_of", _time("as_of", self.as_of))
        object.__setattr__(
            self,
            "current_snapshot_observed_at",
            _time("current_snapshot_observed_at", self.current_snapshot_observed_at),
        )
        if self.current_snapshot_observed_at > self.as_of:
            raise FreshnessContractError(
                "current snapshot is later than explicit as_of."
            )
        if not isinstance(self.freshness, ValidationFreshnessStateV1):
            raise FreshnessContractError("freshness state is unsupported.")
        if not isinstance(self.original_validation_outcome, ValidationOutcomeV2):
            raise FreshnessContractError("original validation outcome is unsupported.")
        if (
            type(self.original_gates) is not tuple
            or any(
                type(item) is not QualificationGateResultV2
                for item in self.original_gates
            )
            or {item.gate for item in self.original_gates} != set(QualificationGateV2)
            or len(self.original_gates) != len(QualificationGateV2)
        ):
            raise FreshnessContractError(
                "original gate evidence must preserve every typed gate exactly once."
            )
        if not isinstance(self.governance_review_state, GovernanceReviewStateV1):
            raise FreshnessContractError("governance review state is unsupported.")
        if not isinstance(self.performance_decay, PerformanceDecayStateV1):
            raise FreshnessContractError("performance decay state is unsupported.")
        if (
            type(self.identity_comparisons) is not tuple
            or any(
                type(item) is not FreshnessIdentityComparisonV1
                for item in self.identity_comparisons
            )
            or tuple(item.identity for item in self.identity_comparisons)
            != _IDENTITY_NAMES
        ):
            raise FreshnessContractError(
                "identity comparisons must contain the complete ordered identity set."
            )
        if (
            type(self.reasons) is not tuple
            or any(type(item) is not str or not item.strip() for item in self.reasons)
            or len(set(self.reasons)) != len(self.reasons)
        ):
            raise FreshnessContractError("reasons must be unique non-blank values.")
        if (
            self.freshness is not ValidationFreshnessStateV1.CURRENT
            and not self.reasons
        ):
            raise FreshnessContractError(
                "non-current freshness requires an explicit reason."
            )
        if type(self.declared_expiries) is not tuple or any(
            type(item) is not datetime for item in self.declared_expiries
        ):
            raise FreshnessContractError("declared_expiries must be a typed tuple.")
        expiries = tuple(
            _time("declared_expiry", item) for item in self.declared_expiries
        )
        if expiries != tuple(sorted(set(expiries))):
            raise FreshnessContractError(
                "declared expiries must be ordered and unique."
            )
        if not expiries:
            raise FreshnessContractError("declared expiries must not be empty.")
        object.__setattr__(self, "declared_expiries", expiries)
        if self.expires_at is not None:
            object.__setattr__(self, "expires_at", _time("expires_at", self.expires_at))
        if self.expires_at != min(expiries):
            raise FreshnessContractError(
                "expires_at must be the earliest declared expiry."
            )
        if self.performance_decay_reason != "ROLLING_PERFORMANCE_DECAY_NOT_ASSESSED":
            raise FreshnessContractError(
                "performance decay reason is fixed in schema 1."
            )
        for name in (
            "qualification_changed",
            "production_eligibility",
            "approval_granted",
            "activation_granted",
            "readiness_granted",
        ):
            if type(getattr(self, name)) is not bool:
                raise FreshnessContractError(f"{name} must be a bool.")
        if (
            self.qualification_changed
            or self.production_eligibility
            or self.approval_granted
            or self.activation_granted
            or self.readiness_granted
        ):
            raise FreshnessContractError("C-106 cannot grant downstream authority.")
        eligible = (
            self.original_validation_outcome is ValidationOutcomeV2.PASS
            and self.freshness is ValidationFreshnessStateV1.CURRENT
        )
        comparisons = tuple(item.matches for item in self.identity_comparisons)
        if self.freshness is ValidationFreshnessStateV1.INCONCLUSIVE and (
            None not in comparisons
        ):
            raise FreshnessContractError("INCONCLUSIVE requires unavailable identity.")
        if self.freshness is ValidationFreshnessStateV1.STALE and (
            None in comparisons or False not in comparisons
        ):
            raise FreshnessContractError(
                "STALE requires comparable mismatched identity."
            )
        if self.freshness is ValidationFreshnessStateV1.EXPIRED and (
            None in comparisons
            or False in comparisons
            or self.expires_at is None
            or self.expires_at > self.as_of
        ):
            raise FreshnessContractError(
                "EXPIRED requires matching evidence at expiry."
            )
        if self.freshness is ValidationFreshnessStateV1.CURRENT and (
            any(item is not True for item in comparisons)
            or self.expires_at is None
            or self.expires_at <= self.as_of
        ):
            raise FreshnessContractError(
                "CURRENT requires matching unexpired evidence."
            )
        if (
            self.governance_review_state
            is GovernanceReviewStateV1.CURRENT_FOR_GOVERNANCE_REVIEW
        ) != eligible:
            raise FreshnessContractError(
                "governance review projection is inconsistent."
            )
        digest = canonical_sha256(_assessment_payload(self))
        expected_id = uuid5(_NAMESPACE, digest)
        if self.content_sha256 != digest or self.assessment_id != expected_id:
            raise FreshnessContractError("C-106 identity/digest is not deterministic.")

    @classmethod
    def build(cls, **values: object) -> ValidationFreshnessAssessmentV1:
        values.pop("assessment_id", None)
        values.pop("content_sha256", None)
        provisional = object.__new__(cls)
        for item in fields(cls):
            if item.name in {"assessment_id", "content_sha256"}:
                continue
            value = (
                "C-106"
                if item.name == "contract_id"
                else "1"
                if item.name == "schema_version"
                else values[item.name]
            )
            object.__setattr__(provisional, item.name, value)
        digest = canonical_sha256(_assessment_payload(provisional))
        return cls(
            assessment_id=uuid5(_NAMESPACE, digest),
            content_sha256=digest,
            **values,  # type: ignore[arg-type]
        )


def _assessment_payload(value: ValidationFreshnessAssessmentV1) -> dict[str, object]:
    return {
        item.name: getattr(value, item.name)
        for item in fields(value)
        if item.name not in {"assessment_id", "content_sha256"}
    }


def validation_result_digest(value: QualificationValidationResultV2) -> str:
    """Recompute C-028v2 content digest, rather than trusting its supplied hash."""
    return canonical_sha256(
        {
            item.name: getattr(value, item.name)
            for item in fields(value)
            if item.name != "content_sha256"
        }
    )


def evidence_package_digest(value: object) -> str:
    """Recompute the exact C-024v2 digest from the immutable package payload."""
    return canonical_sha256(
        {
            item.name: getattr(value, item.name)
            for item in fields(value)  # type: ignore[arg-type]
            if item.name not in {"package_id", "content_sha256"}
        }
    )


__all__ = [
    "FreshnessContractError",
    "FreshnessIdentityComparisonV1",
    "GovernanceReviewStateV1",
    "PerformanceDecayStateV1",
    "ValidationFreshnessAssessmentV1",
    "ValidationFreshnessSnapshotV1",
    "ValidationFreshnessStateV1",
    "evidence_package_digest",
    "validation_result_digest",
]
