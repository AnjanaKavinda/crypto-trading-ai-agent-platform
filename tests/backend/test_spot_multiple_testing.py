"""C-105 records exact supplied OOS journal attempts without correction or ranking."""

import asyncio
import json
from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from test_spot_oos import case, execute, freeze
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.lineage.codec import LineageError, decode, encode, key_for
from trading_platform_api.lineage.store import references
from trading_platform_api.risk import ContractReference
from trading_platform_api.validation.oos_contracts_v2 import (
    OOSEventKind,
    OOSSelectionMode,
    OOSWindow,
)
from trading_platform_api.validation.multiple_testing_contracts_v1 import (
    BestValidationObservation,
    CandidateHypothesisMapping,
    MultipleTestingOutcome,
)
from trading_platform_api.validation.spot_multiple_testing import (
    freeze_spot_multiple_testing_plan,
    observe_spot_multiple_testing,
)


def _hypothesis_refs():
    return (ContractReference("C-048", UUID(int=1), "1", "1" * 64),)


def _protocol_case():
    request, metrics, journal, partitions = case(complete=False)
    protocol = freeze(request, metrics, journal, partitions)
    return request, metrics, journal, partitions, protocol


def build_observation_result():
    request, metrics, journal, _, protocol = _protocol_case()
    freeze_spot_multiple_testing_plan(
        journal=journal, protocol=protocol, hypothesis_refs=_hypothesis_refs()
    )
    oos = asyncio.run(execute(request, metrics, journal, protocol))
    return observe_spot_multiple_testing(
        journal=journal, protocol=protocol, bundle=oos
    )


def test_fixed_plan_allows_zero_development_trials_and_is_observation_only():
    request, metrics, journal, _, protocol = _protocol_case()
    before = journal.snapshot
    plan = freeze_spot_multiple_testing_plan(
        journal=journal, protocol=protocol, hypothesis_refs=_hypothesis_refs()
    )
    assert journal.snapshot == before
    assert plan.journal_prefix_length == len(before.events)
    assert plan.journal_prefix_sha256 == canonical_sha256(
        tuple(event.content_sha256 for event in before.events)
    )
    assert plan.correction_status == "NOT_APPLIED"
    assert plan.interpretation == "UNADJUSTED_DESCRIPTIVE_ONLY"

    oos = asyncio.run(execute(request, metrics, journal, protocol))
    before_observation = journal.snapshot
    result = observe_spot_multiple_testing(
        journal=journal, protocol=protocol, bundle=oos
    )

    assert journal.snapshot == before_observation
    assert oos.result is not None
    assert oos.result.outcome.value == "INCONCLUSIVE"
    assert result.attempted_trial_count == 0
    assert [event.kind for event in result.observed_events] == [OOSEventKind.RESULT]
    assert result.observed_events[0].evidence == (oos.result.request_reference,)
    assert not any(
        reference.artifact_type in {"C-027", "SPOT_PERFORMANCE_REPORT"}
        for event in result.observed_events
        for reference in event.evidence
    )
    assert result.oos_result == oos.result
    assert result.outcome is MultipleTestingOutcome.INCONCLUSIVE
    assert result.counts.protocol_count == 1
    assert result.counts.unique_strategy_count == 1
    assert result.counts.unique_configuration_count == 1
    assert result.counts.unique_hypothesis_count == 1
    assert result.counts.development_trial_count == 0
    assert result.counts.held_out_result_count == sum(
        run.partition_id == plan.held_out_partition_id for run in oos.result.runs
    )
    assert result.selected_candidate_id == protocol.candidates[0].candidate_id
    assert result.rejected_candidate_ids == ()
    assert result.best_validation_observation == BestValidationObservation(
        None, None, None, "FIXED_PROTOCOL_HAS_NO_OPTIMIZATION_SELECTION"
    )
    assert result.preserved_terminal_attempts == result.observed_events
    assert result.correction_status == "NOT_APPLIED"
    assert result.interpretation == "UNADJUSTED_DESCRIPTIVE_ONLY"
    assert decode(encode(result)) == result
    assert key_for(result).contract_id == "C-105"
    with pytest.raises(LineageError, match="retention is not authorized"):
        references(result)


def test_holdout_access_violation_is_preserved_as_failed_not_relabelled_observed():
    request, metrics, journal, partitions, protocol = _protocol_case()
    freeze_spot_multiple_testing_plan(
        journal=journal, protocol=protocol, hypothesis_refs=_hypothesis_refs()
    )
    heldout = partitions[-1]
    journal._append(
        OOSEventKind.ACCESS,
        OOSWindow(
            protocol.window.venue,
            protocol.window.instrument_id,
            protocol.window.timeframe,
            heldout.start,
            heldout.end,
        ),
        protocol=protocol,
        candidate=protocol.candidates[0],
        purpose="UNDECLARED_HELD_OUT_ACCESS",
    )
    oos = asyncio.run(execute(request, metrics, journal, protocol))
    result = observe_spot_multiple_testing(
        journal=journal, protocol=protocol, bundle=oos
    )
    assert result.outcome is MultipleTestingOutcome.FAILED
    assert any(
        event.purpose == "UNDECLARED_HELD_OUT_ACCESS"
        for event in result.preserved_terminal_attempts
    )


