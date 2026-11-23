"""ADR-0030 C-028v3 envelope. Construction is not verified result issuance."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import NAMESPACE_URL, UUID, uuid5

from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.strategy.contracts import SignalCandidate
from trading_platform_api.strategy.contracts_v2 import SignalEvidencePackageV2
from trading_platform_api.validation.contracts import ValidationContractError
from trading_platform_api.validation.contracts_v2 import ValidationArtifactReferenceV2
from trading_platform_api.validation.contracts_v3 import _digest
from trading_platform_api.validation.qualification_study_v3 import (
    QualificationExpectancyUnitV3,
    QualificationStudyProtocolV3,
    _decimal,
    _ratio,
    _ref,
    _text,
    _time,
)

_NAMESPACE = uuid5(
    NAMESPACE_URL, "trading-platform:C-028:3:qualification-result-identity-v1"
)


class QualificationGateV3(StrEnum):
    DATA_INTEGRITY = "DATA_INTEGRITY"
    POINT_IN_TIME = "POINT_IN_TIME"
    THRESHOLD = "THRESHOLD"
    SAMPLE_SUFFICIENCY = "SAMPLE_SUFFICIENCY"
    STATISTICAL_SUPPORT = "STATISTICAL_SUPPORT"
    EXPECTANCY_AFTER_COSTS = "EXPECTANCY_AFTER_COSTS"
    COST_APPLICABILITY = "COST_APPLICABILITY"
    OOS = "OOS"
    WALK_FORWARD = "WALK_FORWARD"
    ROBUSTNESS = "ROBUSTNESS"
    BIAS_LEAKAGE = "BIAS_LEAKAGE"
    RISK = "RISK"
    REGIME_APPLICABILITY = "REGIME_APPLICABILITY"
    RESEARCH_SELECTION = "RESEARCH_SELECTION"
    CALIBRATION = "CALIBRATION"


class QualificationOutcomeV3(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INSUFFICIENT_VALIDATION = "INSUFFICIENT_VALIDATION"


# These are inputs to a future issuer, never direct authoritative PASS sources.
_SOURCE_VERSIONS = {
    QualificationGateV3.DATA_INTEGRITY: {("C-003", "2"), ("C-027", "3")},
    QualificationGateV3.POINT_IN_TIME: {("C-027", "3")},
    QualificationGateV3.THRESHOLD: {("C-027", "3"), ("C-071", "2"), ("C-029", "2")},
    QualificationGateV3.SAMPLE_SUFFICIENCY: {
        ("C-027", "3"),
        ("C-071", "2"),
        ("C-029", "2"),
    },
    QualificationGateV3.STATISTICAL_SUPPORT: {
        ("C-072", "2"),
        ("C-071", "2"),
        ("C-029", "2"),
    },
    QualificationGateV3.EXPECTANCY_AFTER_COSTS: {
        ("C-027", "3"),
        ("C-071", "2"),
        ("C-029", "2"),
    },
    QualificationGateV3.COST_APPLICABILITY: {("C-027", "2"), ("C-027", "3")},
    QualificationGateV3.OOS: {("C-071", "2")},
    QualificationGateV3.WALK_FORWARD: {("C-029", "2")},
    QualificationGateV3.ROBUSTNESS: {("C-072", "2"), ("C-073", "2")},
    QualificationGateV3.BIAS_LEAKAGE: {("C-094", "2")},
    QualificationGateV3.RISK: {("C-027", "3"), ("C-072", "2")},
    QualificationGateV3.REGIME_APPLICABILITY: {("C-074", "2")},
    QualificationGateV3.RESEARCH_SELECTION: {("C-105", "1")},
    QualificationGateV3.CALIBRATION: {("C-031", "1")},
}


def _references(name: str, values: object, *, empty: bool = False) -> None:
    if type(values) is not tuple or len(values) > 32 or (not values and not empty):
        raise ValidationContractError(f"{name} requires bounded immutable references.")
    if any(type(x) is not ValidationArtifactReferenceV2 for x in values):
        raise ValidationContractError(f"{name} requires typed references.")
    keys = [
        (x.artifact_type, str(x.artifact_id), x.version, x.content_sha256)
        for x in values
    ]
    if len(keys) != len({key[:3] for key in keys}) or keys != sorted(keys):
        raise ValidationContractError(f"{name} requires unique canonical ordering.")


@dataclass(frozen=True, slots=True)
class QualificationGateResultV3:
    gate: QualificationGateV3
    outcome: QualificationOutcomeV3
    sources: tuple[ValidationArtifactReferenceV2, ...]
    methods: tuple[ValidationArtifactReferenceV2, ...]
    criterion: str
    reasons: tuple[str, ...]
    as_of: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        if (
            type(self.gate) is not QualificationGateV3
            or type(self.outcome) is not QualificationOutcomeV3
        ):
            raise ValidationContractError("typed gate and terminal outcome required.")
        _references(
            "sources",
            self.sources,
            empty=self.outcome is QualificationOutcomeV3.INSUFFICIENT_VALIDATION,
        )
        _references("methods", self.methods)
        if any(
            (x.artifact_type, x.version) not in _SOURCE_VERSIONS[self.gate]
            for x in self.sources
        ):
            raise ValidationContractError("unsupported gate source identity/version.")
        _text("criterion", self.criterion)
        if type(self.reasons) is not tuple or not 1 <= len(self.reasons) <= 16:
            raise ValidationContractError("explicit bounded gate reasons required.")
        for reason in self.reasons:
            _text("reason", reason)
        if len(set(self.reasons)) != len(self.reasons):
            raise ValidationContractError("duplicate gate reasons.")
        for name in ("as_of", "valid_until"):
            object.__setattr__(self, name, _time(name, getattr(self, name)))
        if self.as_of >= self.valid_until:
            raise ValidationContractError("gate validity must be nonempty.")


@dataclass(frozen=True, slots=True)
class QualificationUncertaintyV3:
    lower_bound: Decimal
    upper_bound: Decimal
    confidence_level: Decimal
    effective_sample_size: Decimal
    method: ValidationArtifactReferenceV2
    dependence_policy: ValidationArtifactReferenceV2
    source: ValidationArtifactReferenceV2
    metric_name: str = field(default="conditional_win_rate", init=False)
    unit: str = field(default="FRACTION", init=False)

    def __post_init__(self) -> None:
        _ratio("lower_bound", self.lower_bound)
        _ratio("upper_bound", self.upper_bound)
        _ratio("confidence_level", self.confidence_level, interior=True)
        if self.lower_bound > self.upper_bound:
            raise ValidationContractError("uncertainty interval is inverted.")
        _decimal("effective_sample_size", self.effective_sample_size, positive=True)
        _ref("method", self.method, "STATISTICAL_METHOD")
        _ref("dependence_policy", self.dependence_policy, "DEPENDENCE_POLICY")
        _references("uncertainty source", (self.source,))
        if (self.source.artifact_type, self.source.version) not in _SOURCE_VERSIONS[
            QualificationGateV3.STATISTICAL_SUPPORT
        ]:
            raise ValidationContractError("unsupported uncertainty source.")


def gate_methods(
    protocol: QualificationStudyProtocolV3, gate: QualificationGateV3
) -> tuple[ValidationArtifactReferenceV2, ...]:
    """Exact protocol method pins required in each output gate envelope."""
    p = protocol.policy
    methods = {
        QualificationGateV3.SAMPLE_SUFFICIENCY: (p.sample_method, p.dependence_policy),
        QualificationGateV3.STATISTICAL_SUPPORT: (
            p.uncertainty_method,
            p.statistical_support_rule,
            p.dependence_policy,
        ),
        QualificationGateV3.EXPECTANCY_AFTER_COSTS: (
            protocol.methodology,
            p.return_basis,
        ),
        QualificationGateV3.ROBUSTNESS: (p.robustness_policy,),
        QualificationGateV3.RISK: (p.historical_risk_policy,),
        QualificationGateV3.RESEARCH_SELECTION: (p.selection_policy,),
        QualificationGateV3.CALIBRATION: (p.statistical_support_rule,),
    }.get(gate, (protocol.methodology,))
    return tuple(
        sorted(
            methods,
            key=lambda x: (
                x.artifact_type,
                str(x.artifact_id),
                x.version,
                x.content_sha256,
            ),
        )
    )


def _aggregate(gates: object) -> QualificationOutcomeV3:
    if (
        type(gates) is not tuple
        or not gates
        or any(type(x) is not QualificationGateResultV3 for x in gates)
    ):
        raise ValidationContractError("typed immutable gate results required.")
    for gate in gates:
        gate.__post_init__()
    states = {x.outcome for x in gates}
    return (
        QualificationOutcomeV3.FAIL
        if QualificationOutcomeV3.FAIL in states
        else QualificationOutcomeV3.INSUFFICIENT_VALIDATION
        if QualificationOutcomeV3.INSUFFICIENT_VALIDATION in states
        else QualificationOutcomeV3.PASS
    )


@dataclass(frozen=True, slots=True)
class QualificationValidationResultV3:
    """C-028v3 structural output, requiring later verified source/journal issuance.

    A structurally coherent PASS is not source authentication or a C-025
    qualification. Existing authoritative readers deliberately reject this type.
    """

    result_id: UUID
    protocol: QualificationStudyProtocolV3
    candidate: SignalCandidate
    evidence_package: SignalEvidencePackageV2
    freeze_receipt: ValidationArtifactReferenceV2
    research_journal: ValidationArtifactReferenceV2
    first_holdout_access_at: datetime
    sample_size: int | None
    effective_sample_size: Decimal | None
    observed_conditional_win_rate: Decimal | None
    after_cost_expectancy: Decimal | None
    expectancy_unit: QualificationExpectancyUnitV3 | None
    expectancy_quote_currency: str | None
    maximum_drawdown_fraction: Decimal | None
    uncertainty: QualificationUncertaintyV3 | None
    gates: tuple[QualificationGateResultV3, ...]
    as_of: datetime
    created_at: datetime
    valid_until: datetime
    content_sha256: str
    outcome: QualificationOutcomeV3 = field(init=False)
    contract_id: str = field(default="C-028", init=False)
    schema_version: str = field(default="3", init=False)
    identity_method: str = field(default="qualification-result-identity-v1", init=False)
    qualification_authorized: bool = field(default=False, init=False)
    approval_authorized: bool = field(default=False, init=False)
    execution_authorized: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if (
            type(self.result_id) is not UUID
            or type(self.protocol) is not QualificationStudyProtocolV3
            or type(self.candidate) is not SignalCandidate
            or type(self.evidence_package) is not SignalEvidencePackageV2
        ):
            raise ValidationContractError("exact typed result sources required.")
        p, c, e = self.protocol, self.candidate, self.evidence_package
        p.__post_init__()
        c.__post_init__()
        e.__post_init__()
        if (
            e.candidate.artifact_id != c.candidate_id
            or e.candidate.version != c.schema_version
            or e.candidate.content_sha256 != canonical_sha256(c)
            or e.strategy_version.artifact_id != c.strategy_version_id
            or e.strategy_version.artifact_id != p.strategy_version.artifact_id
            or e.strategy_version.version != p.strategy_semantic_version
            or e.strategy_version.content_sha256 != p.strategy_version.content_sha256
            or (c.asset, c.instrument_id, c.timeframe)
            != (p.asset, p.instrument_id, p.timeframe)
            or (
                e.eligibility.artifact_id,
                e.market_context.artifact_id,
                e.analysis_snapshot.artifact_id,
                e.data_quality_report.artifact_id,
            )
            != (
                c.eligibility_id,
                c.market_context_id,
                c.analysis_snapshot_id,
                c.data_quality_report_id,
            )
        ):
            raise ValidationContractError("CANDIDATE_PACKAGE_STUDY_BINDING_MISMATCH")
        _ref("freeze_receipt", self.freeze_receipt, "QUALIFICATION_STUDY_FREEZE", "1")
        _ref(
            "research_journal",
            self.research_journal,
            "QUALIFICATION_RESEARCH_JOURNAL",
            "1",
        )
        outcome = _aggregate(self.gates)
        object.__setattr__(self, "outcome", outcome)
        expected = set(QualificationGateV3)
        if not p.policy.calibration_required:
            expected.remove(QualificationGateV3.CALIBRATION)
        actual = tuple(x.gate for x in self.gates)
        if (
            set(actual) != expected
            or len(actual) != len(expected)
            or actual != tuple(sorted(actual, key=lambda x: x.value))
        ):
            raise ValidationContractError(
                "exact mandatory gates in canonical order required."
            )
        for gate in self.gates:
            for source in gate.sources:
                if source.artifact_type == "C-003" and (
                    source.artifact_id,
                    source.version,
                    source.content_sha256,
                ) != (
                    e.data_quality_report.artifact_id,
                    e.data_quality_report.version,
                    e.data_quality_report.content_sha256,
                ):
                    raise ValidationContractError(
                        "DATA_QUALITY_SOURCE_PACKAGE_MISMATCH"
                    )
                if (source.artifact_type, source.version) == (
                    "C-027",
                    "2",
                ) and source != p.cost_assumptions:
                    raise ValidationContractError("COST_SOURCE_PROTOCOL_MISMATCH")
        if any(x.methods != gate_methods(p, x.gate) for x in self.gates):
            raise ValidationContractError("GATE_METHOD_PROTOCOL_MISMATCH")
        for name in ("first_holdout_access_at", "as_of", "created_at", "valid_until"):
            object.__setattr__(self, name, _time(name, getattr(self, name)))
        if (
            not p.holdout_access_not_before
            <= self.first_holdout_access_at
            <= self.as_of
            <= self.created_at
            < self.valid_until
            or not self.as_of
            < self.valid_until
            <= min(
                p.valid_until,
                c.expires_at,
                e.expires_at,
                *(x.valid_until for x in self.gates),
            )
            or c.created_at > self.as_of
            or e.created_at > self.as_of
            or any(x.as_of > self.as_of for x in self.gates)
        ):
            raise ValidationContractError("RESULT_SOURCE_TIME_OR_VALIDITY_MISMATCH")
        self._validate_metrics()
        _digest("content_sha256", self.content_sha256)
        digest = canonical_sha256(self.identity_payload())
        if digest != self.content_sha256 or self.result_id != uuid5(_NAMESPACE, digest):
            raise ValidationContractError("QUALIFICATION_RESULT_CONTENT_MISMATCH")

    def _validate_metrics(self) -> None:
        p = self.protocol.policy
        if self.sample_size is not None and (
            type(self.sample_size) is not int or self.sample_size < 0
        ):
            raise ValidationContractError("raw sample requires a nonnegative integer.")
        if self.effective_sample_size is not None:
            _decimal("effective_sample_size", self.effective_sample_size)
            if self.sample_size is None or self.effective_sample_size > Decimal(
                self.sample_size
            ):
                raise ValidationContractError(
                    "effective sample requires and cannot exceed raw sample."
                )
        if self.observed_conditional_win_rate is not None:
            _ratio("observed_conditional_win_rate", self.observed_conditional_win_rate)
            if self.sample_size is None or self.sample_size == 0:
                raise ValidationContractError(
                    "win rate requires a positive raw sample."
                )
        if self.after_cost_expectancy is not None and (
            type(self.after_cost_expectancy) is not Decimal
            or not self.after_cost_expectancy.is_finite()
        ):
            raise ValidationContractError(
                "expectancy requires a finite signed Decimal."
            )
        if self.after_cost_expectancy is None:
            if (
                self.expectancy_unit is not None
                or self.expectancy_quote_currency is not None
            ):
                raise ValidationContractError("missing expectancy cannot carry units.")
        elif (
            self.expectancy_unit is not p.expectancy_unit
            or self.expectancy_quote_currency != p.quote_currency
        ):
            raise ValidationContractError("EXPECTANCY_UNIT_OR_CURRENCY_MISMATCH")
        if self.maximum_drawdown_fraction is not None:
            _ratio("maximum_drawdown_fraction", self.maximum_drawdown_fraction)
        if self.uncertainty is not None:
            u = self.uncertainty
            if (
                type(u) is not QualificationUncertaintyV3
                or u.method != p.uncertainty_method
                or u.dependence_policy != p.dependence_policy
                or u.confidence_level != p.confidence_level
                or u.effective_sample_size != self.effective_sample_size
                or u.source
                not in next(
                    x
                    for x in self.gates
                    if x.gate is QualificationGateV3.STATISTICAL_SUPPORT
                ).sources
            ):
                raise ValidationContractError(
                    "UNCERTAINTY_SAMPLE_METHOD_OR_SOURCE_MISMATCH"
                )
        states = {x.gate: x.outcome for x in self.gates}
        requirements = {
            QualificationGateV3.THRESHOLD: self.observed_conditional_win_rate
            is not None
            and self.observed_conditional_win_rate >= p.conditional_win_rate_threshold,
            QualificationGateV3.SAMPLE_SUFFICIENCY: self.sample_size is not None
            and self.sample_size >= p.minimum_raw_sample
            and self.effective_sample_size is not None
            and self.effective_sample_size >= p.minimum_effective_sample,
            QualificationGateV3.EXPECTANCY_AFTER_COSTS: self.after_cost_expectancy
            is not None
            and self.after_cost_expectancy > p.minimum_after_cost_expectancy,
            QualificationGateV3.RISK: self.maximum_drawdown_fraction is not None
            and self.maximum_drawdown_fraction <= p.maximum_drawdown_fraction,
            QualificationGateV3.STATISTICAL_SUPPORT: self.uncertainty is not None,
        }
        if any(
            states[g] is QualificationOutcomeV3.PASS and not good
            for g, good in requirements.items()
        ):
            raise ValidationContractError(
                "PASS_GATE_MISSING_OR_BREACHED_POLICY_METRICS"
            )
        failures = {
            QualificationGateV3.THRESHOLD: self.observed_conditional_win_rate
            is not None
            and self.observed_conditional_win_rate < p.conditional_win_rate_threshold,
            QualificationGateV3.EXPECTANCY_AFTER_COSTS: self.after_cost_expectancy
            is not None
            and self.after_cost_expectancy <= p.minimum_after_cost_expectancy,
            QualificationGateV3.RISK: self.maximum_drawdown_fraction is not None
            and self.maximum_drawdown_fraction > p.maximum_drawdown_fraction,
        }
        if any(
            failed and states[g] is not QualificationOutcomeV3.FAIL
            for g, failed in failures.items()
        ):
            raise ValidationContractError("KNOWN_POLICY_FAILURE_MUST_REMAIN_FAILED")

    def identity_payload(self) -> dict[str, object]:
        return {
            x.name: getattr(self, x.name)
            for x in fields(self)
            if x.name not in {"result_id", "content_sha256"}
        }

    @classmethod
    def build(cls, **values: object) -> QualificationValidationResultV3:
        expected = {x.name for x in fields(cls) if x.init} - {
            "result_id",
            "content_sha256",
        }
        if set(values) != expected:
            raise ValidationContractError("exact qualification result fields required.")
        payload = dict(values)
        payload.update(
            {
                x.name: x.default
                for x in fields(cls)
                if not x.init and x.name != "outcome"
            }
        )
        payload["outcome"] = _aggregate(values["gates"])
        digest = canonical_sha256(payload)
        return cls(**values, result_id=uuid5(_NAMESPACE, digest), content_sha256=digest)  # type: ignore[arg-type]
