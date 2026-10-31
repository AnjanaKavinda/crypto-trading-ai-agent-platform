"""Deterministic C-025v2 consumer for exact Spot research evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid5

from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.strategy.contracts import (
    QualificationStatus,
    SignalCandidate,
    VersionReference,
)
from trading_platform_api.strategy.contracts_v2 import (
    SignalEvidencePackageV2,
    SignalQualificationV2,
)
from trading_platform_api.validation.contracts_v2 import (
    QualificationGateV2,
    QualificationValidationResultV2,
    ValidationGateOutcomeV2,
    ValidationOutcomeV2,
)

_QUALIFICATION_NAMESPACE = UUID("5c7ea253-4ba5-5abf-87bc-894c405bba59")


class QualificationEngineStatus(StrEnum):
    QUALIFIED = "QUALIFIED"
    NOT_QUALIFIED = "NOT_QUALIFIED"
    INSUFFICIENT_VALIDATION = "INSUFFICIENT_VALIDATION"
    INVALID_PROVENANCE = "INVALID_PROVENANCE"
    STALE_INPUT = "STALE_INPUT"


@dataclass(frozen=True, slots=True)
class QualificationEngineResult:
    """Local evaluation; qualification is present only for qualified/rejected C-025."""

    status: QualificationEngineStatus
    reasons: tuple[str, ...]
    qualification: SignalQualificationV2 | None
    evaluated_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.status, QualificationEngineStatus):
            raise ValueError("status must be QualificationEngineStatus")
        if not isinstance(self.reasons, tuple) or any(
            not isinstance(reason, str) or not reason for reason in self.reasons
        ):
            raise ValueError("reasons must be a tuple of non-empty strings")
        if self.status is QualificationEngineStatus.QUALIFIED:
            if (
                self.qualification is None
                or self.qualification.status is not QualificationStatus.QUALIFIED
                or self.reasons
            ):
                raise ValueError("qualified status requires a clean C-025 result")
        elif self.status is QualificationEngineStatus.NOT_QUALIFIED:
            if (
                self.qualification is None
                or self.qualification.status is not QualificationStatus.REJECTED
                or not self.reasons
            ):
                raise ValueError(
                    "not-qualified status requires rejected C-025 and reasons"
                )
        elif self.qualification is not None or not self.reasons:
            raise ValueError("fail-closed result requires reasons and no C-025")
        object.__setattr__(self, "evaluated_at", _utc(self.evaluated_at))


def evaluate_signal_qualification_v2(
    *,
    candidate: SignalCandidate | None,
    evidence_package: SignalEvidencePackageV2 | None,
    validation: QualificationValidationResultV2 | None,
    evaluated_at: datetime,
) -> QualificationEngineResult:
    """Consume exact C-023/C-024v2/C-028v2 inputs without recomputing evidence."""

    at = _utc(evaluated_at)
    if candidate is None or evidence_package is None or validation is None:
        return _result(
            QualificationEngineStatus.INSUFFICIENT_VALIDATION,
            ("REQUIRED_INPUT_MISSING",),
            None,
            at,
        )
    if type(candidate) is not SignalCandidate:
        return _result(
            QualificationEngineStatus.INVALID_PROVENANCE,
            ("UNSUPPORTED_CANDIDATE_SCHEMA",),
            None,
            at,
        )
    if type(evidence_package) is not SignalEvidencePackageV2:
        return _result(
            QualificationEngineStatus.INVALID_PROVENANCE,
            ("UNSUPPORTED_EVIDENCE_PACKAGE_SCHEMA",),
            None,
            at,
        )
    if type(validation) is not QualificationValidationResultV2:
        return _result(
            QualificationEngineStatus.INVALID_PROVENANCE,
            ("UNSUPPORTED_VALIDATION_SCHEMA",),
            None,
            at,
        )

    candidate_ref = VersionReference(
        "C-023",
        candidate.candidate_id,
        candidate.schema_version,
        canonical_sha256(candidate),
    )
    package_ref = VersionReference(
        "C-024",
        evidence_package.package_id,
        evidence_package.schema_version,
        evidence_package.content_sha256,
    )
    if (
        candidate.contract_id != "C-023"
        or candidate.schema_version != "1"
        or evidence_package.contract_id != "C-024"
        or evidence_package.schema_version != "2"
        or validation.contract_id != "C-028"
        or validation.schema_version != "2"
    ):
        return _result(
            QualificationEngineStatus.INVALID_PROVENANCE,
            ("UNSUPPORTED_SCHEMA_VERSION",),
            None,
            at,
        )

    strategy_ref = evidence_package.strategy_version
    candidate_binding = (
        evidence_package.candidate == candidate_ref
        and candidate.strategy_version_id == strategy_ref.artifact_id
        and candidate.entry_concept.method == strategy_ref
        and candidate.market_context_id == evidence_package.market_context.artifact_id
        and candidate.analysis_snapshot_id
        == evidence_package.analysis_snapshot.artifact_id
        and candidate.data_quality_report_id
        == evidence_package.data_quality_report.artifact_id
        and candidate.asset == validation.asset
        and candidate.timeframe == validation.timeframe
        and validation.instrument_type == "SPOT"
        and validation.rule_set.strategy_version_id == strategy_ref.artifact_id
        and validation.methodology == validation.rule_set.methodology
        and validation.rule_set.cost_assumption_set.artifact_id
        == validation.cost_assumptions.assumption_set_id
        and validation.rule_set.cost_assumption_set.content_sha256
        == validation.cost_assumptions.content_sha256
    )
    validation_binding = (
        validation.candidate_id == candidate_ref.artifact_id
        and validation.candidate_sha256 == candidate_ref.content_sha256
        and validation.evidence_package_id == package_ref.artifact_id
        and validation.evidence_package_sha256 == package_ref.content_sha256
        and validation.strategy_version_id == strategy_ref.artifact_id
        and evidence_package.candidate.artifact_id == candidate.candidate_id
        and evidence_package.candidate.version == "1"
        and evidence_package.strategy_version.version == strategy_ref.version
        and evidence_package.strategy_version.content_sha256
        == strategy_ref.content_sha256
        and validation.rule_set.asset == candidate.asset
        and validation.rule_set.timeframe == candidate.timeframe
        and validation.rule_set.regime == validation.regime
        and validation.cost_assumptions.strategy_version_id == strategy_ref.artifact_id
        and validation.cost_assumptions.asset == candidate.asset
    )
    if not candidate_binding or not validation_binding:
        return _result(
            QualificationEngineStatus.INVALID_PROVENANCE,
            ("CANDIDATE_PACKAGE_VALIDATION_BINDING_MISMATCH",),
            None,
            at,
        )

    if len(validation.gates) != len(QualificationGateV2) or {
        gate.gate for gate in validation.gates
    } != set(QualificationGateV2):
        return _result(
            QualificationEngineStatus.INSUFFICIENT_VALIDATION,
            ("MANDATORY_GATE_SET_INCOMPLETE",),
            None,
            at,
        )

    times = (
        candidate.created_at,
        evidence_package.created_at,
        validation.created_at,
        validation.as_of,
        *(node.observed_at for node in evidence_package.graph.nodes),
    )
    if any(_utc(timestamp) > at for timestamp in times):
        return _result(
            QualificationEngineStatus.INVALID_PROVENANCE,
            ("FUTURE_DATED_INPUT",),
            None,
            at,
        )

    validity = (
        candidate.expires_at,
        evidence_package.expires_at,
        validation.valid_until,
        *(gate.valid_until for gate in validation.gates),
    )
    if any(_utc(expiry) <= at for expiry in validity):
        return _result(
            QualificationEngineStatus.STALE_INPUT,
            ("UPSTREAM_EVIDENCE_EXPIRED",),
            None,
            at,
        )

    failed = tuple(
        gate.gate.value
        for gate in validation.gates
        if gate.outcome is ValidationGateOutcomeV2.FAIL
    )
    if validation.outcome is ValidationOutcomeV2.FAIL:
        if not failed:
            return _result(
                QualificationEngineStatus.INSUFFICIENT_VALIDATION,
                ("FAIL_WITHOUT_FAILED_GATE",),
                None,
                at,
            )
        return _qualified_record(
            QualificationEngineStatus.NOT_QUALIFIED,
            ("AUTHORITATIVE_VALIDATION_FAILED", *failed),
            candidate_ref,
            strategy_ref,
            package_ref,
            evidence_package,
            validation,
            candidate.expires_at,
            at,
            QualificationStatus.REJECTED,
        )
    if validation.outcome is ValidationOutcomeV2.INSUFFICIENT_VALIDATION:
        return _result(
            QualificationEngineStatus.INSUFFICIENT_VALIDATION,
            ("AUTHORITATIVE_VALIDATION_INSUFFICIENT",),
            None,
            at,
        )
    if validation.outcome is not ValidationOutcomeV2.PASS or any(
        gate.outcome is not ValidationGateOutcomeV2.PASS for gate in validation.gates
    ):
        return _result(
            QualificationEngineStatus.INSUFFICIENT_VALIDATION,
            ("MANDATORY_GATE_NOT_PASSED",),
            None,
            at,
        )
    return _qualified_record(
        QualificationEngineStatus.QUALIFIED,
        (),
        candidate_ref,
        strategy_ref,
        package_ref,
        evidence_package,
        validation,
        candidate.expires_at,
        at,
        QualificationStatus.QUALIFIED,
    )


def _qualified_record(
    status: QualificationEngineStatus,
    reasons: tuple[str, ...],
    candidate: VersionReference,
    strategy: VersionReference,
    package_ref: VersionReference,
    package: SignalEvidencePackageV2,
    validation: QualificationValidationResultV2,
    candidate_valid_until: datetime,
    at: datetime,
    qualification_status: QualificationStatus,
) -> QualificationEngineResult:
    expires_at = min(
        _utc(candidate_valid_until),
        _utc(package.expires_at),
        _utc(validation.valid_until),
    )
    identity = canonical_sha256(
        {
            "candidate": candidate,
            "strategy_version": strategy,
            "evidence_package": package_ref,
            "validation": {
                "result_id": validation.result_id,
                "content_sha256": validation.content_sha256,
            },
            "evaluated_at": at,
            "expires_at": expires_at,
            "status": qualification_status.value,
        }
    )
    qualification = SignalQualificationV2(
        qualification_id=uuid5(_QUALIFICATION_NAMESPACE, identity),
        candidate=candidate,
        strategy_version=strategy,
        evidence_package=package_ref,
        evidence_package_valid_until=package.expires_at,
        validation=validation,
        status=qualification_status,
        evaluated_at=at,
        expires_at=expires_at,
    )
    return _result(status, reasons, qualification, at)


def _result(
    status: QualificationEngineStatus,
    reasons: tuple[str, ...],
    qualification: SignalQualificationV2 | None,
    evaluated_at: datetime,
) -> QualificationEngineResult:
    return QualificationEngineResult(status, reasons, qualification, evaluated_at)


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("qualification timestamps must be timezone-aware")
    return value.astimezone(UTC)


__all__ = [
    "QualificationEngineResult",
    "QualificationEngineStatus",
    "evaluate_signal_qualification_v2",
]
