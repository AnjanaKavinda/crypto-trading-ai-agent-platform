from __future__ import annotations

import re
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.validation.contracts import (
    AssumptionCategory,
    ValidationContractError,
)

VALIDATION_CONTRACT_SCHEMA_VERSION_V2 = "2"


def _text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValidationContractError(f"{name} must be a non-blank trimmed string.")
    return value


def _uuid(name: str, value: object) -> UUID:
    if not isinstance(value, UUID):
        raise ValidationContractError(f"{name} must be a UUID.")
    return value


def _time(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValidationContractError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


def _ratio(name: str, value: object) -> Decimal:
    if (
        not isinstance(value, Decimal)
        or not value.is_finite()
        or not Decimal(0) <= value <= Decimal(1)
    ):
        raise ValidationContractError(f"{name} must be a Decimal ratio from 0 to 1.")
    return value


def _ref(
    name: str, value: object, contract_id: str | None = None
) -> ValidationArtifactReferenceV2:
    if not isinstance(value, ValidationArtifactReferenceV2) or (
        contract_id and value.artifact_type != contract_id
    ):
        expected = f" referencing {contract_id}" if contract_id else ""
        raise ValidationContractError(f"{name} must be a VersionReference{expected}.")
    return value


@dataclass(frozen=True, slots=True)
class ValidationArtifactReferenceV2:
    artifact_type: str
    artifact_id: UUID
    version: str
    content_sha256: str

    def __post_init__(self) -> None:
        _text("artifact_type", self.artifact_type)
        _uuid("artifact_id", self.artifact_id)
        _text("version", self.version)
        if (
            re.fullmatch(r"[0-9a-f]{64}", _text("content_sha256", self.content_sha256))
            is None
        ):
            raise ValidationContractError("content_sha256 must be lowercase SHA-256.")


class CostApplicabilityV2(StrEnum):
    APPLICABLE = "APPLICABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"


class ValidationOutcomeV2(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INSUFFICIENT_VALIDATION = "INSUFFICIENT_VALIDATION"


class StatisticalSupportStateV2(StrEnum):
    OBSERVED = "OBSERVED"
    SUPPORTED = "SUPPORTED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    INSUFFICIENT = "INSUFFICIENT"


class ValidationGateOutcomeV2(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INSUFFICIENT_VALIDATION = "INSUFFICIENT_VALIDATION"


class QualificationGateV2(StrEnum):
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


@dataclass(frozen=True, slots=True)
class ResearchAssumptionV2:
    category: AssumptionCategory
    applicability: CostApplicabilityV2
    model: ValidationArtifactReferenceV2
    value: Decimal | None
    unit: str | None
    rationale: str
    schema_version: str = field(
        default=VALIDATION_CONTRACT_SCHEMA_VERSION_V2, init=False
    )

    def __post_init__(self) -> None:
        if not isinstance(self.category, AssumptionCategory):
            raise ValidationContractError("category must be AssumptionCategory.")
        if not isinstance(self.applicability, CostApplicabilityV2):
            raise ValidationContractError("applicability must be CostApplicabilityV2.")
        _ref("model", self.model)
        _text("rationale", self.rationale)
        if self.applicability is CostApplicabilityV2.APPLICABLE:
            if (
                not isinstance(self.value, Decimal)
                or not self.value.is_finite()
                or self.value < 0
            ):
                raise ValidationContractError(
                    "applicable assumptions require a non-negative Decimal value."
                )
            _text("unit", self.unit)
        elif self.value is not None or self.unit is not None:
            raise ValidationContractError(
                "NOT_APPLICABLE/UNKNOWN assumptions cannot carry a numeric value."
            )


@dataclass(frozen=True, slots=True)
class CostAssumptionSetV2:
    assumption_set_id: UUID
    strategy_version_id: UUID
    asset: str
    instrument_type: str
    required_categories: tuple[AssumptionCategory, ...]
    assumptions: tuple[ResearchAssumptionV2, ...]
    content_sha256: str
    contract_id: str = field(default="C-027", init=False)
    schema_version: str = field(
        default=VALIDATION_CONTRACT_SCHEMA_VERSION_V2, init=False
    )

    def __post_init__(self) -> None:
        _uuid("assumption_set_id", self.assumption_set_id)
        _uuid("strategy_version_id", self.strategy_version_id)
        _text("asset", self.asset)
        _text("instrument_type", self.instrument_type)
        if not self.required_categories or any(
            not isinstance(c, AssumptionCategory) for c in self.required_categories
        ):
            raise ValidationContractError(
                "required_categories must be non-empty typed categories."
            )
        if len(set(self.required_categories)) != len(self.required_categories):
            raise ValidationContractError("required cost categories must be unique.")
        if not self.assumptions or any(
            not isinstance(a, ResearchAssumptionV2) for a in self.assumptions
        ):
            raise ValidationContractError(
                "assumptions must contain ResearchAssumptionV2 values."
            )
        categories = tuple(a.category for a in self.assumptions)
        if len(set(categories)) != len(categories):
            raise ValidationContractError("cost assumption categories must be unique.")
        if not set(self.required_categories).issubset(categories):
            raise ValidationContractError("required cost assumptions are missing.")
        if self.instrument_type == "SPOT":
            funding = next(
                (
                    a
                    for a in self.assumptions
                    if a.category is AssumptionCategory.FUNDING
                ),
                None,
            )
            if (
                funding is None
                or AssumptionCategory.FUNDING not in self.required_categories
            ):
                raise ValidationContractError(
                    "Spot funding applicability must be explicit and required."
                )
            if funding.applicability is not CostApplicabilityV2.NOT_APPLICABLE:
                raise ValidationContractError(
                    "Spot funding must be explicitly NOT_APPLICABLE."
                )
        expected = canonical_sha256(
            {
                "assumption_set_id": self.assumption_set_id,
                "strategy_version_id": self.strategy_version_id,
                "asset": self.asset,
                "instrument_type": self.instrument_type,
                "required_categories": self.required_categories,
                "assumptions": self.assumptions,
                "contract_id": "C-027",
                "schema_version": "2",
            }
        )
        if self.content_sha256 != expected:
            raise ValidationContractError(
                "cost assumption digest does not match content."
            )

    @classmethod
    def build(cls, **values: object) -> CostAssumptionSetV2:
        values.pop("content_sha256", None)
        payload = {
            **values,
            "contract_id": "C-027",
            "schema_version": "2",
        }
        digest = canonical_sha256(payload)
        return cls(content_sha256=digest, **values)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class QualificationRuleSetV2:
    rule_set_id: UUID
    version: str
    strategy_version_id: UUID
    asset: str
    instrument_type: str
    timeframe: str
    regime: str
    conditional_event_definition: str
    conditional_win_rate_threshold: Decimal
    calibration_required: bool
    methodology: ValidationArtifactReferenceV2
    cost_assumption_set: ValidationArtifactReferenceV2
    content_sha256: str

    def __post_init__(self) -> None:
        _uuid("rule_set_id", self.rule_set_id)
        _text("version", self.version)
        _uuid("strategy_version_id", self.strategy_version_id)
        for name in (
            "asset",
            "instrument_type",
            "timeframe",
            "regime",
            "conditional_event_definition",
        ):
            _text(name, getattr(self, name))
        _ratio("conditional_win_rate_threshold", self.conditional_win_rate_threshold)
        if not isinstance(self.calibration_required, bool):
            raise ValidationContractError("calibration_required must be a bool.")
        _ref("methodology", self.methodology)
        _ref("cost_assumption_set", self.cost_assumption_set, "C-027")
        if self.cost_assumption_set.version != "2":
            raise ValidationContractError(
                "qualification rules require C-027 schema 2 cost assumptions."
            )
        expected = canonical_sha256(
            {
                "rule_set_id": self.rule_set_id,
                "version": self.version,
                "strategy_version_id": self.strategy_version_id,
                "asset": self.asset,
                "instrument_type": self.instrument_type,
                "timeframe": self.timeframe,
                "regime": self.regime,
                "conditional_event_definition": self.conditional_event_definition,
                "conditional_win_rate_threshold": self.conditional_win_rate_threshold,
                "calibration_required": self.calibration_required,
                "methodology": self.methodology,
                "cost_assumption_set": self.cost_assumption_set,
            }
        )
        if self.content_sha256 != expected:
            raise ValidationContractError(
                "rule-set digest does not match configuration."
            )

    @classmethod
    def build(cls, **values: object) -> QualificationRuleSetV2:
        values.pop("content_sha256", None)
        digest = canonical_sha256(values)
        return cls(content_sha256=digest, **values)  # type: ignore[arg-type]

    @property
    def reference(self) -> ValidationArtifactReferenceV2:
        return ValidationArtifactReferenceV2(
            "C-025-RULESET", self.rule_set_id, self.version, self.content_sha256
        )


@dataclass(frozen=True, slots=True)
class QualificationGateResultV2:
    gate: QualificationGateV2
    outcome: ValidationGateOutcomeV2
    evidence: ValidationArtifactReferenceV2 | None
    valid_until: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.gate, QualificationGateV2):
            raise ValidationContractError("gate must be QualificationGateV2.")
        if not isinstance(self.outcome, ValidationGateOutcomeV2):
            raise ValidationContractError("outcome must be ValidationGateOutcomeV2.")
        if self.evidence is not None:
            _ref("evidence", self.evidence)
        elif self.outcome is not ValidationGateOutcomeV2.INSUFFICIENT_VALIDATION:
            raise ValidationContractError(
                "PASS/FAIL gates require authoritative evidence."
            )
        object.__setattr__(self, "valid_until", _time("valid_until", self.valid_until))


@dataclass(frozen=True, slots=True)
class StatisticalUncertaintyEvidenceV2:
    result: ValidationArtifactReferenceV2
    methodology: ValidationArtifactReferenceV2
    metric_names: tuple[str, ...]

    def __post_init__(self) -> None:
        _ref("result", self.result)
        _ref("methodology", self.methodology)
        if not self.metric_names or any(
            not isinstance(item, str) or not item.strip() for item in self.metric_names
        ):
            raise ValidationContractError(
                "metric_names must identify uncertainty outputs."
            )
        if len(set(self.metric_names)) != len(self.metric_names):
            raise ValidationContractError("metric_names must be unique.")


@dataclass(frozen=True, slots=True)
class QualificationValidationResultV2:
    result_id: UUID
    candidate_id: UUID
    candidate_sha256: str
    evidence_package_id: UUID
    evidence_package_sha256: str
    strategy_version_id: UUID
    asset: str
    instrument_type: str
    timeframe: str
    regime: str
    rule_set: QualificationRuleSetV2
    cost_assumptions: CostAssumptionSetV2
    observed_conditional_win_rate: Decimal | None
    sample_size: int | None
    effective_sample_size: Decimal | None
    sample_semantics: ValidationArtifactReferenceV2
    after_cost_expectancy: Decimal | None
    expectancy_unit: str | None
    statistical_uncertainty: StatisticalUncertaintyEvidenceV2 | None
    statistical_support_state: StatisticalSupportStateV2
    calibration: ValidationArtifactReferenceV2 | None
    gates: tuple[QualificationGateResultV2, ...]
    outcome: ValidationOutcomeV2
    methodology: ValidationArtifactReferenceV2
    created_at: datetime
    as_of: datetime
    valid_until: datetime
    content_sha256: str
    contract_id: str = field(default="C-028", init=False)
    schema_version: str = field(
        default=VALIDATION_CONTRACT_SCHEMA_VERSION_V2, init=False
    )

    def __post_init__(self) -> None:
        for name in (
            "result_id",
            "candidate_id",
            "evidence_package_id",
            "strategy_version_id",
        ):
            _uuid(name, getattr(self, name))
        for name in ("candidate_sha256", "evidence_package_sha256"):
            if re.fullmatch(r"[0-9a-f]{64}", _text(name, getattr(self, name))) is None:
                raise ValidationContractError(f"{name} must be lowercase SHA-256.")
        for name in ("asset", "instrument_type", "timeframe", "regime"):
            _text(name, getattr(self, name))
        if not isinstance(self.statistical_support_state, StatisticalSupportStateV2):
            raise ValidationContractError(
                "statistical_support_state must be StatisticalSupportStateV2."
            )
        _ref("sample_semantics", self.sample_semantics)
        if self.statistical_uncertainty is not None:
            if not isinstance(
                self.statistical_uncertainty, StatisticalUncertaintyEvidenceV2
            ):
                raise ValidationContractError(
                    "statistical_uncertainty must be typed uncertainty evidence."
                )
        if self.calibration is not None:
            _ref("calibration", self.calibration, "C-031")
        if not isinstance(self.rule_set, QualificationRuleSetV2):
            raise ValidationContractError("rule_set must be QualificationRuleSetV2.")
        if not isinstance(self.cost_assumptions, CostAssumptionSetV2):
            raise ValidationContractError(
                "cost_assumptions must be CostAssumptionSetV2."
            )
        if (
            self.cost_assumptions.assumption_set_id
            != self.rule_set.cost_assumption_set.artifact_id
        ):
            raise ValidationContractError(
                "cost assumptions do not match the configured rule set."
            )
        if (
            self.cost_assumptions.content_sha256
            != self.rule_set.cost_assumption_set.content_sha256
        ):
            raise ValidationContractError(
                "cost assumption digest does not match the configured rule set."
            )
        if self.rule_set.strategy_version_id != self.strategy_version_id or (
            self.rule_set.asset,
            self.rule_set.instrument_type,
            self.rule_set.timeframe,
            self.rule_set.regime,
        ) != (self.asset, self.instrument_type, self.timeframe, self.regime):
            raise ValidationContractError(
                "validation scope must exactly match its rule set."
            )
        if self.rule_set.calibration_required and self.calibration is None:
            raise ValidationContractError("required calibration evidence is missing.")
        if self.observed_conditional_win_rate is not None:
            _ratio("observed_conditional_win_rate", self.observed_conditional_win_rate)
        if self.sample_size is not None and (
            not isinstance(self.sample_size, int)
            or isinstance(self.sample_size, bool)
            or self.sample_size < 0
        ):
            raise ValidationContractError(
                "sample_size must be a non-negative integer or absent."
            )
        if self.effective_sample_size is not None and (
            not isinstance(self.effective_sample_size, Decimal)
            or not self.effective_sample_size.is_finite()
            or self.effective_sample_size < 0
        ):
            raise ValidationContractError(
                "effective_sample_size must be a non-negative Decimal or absent."
            )
        if self.after_cost_expectancy is not None and (
            not isinstance(self.after_cost_expectancy, Decimal)
            or not self.after_cost_expectancy.is_finite()
        ):
            raise ValidationContractError(
                "after_cost_expectancy must be a finite Decimal or absent."
            )
        if self.after_cost_expectancy is None:
            if self.expectancy_unit is not None:
                raise ValidationContractError("missing expectancy cannot carry a unit.")
        else:
            _text("expectancy_unit", self.expectancy_unit)
        if not isinstance(self.outcome, ValidationOutcomeV2):
            raise ValidationContractError("outcome must be ValidationOutcomeV2.")
        _ref("methodology", self.methodology)
        if not self.gates or any(
            not isinstance(g, QualificationGateResultV2) for g in self.gates
        ):
            raise ValidationContractError(
                "gates must contain QualificationGateResultV2 values."
            )
        if {g.gate for g in self.gates} != set(QualificationGateV2):
            raise ValidationContractError(
                "C-028v2 requires every qualification gate exactly once."
            )
        if len({g.gate for g in self.gates}) != len(self.gates):
            raise ValidationContractError("qualification gates must be unique.")
        states = {g.gate: g.outcome for g in self.gates}
        source_contracts = {
            QualificationGateV2.DATA_INTEGRITY: {"C-003", "C-027"},
            QualificationGateV2.POINT_IN_TIME: {"C-027", "C-092"},
            QualificationGateV2.OOS: {"C-071"},
            QualificationGateV2.WALK_FORWARD: {"C-029"},
            QualificationGateV2.ROBUSTNESS: {"C-030"},
            QualificationGateV2.BIAS_LEAKAGE: {"C-094"},
            QualificationGateV2.REGIME_APPLICABILITY: {"C-074"},
            QualificationGateV2.RISK: {"C-035", "C-082", "C-083"},
        }
        for gate, contracts in source_contracts.items():
            gate_result = next(item for item in self.gates if item.gate is gate)
            if (
                gate_result.evidence is not None
                and gate_result.evidence.artifact_type not in contracts
            ):
                raise ValidationContractError(
                    f"{gate.value} must reference an authoritative result in {sorted(contracts)}."
                )
        if self.cost_assumptions.asset != self.asset:
            raise ValidationContractError(
                "cost assumptions must match validation asset scope."
            )
        if self.cost_assumptions.instrument_type != self.rule_set.instrument_type:
            raise ValidationContractError(
                "cost instrument scope must match the qualification rule set."
            )
        if self.cost_assumptions.strategy_version_id != self.strategy_version_id:
            raise ValidationContractError(
                "cost assumptions must match the exact strategy version."
            )
        if states[
            QualificationGateV2.COST_APPLICABILITY
        ] is ValidationGateOutcomeV2.PASS and any(
            assumption.applicability is CostApplicabilityV2.UNKNOWN
            for assumption in self.cost_assumptions.assumptions
            if assumption.category in self.cost_assumptions.required_categories
        ):
            raise ValidationContractError("unknown cost applicability cannot pass.")
        if (
            self.observed_conditional_win_rate is None
            and states[QualificationGateV2.THRESHOLD]
            is not ValidationGateOutcomeV2.INSUFFICIENT_VALIDATION
        ):
            raise ValidationContractError(
                "missing observed win rate must be insufficient validation."
            )
        if self.observed_conditional_win_rate is not None:
            meets = (
                self.observed_conditional_win_rate
                >= self.rule_set.conditional_win_rate_threshold
            )
            if (
                meets
                and states[QualificationGateV2.THRESHOLD]
                is ValidationGateOutcomeV2.FAIL
            ):
                raise ValidationContractError(
                    "threshold gate contradicts observed rate/configuration."
                )
            if (
                not meets
                and states[QualificationGateV2.THRESHOLD]
                is ValidationGateOutcomeV2.PASS
            ):
                raise ValidationContractError(
                    "threshold equality-or-better is required for PASS."
                )
            if not meets and (
                states[QualificationGateV2.THRESHOLD]
                is not ValidationGateOutcomeV2.FAIL
                or self.outcome is not ValidationOutcomeV2.FAIL
            ):
                raise ValidationContractError(
                    "measured below-threshold rate is an authoritative failure."
                )
        if (
            self.sample_size is None
            and states[QualificationGateV2.SAMPLE_SUFFICIENCY]
            is not ValidationGateOutcomeV2.INSUFFICIENT_VALIDATION
        ):
            raise ValidationContractError(
                "missing sample result must be insufficient validation."
            )
        if (
            self.sample_size == 0
            and states[QualificationGateV2.SAMPLE_SUFFICIENCY]
            is ValidationGateOutcomeV2.PASS
        ):
            raise ValidationContractError(
                "zero observations cannot pass sample sufficiency."
            )
        if (
            self.after_cost_expectancy is None
            and states[QualificationGateV2.EXPECTANCY_AFTER_COSTS]
            is not ValidationGateOutcomeV2.INSUFFICIENT_VALIDATION
        ):
            raise ValidationContractError(
                "missing expectancy must be insufficient validation."
            )
        if (
            self.after_cost_expectancy is not None
            and self.after_cost_expectancy <= 0
            and states[QualificationGateV2.EXPECTANCY_AFTER_COSTS]
            is ValidationGateOutcomeV2.PASS
        ):
            raise ValidationContractError(
                "non-positive after-cost expectancy cannot pass."
            )
        if (
            self.after_cost_expectancy is not None
            and self.after_cost_expectancy <= 0
            and (
                states[QualificationGateV2.EXPECTANCY_AFTER_COSTS]
                is not ValidationGateOutcomeV2.FAIL
                or self.outcome is not ValidationOutcomeV2.FAIL
            )
        ):
            raise ValidationContractError(
                "measured non-positive expectancy is an authoritative failure."
            )
        if (
            states[QualificationGateV2.STATISTICAL_SUPPORT]
            is ValidationGateOutcomeV2.PASS
            and self.statistical_uncertainty is None
        ):
            raise ValidationContractError(
                "statistical support PASS requires uncertainty evidence."
            )
        if (
            states[QualificationGateV2.STATISTICAL_SUPPORT]
            is ValidationGateOutcomeV2.PASS
            and self.statistical_support_state
            is not StatisticalSupportStateV2.SUPPORTED
        ):
            raise ValidationContractError(
                "statistical support PASS requires the authoritative supported state."
            )
        created, as_of, valid = (
            _time("created_at", self.created_at),
            _time("as_of", self.as_of),
            _time("valid_until", self.valid_until),
        )
        if (
            created > as_of
            or as_of >= valid
            or any(g.valid_until < valid for g in self.gates)
        ):
            raise ValidationContractError(
                "validation times must be ordered and bounded by all gate expiries."
            )
        if self.outcome is ValidationOutcomeV2.PASS and any(
            state is not ValidationGateOutcomeV2.PASS for state in states.values()
        ):
            raise ValidationContractError(
                "PASS requires every authoritative gate to PASS."
            )
        if self.outcome is ValidationOutcomeV2.FAIL and not any(
            state is ValidationGateOutcomeV2.FAIL for state in states.values()
        ):
            raise ValidationContractError(
                "FAIL requires authoritative evidence proving a failed gate."
            )
        if self.outcome is ValidationOutcomeV2.INSUFFICIENT_VALIDATION and any(
            state is ValidationGateOutcomeV2.FAIL for state in states.values()
        ):
            raise ValidationContractError(
                "proven failure must not be downgraded to insufficient validation."
            )
        if self.outcome is ValidationOutcomeV2.PASS and (
            states[QualificationGateV2.THRESHOLD] is not ValidationGateOutcomeV2.PASS
            or states[QualificationGateV2.EXPECTANCY_AFTER_COSTS]
            is not ValidationGateOutcomeV2.PASS
            or states[QualificationGateV2.COST_APPLICABILITY]
            is not ValidationGateOutcomeV2.PASS
        ):
            raise ValidationContractError(
                "PASS requires threshold, positive expectancy, and applicable cost gates."
            )
        expected_digest = _validation_digest(self)
        if self.content_sha256 != expected_digest:
            raise ValidationContractError(
                "validation result digest does not match content."
            )
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "valid_until", valid)

    @classmethod
    def build(cls, **values: object) -> QualificationValidationResultV2:
        values.pop("content_sha256", None)
        draft = object.__new__(cls)
        for item in fields(cls):
            if item.name == "content_sha256":
                continue
            value = values.get(item.name, item.default)
            object.__setattr__(draft, item.name, value)
        digest = _validation_digest(draft)
        return cls(content_sha256=digest, **values)  # type: ignore[arg-type]


def _validation_digest(value: QualificationValidationResultV2) -> str:
    return canonical_sha256(
        {
            item.name: getattr(value, item.name)
            for item in fields(value)
            if item.name != "content_sha256"
        }
    )


__all__ = [
    "CostApplicabilityV2",
    "CostAssumptionSetV2",
    "QualificationGateResultV2",
    "QualificationGateV2",
    "QualificationRuleSetV2",
    "QualificationValidationResultV2",
    "ResearchAssumptionV2",
    "StatisticalSupportStateV2",
    "StatisticalUncertaintyEvidenceV2",
    "VALIDATION_CONTRACT_SCHEMA_VERSION_V2",
    "ValidationGateOutcomeV2",
    "ValidationArtifactReferenceV2",
    "ValidationOutcomeV2",
]
