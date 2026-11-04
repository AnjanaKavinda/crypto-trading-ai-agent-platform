from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from test_qualification_rule_evaluator import request
from test_strategy_contracts import signal as signal_v1
from test_strategy_evidence_package import _package
from test_strategy_setup_detection import _detect, _positive_case
from trading_platform_api.contracts.serialization import (
    contract_sha256,
    serialize_contract,
)
from trading_platform_api.strategy import (
    InvalidationCombinationV2,
    InvalidationRuleSetV2,
    InvalidationTargetTypeV2,
    InvalidationTriggerV2,
    InvalidationTruthV2,
    NoTradeEngineStatus,
    NoTradeReasonV2,
    QualificationEngineStatus,
    Signal,
    SignalCodecError,
    SignalV2,
    StrategyVersionV2,
    build_personal_spot_strategy_v2,
    decode_signal_contract,
    evaluate_no_trade_v2,
    evaluate_qualification_rules,
    evaluate_signal_qualification_v2,
    strategy_version_content_sha256,
)
from trading_platform_api.strategy.registry_store import (
    SqlAlchemyStrategyRegistryStore,
    _decode_contract,
)
from trading_platform_api.validation import (
    QualificationGateV2,
    ValidationGateOutcomeV2,
    ValidationOutcomeV2,
)


def _v2_case():
    case = _positive_case()
    prior = case[3].version
    version = build_personal_spot_strategy_v2(
        prior,
        strategy_version_id=uuid4(),
        created_at=prior.created_at + timedelta(seconds=1),
    )
    strategy = replace(case[3], version=version)
    context = replace(case[4], strategy=strategy)
    from trading_platform_api.strategy import evaluate_strategy_conditions

    condition = evaluate_strategy_conditions(strategy, context)
    from test_strategy_eligibility import _evaluate

    eligibility = _evaluate(
        case[0],
        requested_strategy_version_id=version.strategy_version_id,
        strategy=strategy,
        condition_context=context,
        condition_evaluation=condition,
    )
    case = (*case[:3], strategy, context, condition, eligibility)
    candidate_result = _detect(
        case,
        requested_strategy_version_id=version.strategy_version_id,
        strategy=strategy,
        condition_context=context,
        condition_evaluation=condition,
        eligibility_evaluation=eligibility,
        now=case[1].manifest.created_at,
    )
    assert candidate_result.candidate is not None
    return case, strategy, version, candidate_result.candidate


def test_personal_spot_c021v2_rules_identity_and_schema_dispatch() -> None:
    _, _, version, candidate = _v2_case()
    assert version.semantic_version == "2.0.0"
    assert version.parent_version_id is not None
    assert version.schema_version == "2"
    assert version.content_sha256 == strategy_version_content_sha256(version)
    reversed_rules = InvalidationRuleSetV2(
        tuple(reversed(version.invalidation_rules.triggers)),
        version.invalidation_rules.combine,
    )
    assert reversed_rules == version.invalidation_rules
    assert (
        replace(version, invalidation_rules=reversed_rules).content_sha256
        == version.content_sha256
    )
    assert tuple(
        item.target_id for item in version.invalidation_rules.triggers
    ) == tuple(group.group_id for group in version.condition_groups)
    assert all(
        item.target_type is InvalidationTargetTypeV2.CONDITION_GROUP
        and item.trigger_truth is InvalidationTruthV2.FAIL
        for item in version.invalidation_rules.triggers
    )
    assert version.invalidation_rules.combine is InvalidationCombinationV2.ANY
    assert candidate.entry_concept.method.version == "2.0.0"
    assert candidate.entry_concept.method.content_sha256 == version.content_sha256
    assert (
        _decode_contract(serialize_contract(version, payload_version="wire-1"), "C-021")
        == version
    )
    document = serialize_contract(version, payload_version="wire-1")
    row = {
        "canonical_document": document,
        "strategy_version_id": version.strategy_version_id,
        "strategy_id": version.strategy_id,
        "semantic_version": version.semantic_version,
        "parent_version_id": version.parent_version_id,
        "created_at": version.created_at,
        "content_sha256": version.content_sha256,
        "document_sha256": contract_sha256(version, payload_version="wire-1"),
    }
    restored = SqlAlchemyStrategyRegistryStore._decode_version_row(object(), row)
    assert type(restored) is StrategyVersionV2
    assert restored == version
    unknown_schema = serialize_contract(version, payload_version="wire-1").replace(
        '"schema_version":"2"', '"schema_version":"3"', 1
    )
    with pytest.raises(Exception):
        _decode_contract(unknown_schema, "C-021")