def test_post_result_holdout_access_is_included_and_fails_assessment():
    request, metrics, journal, partitions, protocol = _protocol_case()
    freeze_spot_multiple_testing_plan(
        journal=journal, protocol=protocol, hypothesis_refs=_hypothesis_refs()
    )
    oos = asyncio.run(execute(request, metrics, journal, protocol))
    heldout = partitions[-1]
    journal.record_access(
        OOSWindow(
            protocol.window.venue,
            protocol.window.instrument_id,
            protocol.window.timeframe,
            heldout.start,
            heldout.end,
        ),
        purpose="POST_RESULT_HOLDOUT_INSPECTION",
    )

    assessment = observe_spot_multiple_testing(
        journal=journal, protocol=protocol, bundle=oos
    )

    assert assessment.outcome is MultipleTestingOutcome.FAILED
    assert any(
        event.purpose == "POST_RESULT_HOLDOUT_INSPECTION"
        for event in assessment.preserved_terminal_attempts
    )


def test_missing_development_selection_is_inconclusive_not_rejected_or_holdout_ranked():
    request, metrics, journal, partitions = case(complete=False)
    protocol = freeze(
        request,
        metrics,
        journal,
        partitions,
        selection_mode=OOSSelectionMode.VALIDATION_NET_PROFIT,
    )
    freeze_spot_multiple_testing_plan(
        journal=journal, protocol=protocol, hypothesis_refs=_hypothesis_refs()
    )
    oos = asyncio.run(execute(request, metrics, journal, protocol))
    result = observe_spot_multiple_testing(
        journal=journal, protocol=protocol, bundle=oos
    )
    assert result.outcome is MultipleTestingOutcome.INCONCLUSIVE
    assert result.selected_candidate_id is None
    assert result.rejected_candidate_ids == ()
    assert result.best_validation_observation.evidence_reference is None


def test_freeze_rejects_prior_scoped_data_access_and_does_not_change_journal():
    _, _, journal, _, protocol = _protocol_case()
    journal.record_access(protocol.window, purpose="INSPECTION")
    before = journal.snapshot

    with pytest.raises(ValueError, match="MULTIPLE_TESTING_PLAN_AFTER_SCOPED_ACCESS"):
        freeze_spot_multiple_testing_plan(
            journal=journal, protocol=protocol, hypothesis_refs=_hypothesis_refs()
        )

    assert journal.snapshot == before


def test_freeze_rejects_empty_hypothesis_set():
    _, _, journal, _, protocol = _protocol_case()

    with pytest.raises(ValueError, match="MULTIPLE_TESTING_HYPOTHESES_REQUIRED"):
        freeze_spot_multiple_testing_plan(journal=journal, protocol=protocol)


def test_plan_freezes_typed_hypothesis_refs_and_candidate_mapping():
    _, _, journal, partitions, protocol = _protocol_case()
    hypothesis = ContractReference("C-048", uuid4(), "1", "1" * 64)
    plan = freeze_spot_multiple_testing_plan(
        journal=journal, protocol=protocol, hypothesis_refs=(hypothesis,)
    )
    assert plan.candidate_hypothesis_map == (
        CandidateHypothesisMapping(protocol.candidates[0].candidate_id, (hypothesis,)),
    )
    assert (
        plan.candidate_configurations[0].candidate_id
        == protocol.candidates[0].candidate_id
    )
    assert plan.selection_policy is protocol.selection_mode
    assert plan.metrics_policy_sha256 == protocol.metrics_policy_sha256
    assert plan.validation_partition_id == partitions[1].partition_id
    assert len(plan.candidate_hypothesis_map[0].hypothesis_refs) == 1


def test_c105_codec_uses_closed_schema_dispatch():
    result = build_observation_result()
    envelope = json.loads(encode(result))
    envelope["schema_version"] = "2"
    with pytest.raises(LineageError, match="corrupt"):
        decode(json.dumps(envelope))


def test_assessment_identity_and_round_trip_are_deterministic_for_exact_inputs():
    request, metrics, journal, _, protocol = _protocol_case()
    plan = freeze_spot_multiple_testing_plan(
        journal=journal, protocol=protocol, hypothesis_refs=_hypothesis_refs()
    )
    oos = asyncio.run(execute(request, metrics, journal, protocol))
    first = observe_spot_multiple_testing(
        journal=journal, protocol=protocol, bundle=oos
    )
    second = observe_spot_multiple_testing(
        journal=journal, protocol=protocol, bundle=oos
    )
    assert first == second
    assert decode(encode(first)) == first
    assert first.content_sha256 == second.content_sha256
    assert first.plan == plan


def test_observer_rejects_substituted_or_missing_exact_oos_result():
    request, metrics, journal, _, protocol = _protocol_case()
    freeze_spot_multiple_testing_plan(
        journal=journal, protocol=protocol, hypothesis_refs=_hypothesis_refs()
    )
    oos = asyncio.run(execute(request, metrics, journal, protocol))
    with pytest.raises(ValueError):
        observe_spot_multiple_testing(
            journal=journal, protocol=protocol, bundle=replace(oos, result=None)
        )
    with pytest.raises(ValueError):
        observe_spot_multiple_testing(
            journal=journal,
            protocol=protocol,
            bundle=replace(oos, reason_codes=("SUBSTITUTED",)),
        )
