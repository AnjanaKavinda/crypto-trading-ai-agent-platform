"""ADR-0030 study-policy foundation; no qualification issuer or authority."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid5

from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.strategy.registry import validate_semantic_version
from trading_platform_api.validation.contracts import ValidationContractError
from trading_platform_api.validation.contracts_v2 import ValidationArtifactReferenceV2
from trading_platform_api.validation.contracts_v3 import _digest

_NAMESPACE = UUID("762f29fb-62c4-585f-adba-40f4fe1ef052")


def _text(name: str, value: object) -> None:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > 1024
    ):
        raise ValidationContractError(f"{name} requires bounded nonblank text.")


def _time(name: str, value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValidationContractError(f"{name} requires an aware datetime.")
    return value.astimezone(UTC)


def _decimal(name: str, value: object, *, positive: bool = False) -> Decimal:
    if (
        type(value) is not Decimal
        or not value.is_finite()
        or value < 0
        or (positive and value == 0)
    ):
        raise ValidationContractError(f"{name} requires a finite nonnegative Decimal.")
    return value


def _ratio(name: str, value: object, *, interior: bool = False) -> None:
    number = _decimal(name, value)
    if number > 1 or (interior and number in (Decimal(0), Decimal(1))):
        raise ValidationContractError(f"{name} is outside its fractional range.")


def _ref(name: str, value: object, kind: str, version: str | None = None) -> None:
    if (
        type(value) is not ValidationArtifactReferenceV2
        or value.artifact_type != kind
        or (version is not None and value.version != version)
    ):
        raise ValidationContractError(f"{name} requires exact {kind} reference.")
    _text(name + ".version", value.version)


class QualificationExpectancyUnitV3(StrEnum):
    QUOTE_PER_RESOLVED_TRADE = "QUOTE_PER_RESOLVED_TRADE"
    R_PER_RESOLVED_TRADE = "R_PER_RESOLVED_TRADE"


@dataclass(frozen=True, slots=True)
class QualificationDatasetPinV3:
    """Native source pins, not source resolution or authenticity evidence."""

    dataset_id: str
    dataset_version: str
    dataset_sha256: str
    manifest_sha256: str
    coverage_start: datetime
    coverage_end: datetime
    point_in_time_cutoff: datetime

    def __post_init__(self) -> None:
        for name in ("dataset_id", "dataset_version"):
            _text(name, getattr(self, name))
        for name in ("dataset_sha256", "manifest_sha256"):
            _digest(name, getattr(self, name))
        for name in ("coverage_start", "coverage_end", "point_in_time_cutoff"):
            object.__setattr__(self, name, _time(name, getattr(self, name)))
        if not self.coverage_start < self.coverage_end <= self.point_in_time_cutoff:
            raise ValidationContractError("STUDY_DATASET_WINDOW_INVALID")


@dataclass(frozen=True, slots=True)
class QualificationStudyPolicyV3:
    conditional_event_definition: str
    win_definition: str
    loss_definition: str
    breakeven_definition: str
    minimum_raw_sample: int
    minimum_effective_sample: Decimal
    conditional_win_rate_threshold: Decimal
    confidence_level: Decimal
    minimum_after_cost_expectancy: Decimal
    expectancy_unit: QualificationExpectancyUnitV3
    quote_currency: str | None
    maximum_drawdown_fraction: Decimal
    sample_method: ValidationArtifactReferenceV2
    dependence_policy: ValidationArtifactReferenceV2
    uncertainty_method: ValidationArtifactReferenceV2
    statistical_support_rule: ValidationArtifactReferenceV2
    historical_risk_policy: ValidationArtifactReferenceV2
    robustness_policy: ValidationArtifactReferenceV2
    selection_policy: ValidationArtifactReferenceV2
    return_basis: ValidationArtifactReferenceV2
    calibration_required: bool
    drawdown_basis: str = field(default="EQUITY_PEAK_FRACTION", init=False)
    expectancy_comparison: str = field(default="STRICTLY_GREATER", init=False)

    def __post_init__(self) -> None:
        for name in (
            "conditional_event_definition",
            "win_definition",
            "loss_definition",
            "breakeven_definition",
        ):
            _text(name, getattr(self, name))
        if type(self.minimum_raw_sample) is not int or self.minimum_raw_sample <= 0:
            raise ValidationContractError(
                "minimum_raw_sample must be a positive integer."
            )
        _decimal(
            "minimum_effective_sample", self.minimum_effective_sample, positive=True
        )
        _ratio("conditional_win_rate_threshold", self.conditional_win_rate_threshold)
        _ratio("confidence_level", self.confidence_level, interior=True)
        _decimal("minimum_after_cost_expectancy", self.minimum_after_cost_expectancy)
        _ratio("maximum_drawdown_fraction", self.maximum_drawdown_fraction)
        if type(self.expectancy_unit) is not QualificationExpectancyUnitV3:
            raise ValidationContractError("typed expectancy unit required.")
        if (
            self.expectancy_unit
            is QualificationExpectancyUnitV3.QUOTE_PER_RESOLVED_TRADE
        ):
            _text("quote_currency", self.quote_currency)
        elif self.quote_currency is not None:
            raise ValidationContractError(
                "normalized-R expectancy has no quote-currency unit."
            )
        if type(self.calibration_required) is not bool:
            raise ValidationContractError("calibration_required must be bool.")
        for name, kind in (
            ("sample_method", "SAMPLE_METHOD"),
            ("dependence_policy", "DEPENDENCE_POLICY"),
            ("uncertainty_method", "STATISTICAL_METHOD"),
            ("statistical_support_rule", "STATISTICAL_SUPPORT_RULE"),
            ("historical_risk_policy", "HISTORICAL_RISK_POLICY"),
            ("robustness_policy", "ROBUSTNESS_POLICY"),
            ("selection_policy", "SELECTION_POLICY"),
            ("return_basis", "RETURN_BASIS"),
        ):
            _ref(name, getattr(self, name), kind)


@dataclass(frozen=True, slots=True)
class QualificationStudyProtocolV3:
    """Content-frozen internal protocol supporting future C-028v3 issuance.

    Construction binds supplied claims, not their truth, registration, approval
    or real freeze time. A later issuer must resolve the complete source objects
    and trusted journal receipts before using this protocol. No gate is evaluated
    here; no reference or configured method is made authoritative by this value.
    """

    protocol_id: UUID
    strategy_version: ValidationArtifactReferenceV2
    strategy_semantic_version: str
    parameter_set: ValidationArtifactReferenceV2
    configuration: ValidationArtifactReferenceV2
    methodology: ValidationArtifactReferenceV2
    code_build: ValidationArtifactReferenceV2
    cost_assumptions: ValidationArtifactReferenceV2
    datasets: tuple[QualificationDatasetPinV3, ...]
    asset: str
    venue: str
    instrument_id: str
    timeframe: str
    regime: str
    study_start: datetime
    study_end: datetime
    frozen_at: datetime
    holdout_access_not_before: datetime
    valid_until: datetime
    policy: QualificationStudyPolicyV3
    content_sha256: str
    schema_version: str = field(default="3", init=False)
    market_type: str = field(default="SPOT", init=False)
    identity_method: str = field(default="qualification-study-identity-v1", init=False)
    qualification_authorized: bool = field(default=False, init=False)
    execution_authorized: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if type(self.protocol_id) is not UUID:
            raise ValidationContractError("protocol_id must be UUID.")
        for name, kind, version in (
            ("strategy_version", "C-021", "2"),
            ("parameter_set", "PARAMETER_SET", None),
            ("configuration", "CONFIGURATION", None),
            ("methodology", "VALIDATION_METHODOLOGY", None),
            ("code_build", "CODE_BUILD", None),
            ("cost_assumptions", "C-027", "2"),
        ):
            _ref(name, getattr(self, name), kind, version)
        validate_semantic_version(self.strategy_semantic_version)
        for name in ("asset", "venue", "instrument_id", "timeframe", "regime"):
            _text(name, getattr(self, name))
        if type(self.policy) is not QualificationStudyPolicyV3:
            raise ValidationContractError("exact study policy required.")
        if (
            type(self.datasets) is not tuple
            or not 1 <= len(self.datasets) <= 16
            or any(type(x) is not QualificationDatasetPinV3 for x in self.datasets)
        ):
            raise ValidationContractError(
                "one to sixteen immutable dataset pins required."
            )
        keys = [(x.dataset_id, x.dataset_version) for x in self.datasets]
        if len(keys) != len(set(keys)):
            raise ValidationContractError("duplicate dataset identity.")
        if keys != sorted(keys):
            raise ValidationContractError(
                "dataset pins require canonical identity order."
            )
        for name in (
            "study_start",
            "study_end",
            "frozen_at",
            "holdout_access_not_before",
            "valid_until",
        ):
            object.__setattr__(self, name, _time(name, getattr(self, name)))
        if (
            not self.study_start
            < self.study_end
            <= self.frozen_at
            <= self.holdout_access_not_before
            < self.valid_until
        ):
            raise ValidationContractError("STUDY_PROTOCOL_TIME_ORDER_INVALID")
        if any(
            x.point_in_time_cutoff > self.frozen_at
            or x.coverage_start < self.study_start
            or x.coverage_end > self.study_end
            for x in self.datasets
        ):
            raise ValidationContractError("STUDY_DATASET_SCOPE_OR_CUTOFF_MISMATCH")
        _digest("content_sha256", self.content_sha256)
        digest = canonical_sha256(self.identity_payload())
        if self.content_sha256 != digest or self.protocol_id != uuid5(
            _NAMESPACE, digest
        ):
            raise ValidationContractError("STUDY_PROTOCOL_CONTENT_MISMATCH")

    def identity_payload(self) -> dict[str, object]:
        return {
            x.name: getattr(self, x.name)
            for x in fields(self)
            if x.name not in {"protocol_id", "content_sha256"}
        }

    @classmethod
    def build(cls, **values: object) -> QualificationStudyProtocolV3:
        required = {x.name for x in fields(cls) if x.init} - {
            "protocol_id",
            "content_sha256",
        }
        if set(values) != required:
            raise ValidationContractError("exact study protocol input fields required.")
        payload = dict(values)
        payload.update({x.name: x.default for x in fields(cls) if not x.init})
        digest = canonical_sha256(payload)
        return cls(
            **values,  # type: ignore[arg-type]
            protocol_id=uuid5(_NAMESPACE, digest),
            content_sha256=digest,
        )

    @property
    def reference(self) -> ValidationArtifactReferenceV2:
        return ValidationArtifactReferenceV2(
            "QUALIFICATION_STUDY_PROTOCOL",
            self.protocol_id,
            self.schema_version,
            self.content_sha256,
        )
