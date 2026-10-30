"""Bounded deterministic condition evaluation for PERSONAL_SPOT_RESEARCH.

This module consumes only immutable strategy registry results and validated
Spot orchestration outputs. It is deliberately a small allowlisted DSL
interpreter; strategy text is data and is never compiled or executed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import TypeAlias
from uuid import UUID

from trading_platform_api.analysis.contracts import (
    VersionReference,
)
from trading_platform_api.analysis.spot_meta_analysis import (
    SUPPORTED_SPOT_FINDING_DOMAINS,
    FindingReadiness,
    SpotMetaFinding,
)
from trading_platform_api.analysis.versioned_contracts import (
    ConfluenceEvidenceStrengthV2,
)
from trading_platform_api.analysis.versioned_contracts_v5 import MarketContextV5
from trading_platform_api.orchestration.spot_analysis_fanout import (
    SpotAnalysisFanoutResult,
    SpotAnalysisTaskStatus,
)
from trading_platform_api.orchestration.spot_debate import SpotDebateResult
from trading_platform_api.strategy.contracts import (
    ConditionGroup,
    ConditionGroupOperator,
    ConditionOperator,
    StrategyCondition,
    StrategyLifecycle,
)
from trading_platform_api.strategy.registry import (
    ArtifactVersionLifecycle,
    ResolvedStrategyVersion,
    StrategyAvailability,
    strategy_version_content_sha256,
)

DSL_DEFINITION_VERSION = "1"
MAX_CONDITIONS = 64
MAX_GROUPS = 32
MAX_EXPECTED_VALUES = 4
MAX_TEXT_LENGTH = 256
_RSI_METHOD = VersionReference("rsi", "rsi-wilder-sma-seed-v1")
_RSI_ADAPTER = VersionReference("spot-rsi-momentum-finding", "1")
_RSI_METADATA = VersionReference("indicator-metadata:rsi", "1")
_DECIMAL_LITERAL = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")

Scalar: TypeAlias = str | Decimal | bool


class ConditionTruth(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class ConditionResultCode(StrEnum):
    EVALUATED = "EVALUATED"
    UNKNOWN_FEATURE = "UNKNOWN_FEATURE"
    UNAVAILABLE_FEATURE = "UNAVAILABLE_FEATURE"
    STALE_INPUT = "STALE_INPUT"
    VERSION_MISMATCH = "VERSION_MISMATCH"
    INVALID_EXPECTED_VALUE = "INVALID_EXPECTED_VALUE"
    UNSUPPORTED_OPERATOR = "UNSUPPORTED_OPERATOR"
    UNSUPPORTED_RUNTIME_CASE = "UNSUPPORTED_RUNTIME_CASE"
    REQUIRED_EVIDENCE_UNAVAILABLE = "REQUIRED_EVIDENCE_UNAVAILABLE"
    INPUT_LIMIT_EXCEEDED = "INPUT_LIMIT_EXCEEDED"
    INVALID_STRATEGY_STATE = "INVALID_STRATEGY_STATE"


class FeatureAvailability(StrEnum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class ResolvedFeature:
    """One exact typed Spot value and its source contract/version lineage."""

    path: str
    availability: FeatureAvailability
    value: Scalar | None
    source_contract_id: str
    source_schema_version: str
    provenance: tuple[VersionReference, ...]
    source_record_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.path, str)
            or not self.path
            or len(self.path) > MAX_TEXT_LENGTH
        ):
            raise ValueError("feature path is invalid")
        if type(self.availability) is not FeatureAvailability:
            raise ValueError("feature availability is invalid")
        if self.value is not None and type(self.value) not in {str, Decimal, bool}:
            raise ValueError("feature value must use an exact scalar type")
        if type(self.value) is Decimal and not self.value.is_finite():
            raise ValueError("feature Decimal must be finite")
        if not isinstance(self.source_contract_id, str) or not self.source_contract_id:
            raise ValueError("source contract ID is required")
        if (
            not isinstance(self.source_schema_version, str)
            or not self.source_schema_version
        ):
            raise ValueError("source schema version is required")
        if type(self.provenance) is not tuple or any(
            type(item) is not VersionReference for item in self.provenance
        ):
            raise ValueError("feature provenance must be exact version references")
        if type(self.source_record_ids) is not tuple or any(
            not isinstance(item, UUID) for item in self.source_record_ids
        ):
            raise ValueError("feature source record IDs must be UUIDs")
        if self.availability is FeatureAvailability.PRESENT and self.value is None:
            raise ValueError("present feature requires a value")
        if (
            self.availability is not FeatureAvailability.PRESENT
            and self.value is not None
        ):
            raise ValueError("non-present feature cannot carry a value")


@dataclass(frozen=True, slots=True)
class SpotConditionContext:
    """Runtime-local, profile-scoped view of validated Spot outputs."""

    strategy: ResolvedStrategyVersion
    context_id: UUID
    correlation_id: UUID
    trace_id: UUID
    evaluated_at: datetime
    expires_at: datetime
    features: tuple[ResolvedFeature, ...]

    def __post_init__(self) -> None:
        if type(self.strategy) is not ResolvedStrategyVersion:
            raise ValueError("exact resolved strategy registry state is required")
        for name in ("context_id", "correlation_id", "trace_id"):
            if not isinstance(getattr(self, name), UUID):
                raise ValueError(f"{name} must be a UUID")
        for name in ("evaluated_at", "expires_at"):
            value = getattr(self, name)
            if (
                not isinstance(value, datetime)
                or value.tzinfo is None
                or value.utcoffset() is None
            ):
                raise ValueError(f"{name} must be timezone-aware")
            object.__setattr__(self, name, value.astimezone(UTC))
        if self.evaluated_at >= self.expires_at:
            raise ValueError("condition context must have a positive validity window")
        if type(self.features) is not tuple or any(
            type(item) is not ResolvedFeature for item in self.features
        ):
            raise ValueError("features must be a tuple of exact ResolvedFeature values")
        paths = tuple(item.path for item in self.features)
        if len(paths) != len(set(paths)):
            raise ValueError("feature paths must be unique")


@dataclass(frozen=True, slots=True)
class ConditionEvaluation:
    condition_id: UUID
    truth: ConditionTruth
    code: ConditionResultCode
    feature_path: str
    source_contract_id: str | None
    source_schema_version: str | None
    provenance: tuple[VersionReference, ...]
    source_record_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class GroupEvaluation:
    group_id: UUID
    operator: ConditionGroupOperator
    truth: ConditionTruth
    condition_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class StrategyConditionEvaluation:
    """Non-authoritative result; it is not a candidate, signal, or approval."""

    strategy_id: UUID
    strategy_version_id: UUID
    semantic_version: str
    content_sha256: str
    dsl_version: str
    context_id: UUID
    correlation_id: UUID
    trace_id: UUID
    evaluated_at: datetime
    expires_at: datetime
    truth: ConditionTruth
    reason_codes: tuple[ConditionResultCode, ...]
    conditions: tuple[ConditionEvaluation, ...]
    groups: tuple[GroupEvaluation, ...]


def build_spot_condition_context(
    *,
    strategy: ResolvedStrategyVersion,
    debate: SpotDebateResult,
    fanout: SpotAnalysisFanoutResult,
    now: datetime,
) -> SpotConditionContext:
    """Resolve only exact, typed features carried by the current Spot outputs."""

    if type(strategy) is not ResolvedStrategyVersion:
        raise ValueError("exact strategy registry resolution is required")
    if (
        type(debate) is not SpotDebateResult
        or type(fanout) is not SpotAnalysisFanoutResult
    ):
        raise ValueError("exact validated Spot debate and fan-out outputs are required")
    at = _utc("now", now)
    context = debate.market_context
    if (
        debate.correlation_id != fanout.correlation_id
        or debate.expires_at <= at
        or context.expires_at <= at
        or context.contract_id != "C-006"
        or context.schema_version != "5"
        or debate.agent_evaluation.result_id != debate.agent_result.result_id
        or debate.agent_evaluation.context_id != context.context_id
        or debate.agent_evaluation.correlation_id != debate.correlation_id
        or debate.agent_evaluation.trace_id != debate.trace_id
        or debate.agent_evaluation.outcome.value != "COMPLETED"
        or debate.agent_evaluation.schema_state.value != "VALID"
        or debate.agent_evaluation.result_status != debate.agent_result.status
        or debate.agent_result.context_id != context.context_id
        or debate.agent_result.output != context
    ):
        raise ValueError("Spot orchestration output is stale or mismatched")
    version = strategy.version
    if (
        context.asset not in version.supported_assets
        or context.instrument_id not in version.supported_instruments
        or context.adversarial.timeframe not in version.supported_timeframes
        or not any(item.value == "research" for item in version.operating_modes)
    ):
        raise ValueError("Spot context is outside the exact strategy profile")

    components = {item.component_id: item for item in context.confluence.components}
    findings: dict[str, SpotMetaFinding] = {}
    if len(fanout.outcomes) > len(SUPPORTED_SPOT_FINDING_DOMAINS):
        raise ValueError("Spot fan-out exceeds its approved domain bound")
    for outcome in fanout.outcomes:
        if outcome.status is not SpotAnalysisTaskStatus.COMPLETE:
            continue
        finding = outcome.finding
        if type(finding) is not SpotMetaFinding or finding.domain != outcome.domain:
            raise ValueError("Spot fan-out finding does not match its task")
        component = components.get(finding.finding_id)
        if component is None or (
            component.domain,
            component.direction,
            component.relation,
            component.evidence_ids,
            component.input_binding_ids,
        ) != (
            finding.domain,
            finding.direction,
            finding.relation,
            finding.evidence_ids,
            finding.input_binding_ids,
        ):
            raise ValueError("Spot finding is not bound to the exact C-009 component")
        if finding.domain in findings:
            raise ValueError("Spot fan-out contains duplicate feature domains")
        findings[finding.domain] = finding

    c006_provenance = (
        VersionReference("C-006", context.schema_version),
        VersionReference("C-007", context.analysis_snapshot.schema_version),
    )
    c009_provenance = (
        VersionReference("C-009", context.confluence.schema_version),
        context.confluence.method,
        VersionReference("C-007", context.analysis_snapshot.schema_version),
    )
    features: list[ResolvedFeature] = [
        _feature(
            "market.asset",
            context.asset,
            "C-006",
            context.schema_version,
            c006_provenance,
            (context.context_id,),
        ),
        _feature(
            "market.instrument_id",
            context.instrument_id,
            "C-006",
            context.schema_version,
            c006_provenance,
            (context.context_id,),
        ),
        _feature(
            "market.regime.direction",
            context.regime.direction.value,
            "C-005",
            context.regime.schema_version,
            (VersionReference("C-005", context.regime.schema_version),),
            (context.regime.regime_id,),
        ),
        _feature(
            "market.regime.dimension.trend.state",
            _dimension(context, "trend"),
            "C-005",
            context.regime.schema_version,
            (VersionReference("C-005", context.regime.schema_version),),
            (context.regime.regime_id,),
        ),
        _feature(
            "market.regime.dimension.realized-volatility.state",
            _dimension(context, "realized-volatility"),
            "C-005",
            context.regime.schema_version,
            (VersionReference("C-005", context.regime.schema_version),),
            (context.regime.regime_id,),
        ),
        _feature(
            "market.regime.dimension.transition.state",
            _dimension(context, "transition"),
            "C-005",
            context.regime.schema_version,
            (VersionReference("C-005", context.regime.schema_version),),
            (context.regime.regime_id,),
        ),
        _feature(
            "spot.confluence.state",
            context.confluence.state.value,
            "C-009",
            context.confluence.schema_version,
            c009_provenance,
            (context.confluence.assessment_id,),
        ),
    ]
    for domain, finding in sorted(findings.items()):
        prefix = f"spot.finding.{domain}"
        provenance = tuple(
            sorted(
                set((finding.method,) if finding.method else ())
                | set(finding.provenance),
                key=lambda ref: (ref.component, ref.version),
            )
        )
        features.extend(
            (
                _feature(
                    f"{prefix}.direction",
                    finding.direction.value,
                    "C-009",
                    context.confluence.schema_version,
                    c009_provenance + provenance,
                    (finding.finding_id, *finding.evidence_ids),
                ),
                _feature(
                    f"{prefix}.relation",
                    finding.relation.value,
                    "C-009",
                    context.confluence.schema_version,
                    c009_provenance + provenance,
                    (finding.finding_id, *finding.evidence_ids),
                ),
                _feature(
                    f"{prefix}.evidence_strength",
                    _component_strength(context, finding.finding_id).value,
                    "C-009",
                    context.confluence.schema_version,
                    c009_provenance + provenance,
                    (finding.finding_id, *finding.evidence_ids),
                ),
            )
        )
        if _is_supported_rsi14(finding):
            features.append(
                _feature(
                    "spot.momentum.rsi14.value",
                    finding.result_value,
                    "SPOT_META_FINDING",
                    "1",
                    c009_provenance + provenance,
                    (finding.finding_id, *finding.evidence_ids),
                )
            )
    return SpotConditionContext(
        strategy,
        context.context_id,
        debate.correlation_id,
        debate.trace_id,
        at,
        min(debate.expires_at, context.expires_at),
        tuple(features),
    )


def evaluate_strategy_conditions(
    strategy: ResolvedStrategyVersion,
    context: SpotConditionContext,
    *,
    now: datetime | None = None,
    max_conditions: int = MAX_CONDITIONS,
    max_groups: int = MAX_GROUPS,
) -> StrategyConditionEvaluation:
    """Evaluate one exact immutable C-021 version with bounded three-valued logic."""

    at = _utc("evaluated_at", now or context.evaluated_at)
    if type(strategy) is not ResolvedStrategyVersion or strategy != context.strategy:
        return _empty_evaluation(context, ConditionResultCode.VERSION_MISMATCH, at)
    version = strategy.version
    if (
        strategy.strategy.strategy_id != version.strategy_id
        or strategy_version_content_sha256(version) != version.content_sha256
    ):
        return _empty_evaluation(context, ConditionResultCode.VERSION_MISMATCH, at)
    if (
        not strategy.selectable_for_research
        or strategy.availability
        in {
            StrategyAvailability.SUSPENDED,
            StrategyAvailability.DEPRECATED,
        }
        or strategy.c021_lifecycle
        in {
            StrategyLifecycle.REJECTED,
            StrategyLifecycle.RETIRED,
            StrategyLifecycle.ROLLED_BACK,
        }
        or strategy.artifact_lifecycle
        in {
            ArtifactVersionLifecycle.REJECTED,
            ArtifactVersionLifecycle.RETIRED,
            ArtifactVersionLifecycle.ROLLED_BACK,
        }
    ):
        return _empty_evaluation(
            context, ConditionResultCode.INVALID_STRATEGY_STATE, at
        )
    if context.expires_at <= at:
        return _empty_evaluation(context, ConditionResultCode.STALE_INPUT, at)
    if (
        not isinstance(max_conditions, int)
        or isinstance(max_conditions, bool)
        or not 1 <= max_conditions <= MAX_CONDITIONS
        or not isinstance(max_groups, int)
        or isinstance(max_groups, bool)
        or not 1 <= max_groups <= MAX_GROUPS
        or len(version.conditions) > max_conditions
        or len(version.condition_groups) > max_groups
        or any(
            len(item.expected_values) > MAX_EXPECTED_VALUES
            for item in version.conditions
        )
        or len(context.features) > 8 + 3 * len(SUPPORTED_SPOT_FINDING_DOMAINS)
    ):
        return _empty_evaluation(context, ConditionResultCode.INPUT_LIMIT_EXCEEDED, at)
    if not version.conditions or not version.condition_groups:
        return _empty_evaluation(
            context, ConditionResultCode.UNSUPPORTED_RUNTIME_CASE, at
        )

    if any(
        len(group.condition_ids) > max_conditions for group in version.condition_groups
    ):
        return _empty_evaluation(context, ConditionResultCode.INPUT_LIMIT_EXCEEDED, at)
    grouped_condition_ids = {
        condition_id
        for group in version.condition_groups
        for condition_id in group.condition_ids
    }
    if grouped_condition_ids != {item.condition_id for item in version.conditions}:
        return _empty_evaluation(
            context, ConditionResultCode.UNSUPPORTED_RUNTIME_CASE, at
        )
    feature_map = {item.path: item for item in context.features}
    condition_results = tuple(
        _evaluate_condition(condition, feature_map, context.expires_at, at)
        for condition in version.conditions
    )
    result_map = {item.condition_id: item for item in condition_results}
    group_results = tuple(
        _evaluate_group(group, result_map) for group in version.condition_groups
    )
    evidence_available = _required_evidence_available(
        version.required_evidence_categories, feature_map
    )
    # C-021 has no root node; its declared groups are combined conjunctively.
    overall = _and(tuple(item.truth for item in group_results))
    if evidence_available is not True:
        overall = ConditionTruth.UNKNOWN
    reason_codes = tuple(
        dict.fromkeys(
            item.code
            for item in condition_results
            if item.code is not ConditionResultCode.EVALUATED
        )
    )
    if evidence_available is not True:
        reason_codes += (ConditionResultCode.REQUIRED_EVIDENCE_UNAVAILABLE,)
    return StrategyConditionEvaluation(
        strategy.strategy.strategy_id,
        version.strategy_version_id,
        version.semantic_version,
        version.content_sha256,
        DSL_DEFINITION_VERSION,
        context.context_id,
        context.correlation_id,
        context.trace_id,
        at,
        context.expires_at,
        overall,
        reason_codes,
        condition_results,
        group_results,
    )


def _evaluate_condition(
    condition: StrategyCondition,
    features: dict[str, ResolvedFeature],
    context_expiry: datetime,
    now: datetime,
) -> ConditionEvaluation:
    if condition.definition_version != DSL_DEFINITION_VERSION:
        return _condition_result(
            condition,
            ConditionTruth.UNKNOWN,
            ConditionResultCode.UNSUPPORTED_RUNTIME_CASE,
        )
    if len(condition.feature_path) > MAX_TEXT_LENGTH or any(
        len(value) > MAX_TEXT_LENGTH for value in condition.expected_values
    ):
        return _condition_result(
            condition, ConditionTruth.UNKNOWN, ConditionResultCode.INPUT_LIMIT_EXCEEDED
        )
    allowed_path = _is_allowlisted_path(condition.feature_path)
    if not allowed_path:
        return _condition_result(
            condition, ConditionTruth.UNKNOWN, ConditionResultCode.UNKNOWN_FEATURE
        )
    feature = features.get(condition.feature_path)
    if feature is None:
        return _condition_result(
            condition, ConditionTruth.UNKNOWN, ConditionResultCode.UNAVAILABLE_FEATURE
        )
    if context_expiry <= now:
        return _condition_result(
            condition, ConditionTruth.UNKNOWN, ConditionResultCode.STALE_INPUT, feature
        )
    if feature.availability is FeatureAvailability.UNAVAILABLE:
        return _condition_result(
            condition,
            ConditionTruth.UNKNOWN,
            ConditionResultCode.UNAVAILABLE_FEATURE,
            feature,
        )
    if condition.operator in {
        ConditionOperator.PERCENTILE_ABOVE,
        ConditionOperator.PERCENTILE_BELOW,
        ConditionOperator.CROSSES_ABOVE,
        ConditionOperator.CROSSES_BELOW,
    }:
        return _condition_result(
            condition,
            ConditionTruth.UNKNOWN,
            ConditionResultCode.UNSUPPORTED_OPERATOR,
            feature,
        )
    if condition.operator in {ConditionOperator.PRESENT, ConditionOperator.ABSENT}:
        if condition.expected_values:
            return _condition_result(
                condition,
                ConditionTruth.UNKNOWN,
                ConditionResultCode.INVALID_EXPECTED_VALUE,
                feature,
            )
        if feature.availability is FeatureAvailability.ABSENT:
            truth = (
                ConditionTruth.PASS
                if condition.operator is ConditionOperator.ABSENT
                else ConditionTruth.FAIL
            )
        elif (
            feature.availability is FeatureAvailability.PRESENT
            and feature.value is not None
        ):
            truth = (
                ConditionTruth.PASS
                if condition.operator is ConditionOperator.PRESENT
                else ConditionTruth.FAIL
            )
        else:
            truth = ConditionTruth.UNKNOWN
        return _condition_result(
            condition, truth, ConditionResultCode.EVALUATED, feature
        )
    if feature.availability is not FeatureAvailability.PRESENT or feature.value is None:
        return _condition_result(
            condition,
            ConditionTruth.UNKNOWN,
            ConditionResultCode.UNAVAILABLE_FEATURE,
            feature,
        )
    if condition.operator in {ConditionOperator.EQUALS, ConditionOperator.NOT_EQUALS}:
        if len(condition.expected_values) != 1:
            return _condition_result(
                condition,
                ConditionTruth.UNKNOWN,
                ConditionResultCode.INVALID_EXPECTED_VALUE,
                feature,
            )
        expected = _parse_expected(feature.value, condition.expected_values[0])
        if expected is None:
            return _condition_result(
                condition,
                ConditionTruth.UNKNOWN,
                ConditionResultCode.INVALID_EXPECTED_VALUE,
                feature,
            )
        equal = type(expected) is type(feature.value) and expected == feature.value
        passed = equal if condition.operator is ConditionOperator.EQUALS else not equal
        return _condition_result(
            condition,
            ConditionTruth.PASS if passed else ConditionTruth.FAIL,
            ConditionResultCode.EVALUATED,
            feature,
        )
    if condition.operator in {
        ConditionOperator.GREATER_THAN,
        ConditionOperator.GREATER_THAN_OR_EQUAL,
        ConditionOperator.LESS_THAN,
        ConditionOperator.LESS_THAN_OR_EQUAL,
        ConditionOperator.IN_RANGE,
    }:
        if type(feature.value) is not Decimal:
            return _condition_result(
                condition,
                ConditionTruth.UNKNOWN,
                ConditionResultCode.UNSUPPORTED_RUNTIME_CASE,
                feature,
            )
        needed = 2 if condition.operator is ConditionOperator.IN_RANGE else 1
        if len(condition.expected_values) != needed:
            return _condition_result(
                condition,
                ConditionTruth.UNKNOWN,
                ConditionResultCode.INVALID_EXPECTED_VALUE,
                feature,
            )
        expected_values = tuple(
            _parse_decimal(value) for value in condition.expected_values
        )
        if any(item is None for item in expected_values):
            return _condition_result(
                condition,
                ConditionTruth.UNKNOWN,
                ConditionResultCode.INVALID_EXPECTED_VALUE,
                feature,
            )
        bounds = tuple(item for item in expected_values if item is not None)
        value = feature.value
        if condition.operator is ConditionOperator.GREATER_THAN:
            passed = value > bounds[0]
        elif condition.operator is ConditionOperator.GREATER_THAN_OR_EQUAL:
            passed = value >= bounds[0]
        elif condition.operator is ConditionOperator.LESS_THAN:
            passed = value < bounds[0]
        elif condition.operator is ConditionOperator.LESS_THAN_OR_EQUAL:
            passed = value <= bounds[0]
        else:
            passed = bounds[0] <= value <= bounds[1]
            if bounds[0] > bounds[1]:
                return _condition_result(
                    condition,
                    ConditionTruth.UNKNOWN,
                    ConditionResultCode.INVALID_EXPECTED_VALUE,
                    feature,
                )
        return _condition_result(
            condition,
            ConditionTruth.PASS if passed else ConditionTruth.FAIL,
            ConditionResultCode.EVALUATED,
            feature,
        )
    return _condition_result(
        condition,
        ConditionTruth.UNKNOWN,
        ConditionResultCode.UNSUPPORTED_OPERATOR,
        feature,
    )


def _evaluate_group(
    group: ConditionGroup, results: dict[UUID, ConditionEvaluation]
) -> GroupEvaluation:
    children = tuple(results[item] for item in group.condition_ids if item in results)
    if len(children) != len(group.condition_ids):
        truth = ConditionTruth.UNKNOWN
    elif group.operator is ConditionGroupOperator.AND:
        truth = _and(tuple(item.truth for item in children))
    elif group.operator is ConditionGroupOperator.OR:
        truth = _or(tuple(item.truth for item in children))
    elif group.operator is ConditionGroupOperator.NOT and len(children) == 1:
        child = children[0].truth
        truth = (
            ConditionTruth.UNKNOWN
            if child is ConditionTruth.UNKNOWN
            else ConditionTruth.FAIL
            if child is ConditionTruth.PASS
            else ConditionTruth.PASS
        )
    else:
        truth = ConditionTruth.UNKNOWN
    return GroupEvaluation(group.group_id, group.operator, truth, group.condition_ids)


def _and(values: tuple[ConditionTruth, ...]) -> ConditionTruth:
    if not values or ConditionTruth.UNKNOWN in values:
        return ConditionTruth.UNKNOWN
    return (
        ConditionTruth.PASS
        if all(item is ConditionTruth.PASS for item in values)
        else ConditionTruth.FAIL
    )


def _or(values: tuple[ConditionTruth, ...]) -> ConditionTruth:
    if not values:
        return ConditionTruth.UNKNOWN
    if ConditionTruth.PASS in values:
        return ConditionTruth.PASS
    return (
        ConditionTruth.UNKNOWN
        if ConditionTruth.UNKNOWN in values
        else ConditionTruth.FAIL
    )


def _parse_expected(actual: Scalar, value: str) -> Scalar | None:
    if type(actual) is Decimal:
        return _parse_decimal(value)
    if type(actual) is bool:
        if value == "true":
            return True
        if value == "false":
            return False
        return None
    if type(actual) is str:
        return value
    return None


def _parse_decimal(value: str) -> Decimal | None:
    if (
        not value
        or value != value.strip()
        or len(value) > MAX_TEXT_LENGTH
        or _DECIMAL_LITERAL.fullmatch(value) is None
    ):
        return None
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _feature(
    path: str,
    value: Scalar | None,
    contract_id: str,
    schema_version: str,
    provenance: tuple[VersionReference, ...],
    source_record_ids: tuple[UUID, ...],
) -> ResolvedFeature:
    return ResolvedFeature(
        path,
        FeatureAvailability.PRESENT
        if value is not None
        else FeatureAvailability.UNAVAILABLE,
        value,
        contract_id,
        schema_version,
        provenance,
        source_record_ids,
    )


def _is_allowlisted_path(path: str) -> bool:
    if path in {
        "market.asset",
        "market.instrument_id",
        "market.regime.direction",
        "market.regime.dimension.trend.state",
        "market.regime.dimension.realized-volatility.state",
        "market.regime.dimension.transition.state",
        "spot.confluence.state",
        "spot.momentum.rsi14.value",
    }:
        return True
    prefix = "spot.finding."
    suffixes = {".direction", ".relation", ".evidence_strength"}
    if not path.startswith(prefix):
        return False
    domain, dot, suffix = path[len(prefix) :].rpartition(".")
    # A feature has exactly one field separator after the allowlisted domain.
    if not dot:
        return False
    field = f".{suffix}"
    return domain in SUPPORTED_SPOT_FINDING_DOMAINS and field in suffixes


def _is_supported_rsi14(finding: SpotMetaFinding) -> bool:
    return (
        finding.domain == "spot-momentum"
        and finding.readiness in {FindingReadiness.PARTIAL, FindingReadiness.READY}
        and finding.result_value is not None
        and Decimal("0") <= finding.result_value <= Decimal("100")
        and finding.result_unit == "percent"
        and finding.method == _RSI_ADAPTER
        and _RSI_METHOD in finding.provenance
        and _RSI_METADATA in finding.provenance
    )


def _dimension(context: MarketContextV5, name: str) -> str | None:
    match = next(
        (item for item in context.regime.dimensions if item.name == name), None
    )
    return match.state if match is not None else None


def _component_strength(
    context: MarketContextV5, finding_id: UUID
) -> ConfluenceEvidenceStrengthV2:
    component = next(
        (
            item
            for item in context.confluence.components
            if item.component_id == finding_id
        ),
        None,
    )
    if component is None:
        raise ValueError("Spot finding component disappeared from exact C-009 result")
    return component.evidence_strength


def _required_evidence_available(
    required_categories: tuple[str, ...], features: dict[str, ResolvedFeature]
) -> bool | None:
    """Return false/unknown for missing or unsupported declared evidence."""

    technical_paths = tuple(
        path
        for path, feature in features.items()
        if (path.startswith("spot.finding.") or path == "spot.momentum.rsi14.value")
        and feature.availability is FeatureAvailability.PRESENT
    )
    regime_paths = (
        "market.regime.direction",
        "market.regime.dimension.trend.state",
        "market.regime.dimension.realized-volatility.state",
        "market.regime.dimension.transition.state",
    )
    supported = {
        "technical": bool(technical_paths),
        "regime": all(
            path in features
            and features[path].availability is FeatureAvailability.PRESENT
            for path in regime_paths
        ),
        "confluence": "spot.confluence.state" in features
        and features["spot.confluence.state"].availability
        is FeatureAvailability.PRESENT,
    }
    if any(category not in supported for category in required_categories):
        return None
    return all(supported[category] for category in required_categories)


def _condition_result(
    condition: StrategyCondition,
    truth: ConditionTruth,
    code: ConditionResultCode,
    feature: ResolvedFeature | None = None,
) -> ConditionEvaluation:
    return ConditionEvaluation(
        condition.condition_id,
        truth,
        code,
        condition.feature_path,
        feature.source_contract_id if feature else None,
        feature.source_schema_version if feature else None,
        feature.provenance if feature else (),
        feature.source_record_ids if feature else (),
    )


def _empty_evaluation(
    context: SpotConditionContext, code: ConditionResultCode, evaluated_at: datetime
) -> StrategyConditionEvaluation:
    version = context.strategy.version
    return StrategyConditionEvaluation(
        context.strategy.strategy.strategy_id,
        version.strategy_version_id,
        version.semantic_version,
        version.content_sha256,
        DSL_DEFINITION_VERSION,
        context.context_id,
        context.correlation_id,
        context.trace_id,
        evaluated_at,
        context.expires_at,
        ConditionTruth.UNKNOWN,
        (code,),
        (),
        (),
    )


def _utc(name: str, value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


__all__ = [
    "ConditionEvaluation",
    "ConditionResultCode",
    "ConditionTruth",
    "DSL_DEFINITION_VERSION",
    "FeatureAvailability",
    "GroupEvaluation",
    "ResolvedFeature",
    "SpotConditionContext",
    "StrategyConditionEvaluation",
    "build_spot_condition_context",
    "evaluate_strategy_conditions",
]