def test_c070v1_codec_and_failed_v2_path_remain_distinct_from_signal() -> None:
    decoded = decode_signal_contract(
        serialize_contract(signal_v1(), payload_version="wire-1")
    )
    assert type(decoded) is Signal
    assert decoded.lifecycle.value == "QUALIFIED"

    case, _, _, candidate = _v2_case()
    package = _package(case, candidate=candidate)
    assert package.package is not None
    evaluated_at = candidate.created_at + timedelta(seconds=10)
    rule_input = request(
        candidate=candidate, evidence_package=package.package, evaluated_at=evaluated_at
    )
    failed_input = replace(
        rule_input,
        authoritative_gates=tuple(
            replace(gate, outcome=ValidationGateOutcomeV2.FAIL)
            if gate.gate is QualificationGateV2.OOS
            else gate
            for gate in rule_input.authoritative_gates
        ),
    )
    validation = evaluate_qualification_rules(failed_input)
    qualification = evaluate_signal_qualification_v2(
        candidate=candidate,
        evidence_package=package.package,
        validation=validation.validation,
        evaluated_at=evaluated_at + timedelta(seconds=1),
    )
    assert qualification.status is QualificationEngineStatus.NOT_QUALIFIED
    result = evaluate_no_trade_v2(
        market_context=case[2].market_context,
        setup=_detect(
            case,
            requested_strategy_version_id=candidate.strategy_version_id,
            now=candidate.created_at,
        ),
        eligibility=case[6],
        evidence_package=package,
        validation=validation,
        qualification=qualification,
        evaluated_at=evaluated_at + timedelta(seconds=2),
        correlation_id="wave4-v2-no-trade",
    )
    assert result.status is NoTradeEngineStatus.NO_TRADE
    assert result.decision is not None
    assert result.decision.schema_version == "2"
    assert NoTradeReasonV2.VALIDATION_FAILED in result.reasons
    with pytest.raises(ValueError):
        SignalV2.build(
            candidate=candidate,
            strategy=case[3].version,
            package=package.package,
            qualification=qualification.qualification,  # type: ignore[arg-type]
            market_context=case[2].market_context,
            now=evaluated_at + timedelta(seconds=2),
            signal_fields={
                "market_context_id": candidate.market_context_id,
                "analysis_snapshot_id": candidate.analysis_snapshot_id,
                "asset": candidate.asset,
                "instrument_id": candidate.instrument_id,
                "timeframe": candidate.timeframe,
                "direction": candidate.direction,
                "evidence_ids": candidate.supporting_evidence_ids,
                "data_quality_report_id": candidate.data_quality_report_id,
            },
        )


def test_c021v2_invalid_references_duplicates_and_empty_rules_fail_closed() -> None:
    _, _, version, _ = _v2_case()
    trigger = version.invalidation_rules.triggers[0]
    with pytest.raises(ValueError):
        InvalidationRuleSetV2((), InvalidationCombinationV2.ANY)
    with pytest.raises(ValueError):
        InvalidationRuleSetV2((trigger, trigger), InvalidationCombinationV2.ANY)
    unknown = replace(trigger, target_id=uuid4())
    with pytest.raises(ValueError):
        replace(
            version,
            invalidation_rules=InvalidationRuleSetV2(
                (unknown,), InvalidationCombinationV2.ANY
            ),
        )
    with pytest.raises(ValueError):
        InvalidationTriggerV2("GROUP", trigger.target_id, InvalidationTruthV2.FAIL)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        InvalidationTriggerV2(trigger.target_type, trigger.target_id, "UNKNOWN")  # type: ignore[arg-type]


def test_wave3_chain_and_c070v2_exact_lineage_from_personal_spot_v2() -> None:
    case, strategy, _, candidate = _v2_case()
    package_result = _package(case, candidate=candidate)
    assert package_result.package is not None
    package = package_result.package
    evaluated_at = candidate.created_at + timedelta(seconds=10)
    validation = evaluate_qualification_rules(
        request(
            candidate=candidate, evidence_package=package, evaluated_at=evaluated_at
        )
    )
    assert validation.outcome is ValidationOutcomeV2.PASS
    assert validation.validation is not None
    qualification = evaluate_signal_qualification_v2(
        candidate=candidate,
        evidence_package=package,
        validation=validation.validation,
        evaluated_at=evaluated_at + timedelta(seconds=1),
    )
    assert qualification.status is QualificationEngineStatus.QUALIFIED
    assert qualification.qualification is not None
    assert qualification.qualification.status.value == "QUALIFIED"
    result = SignalV2.build(
        candidate=candidate,
        strategy=strategy.version,
        package=package,
        qualification=qualification.qualification,
        market_context=case[2].market_context,
        now=evaluated_at + timedelta(seconds=2),
        signal_fields={
            "market_context_id": candidate.market_context_id,
            "analysis_snapshot_id": candidate.analysis_snapshot_id,
            "asset": candidate.asset,
            "instrument_id": candidate.instrument_id,
            "timeframe": candidate.timeframe,
            "direction": candidate.direction,
            "evidence_ids": candidate.supporting_evidence_ids,
            "data_quality_report_id": candidate.data_quality_report_id,
        },
    )
    repeat = SignalV2.build(
        candidate=candidate,
        strategy=strategy.version,
        package=package,
        qualification=qualification.qualification,
        market_context=case[2].market_context,
        now=evaluated_at + timedelta(seconds=2),
        signal_fields={
            "market_context_id": candidate.market_context_id,
            "analysis_snapshot_id": candidate.analysis_snapshot_id,
            "asset": candidate.asset,
            "instrument_id": candidate.instrument_id,
            "timeframe": candidate.timeframe,
            "direction": candidate.direction,
            "evidence_ids": candidate.supporting_evidence_ids,
            "data_quality_report_id": candidate.data_quality_report_id,
        },
    )
    assert result == repeat
    assert result.lineage.strategy_version.version == "2.0.0"
    assert (
        result.lineage.strategy_version.content_sha256
        == strategy.version.content_sha256
    )
    assert result.lineage.validation.version == "2"
    assert result.execution_authorized is False
    assert result.parameter_set == result.lineage.strategy_version
    assert result.configuration.artifact_type == "C-025-RULESET"
    assert (
        result.configuration.artifact_id
        == qualification.qualification.validation.rule_set.rule_set_id
    )
    assert (
        result.configuration.version
        == qualification.qualification.validation.rule_set.version
    )
    assert (
        result.configuration.content_sha256
        == qualification.qualification.validation.rule_set.content_sha256
    )
    assert result.regime_id == case[2].market_context.regime.regime_id
    assert result.conflict_ids == tuple(item.artifact_id for item in package.conflicts)
    assert result.uncertainty_ids == tuple(
        item.artifact_id for item in package.uncertainties
    )
    encoded = serialize_contract(result, payload_version="wire-1")
    assert decode_signal_contract(encoded) == result
    unsupported = encoded.replace('"schema_version":"2"', '"schema_version":"3"', 1)
    with pytest.raises(SignalCodecError):
        decode_signal_contract(unsupported)
    assert result.expires_at <= min(
        candidate.expires_at,
        package.expires_at,
        qualification.qualification.expires_at,
        qualification.qualification.validation.valid_until,
    )
    changed_package = _package(case, candidate=candidate).package
    assert changed_package is not None
    changed_validation = evaluate_qualification_rules(
        request(
            candidate=candidate,
            evidence_package=changed_package,
            evaluated_at=evaluated_at,
        )
    )
    assert changed_validation.validation is not None
    changed_qualification = evaluate_signal_qualification_v2(
        candidate=candidate,
        evidence_package=changed_package,
        validation=changed_validation.validation,
        evaluated_at=evaluated_at + timedelta(seconds=1),
    )
    assert changed_qualification.qualification is not None
    changed_signal = SignalV2.build(
        candidate=candidate,
        strategy=strategy.version,
        package=changed_package,
        qualification=changed_qualification.qualification,
        market_context=case[2].market_context,
        now=evaluated_at + timedelta(seconds=2),
        signal_fields={
            "market_context_id": candidate.market_context_id,
            "analysis_snapshot_id": candidate.analysis_snapshot_id,
            "asset": candidate.asset,
            "instrument_id": candidate.instrument_id,
            "timeframe": candidate.timeframe,
            "direction": candidate.direction,
            "evidence_ids": candidate.supporting_evidence_ids,
            "data_quality_report_id": candidate.data_quality_report_id,
        },
    )
    assert changed_signal.lineage.qualification_id != result.lineage.qualification_id
    assert changed_signal.signal_id != result.signal_id
