"""Synthetic live-recorder precommitment checks, never qualification evidence."""

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest
from test_qualification_study_v3 import inputs
from test_spot_oos import case, execute, freeze
from trading_platform_api.validation.oos_contracts_v2 import (
    OOSEventKind,
    OOSJournalSnapshot,
)
from trading_platform_api.validation.qualification_study_v3 import (
    QualificationDatasetPinV3,
    QualificationStudyProtocolV3,
)
from trading_platform_api.validation.spot_oos import (
    OOSResearchJournal,
    resolve_spot_oos_result,
)
from trading_platform_api.validation.spot_qualification_freeze import (
    freeze_spot_qualification_study,
    resolve_spot_qualification_freeze,
)


def setup(*, complete=True):
    request, metrics, journal, partitions = case(complete=complete)
    protocol = freeze(request, metrics, journal, partitions)
    candidate = protocol.candidates[0]
    values = dict(
        inputs(),
        strategy_version=candidate.strategy,
        parameter_set=candidate.parameters,
        cost_assumptions=candidate.costs,
        venue=protocol.window.venue,
        instrument_id=protocol.window.instrument_id,
        timeframe=protocol.window.timeframe,
        study_start=partitions[0].start,
        study_end=partitions[-1].end,
        frozen_at=journal._clock(),
        holdout_access_not_before=journal._clock(),
        valid_until=journal._clock() + timedelta(days=1),
        datasets=(
            QualificationDatasetPinV3(
                "synthetic-native-dataset-id",
                "revision-1",
                request.execution_dataset_sha256,
                request.execution_manifest_sha256,
                partitions[-1].start,
                partitions[-1].end,
                partitions[-1].point_in_time_cutoff,
            ),
        ),
    )
    return request, metrics, journal, protocol, values


def register(journal, protocol, study):
    return freeze_spot_qualification_study(
        journal=journal, protocol=protocol, study=study
    )


def resolve(journal, protocol, study):
    return resolve_spot_qualification_freeze(
        journal=journal, protocol=protocol, study=study
    )


def test_recorder_issues_one_exact_receipt_and_identical_retry_is_idempotent():
    _, _, journal, protocol, values = setup()
    study = QualificationStudyProtocolV3.build(**values)
    before = len(journal.snapshot.events)
    receipt = register(journal, protocol, study)
    assert receipt.recorded_at == journal._clock() == study.frozen_at
    assert receipt.evidence == (study.reference,)
    assert receipt.protocol_sha256 is None
    assert len(journal.snapshot.events) == before + 1
    journal.record_access(protocol.window)
    assert resolve(journal, protocol, study) == receipt
    after = journal.snapshot
    assert register(journal, protocol, study) == receipt
    assert journal.snapshot == after
    assert not study.qualification_authorized and not study.execution_authorized


def test_future_declared_freeze_time_is_rejected():
    _, _, journal, protocol, values = setup()
    now = journal._clock() + timedelta(seconds=2)
    journal._clock = lambda: now
    at = now + timedelta(seconds=1)
    study = QualificationStudyProtocolV3.build(
        **dict(values, frozen_at=at, holdout_access_not_before=at)
    )
    before = journal.snapshot
    with pytest.raises(ValueError, match="FREEZE_TIME_INVALID"):
        register(journal, protocol, study)
    assert journal.snapshot == before


def test_ticking_clock_records_actual_registration_not_the_earlier_content_time():
    _, _, journal, protocol, values = setup()
    study = QualificationStudyProtocolV3.build(**values)
    now = study.frozen_at + timedelta(microseconds=17)
    journal._clock = lambda: now
    receipt = register(journal, protocol, study)
    assert receipt.recorded_at == now > study.frozen_at
    journal.record_access(protocol.window)
    assert resolve(journal, protocol, study) == receipt
    journal._clock = lambda: study.frozen_at + timedelta(microseconds=1)
    with pytest.raises(ValueError, match="CLOCK_REVERSED"):
        resolve(journal, protocol, study)


@pytest.mark.parametrize(
    "kind", [OOSEventKind.ACCESS, OOSEventKind.TRIAL, OOSEventKind.RESULT]
)
def test_any_prior_overlapping_attempt_blocks_registration_even_at_same_time(kind):
    _, _, journal, protocol, values = setup()
    journal._append(kind, protocol.window, purpose="PRIOR_ATTEMPT")
    before = journal.snapshot
    with pytest.raises(ValueError, match="ALREADY_ACCESSED"):
        register(journal, protocol, QualificationStudyProtocolV3.build(**values))
    assert journal.snapshot == before


def test_changed_policy_cannot_replace_registration_before_or_after_access():
    _, _, journal, protocol, values = setup()
    study = QualificationStudyProtocolV3.build(**values)
    register(journal, protocol, study)
    changed = QualificationStudyProtocolV3.build(
        **dict(values, policy=replace(study.policy, minimum_raw_sample=50))
    )
    for _ in range(2):
        before = journal.snapshot
        with pytest.raises(ValueError, match="ALREADY_FROZEN"):
            register(journal, protocol, changed)
        assert journal.snapshot == before
        journal.record_access(protocol.window)


def test_clock_reversal_after_access_cannot_resolve_or_retry_registration():
    _, _, journal, protocol, values = setup()
    study = QualificationStudyProtocolV3.build(**values)
    receipt = register(journal, protocol, study)
    accessed_at = study.frozen_at + timedelta(seconds=10)
    journal._clock = lambda: accessed_at
    journal.record_access(protocol.window)
    assert resolve(journal, protocol, study) == receipt
    # The clock remains after registration but before an event it now verifies.
    journal._clock = lambda: study.frozen_at + timedelta(seconds=5)
    before = journal.snapshot
    with pytest.raises(ValueError, match="CLOCK_REVERSED"):
        resolve(journal, protocol, study)
    with pytest.raises(ValueError, match="CLOCK_REVERSED"):
        register(journal, protocol, study)
    assert journal.snapshot == before


def test_copied_valid_history_does_not_restore_trusted_registration():
    _, _, journal, protocol, values = setup()
    study = QualificationStudyProtocolV3.build(**values)
    register(journal, protocol, study)
    copied = OOSResearchJournal(
        journal_id=journal.snapshot.journal_id,
        authority=journal.snapshot.authority,
        clock=journal._clock,
        declared_complete=True,
        prior_history=journal.snapshot.events,
    )
    # Even restoring the existing OOS protocol is insufficient to authenticate
    # the new qualification policy registration from a supplied event/hash.
    copied._protocols[protocol.content_sha256] = protocol
    with pytest.raises(ValueError, match="UNAUTHENTICATED"):
        resolve(copied, protocol, study)


def test_rehashed_study_cannot_hide_an_invalid_nested_method_reference():
    _, _, journal, protocol, values = setup()
    method = replace(values["policy"].uncertainty_method)
    object.__setattr__(method, "artifact_id", "not-a-uuid")
    altered_policy = replace(values["policy"], uncertainty_method=method)
    # The outer content hash alone does not validate the entire nested tree.
    study = QualificationStudyProtocolV3.build(**dict(values, policy=altered_policy))
    before = journal.snapshot
    with pytest.raises((TypeError, ValueError)):
        register(journal, protocol, study)
    assert journal.snapshot == before


def test_access_in_another_window_does_not_invalidate_heldout_precommitment():
    _, _, journal, protocol, values = setup()
    study = QualificationStudyProtocolV3.build(**values)
    receipt = register(journal, protocol, study)
    journal.record_access(
        replace(
            protocol.window,
            start=protocol.partitions[0].start,
            end=protocol.partitions[0].end,
        )
    )
    assert resolve(journal, protocol, study) == receipt


def test_missing_receipt_and_early_access_are_rejected_on_resolution():
    _, _, journal, protocol, values = setup()
    study = QualificationStudyProtocolV3.build(
        **dict(
            values, holdout_access_not_before=journal._clock() + timedelta(seconds=1)
        )
    )
    receipt = register(journal, protocol, study)
    journal.record_access(protocol.window)
    with pytest.raises(ValueError, match="ACCESS_ORDER_INVALID"):
        resolve(journal, protocol, study)
    journal._snapshot = OOSJournalSnapshot(
        journal.snapshot.journal_id,
        journal.snapshot.authority,
        journal.snapshot.declared_complete,
        journal.snapshot.events[: receipt.sequence],
    )
    with pytest.raises(ValueError, match="RECEIPT_MISMATCH"):
        resolve(journal, protocol, study)


@pytest.mark.parametrize("elapsed", [-1, 86400])
def test_expiry_and_clock_reversal_do_not_reuse_an_earlier_receipt(elapsed):
    _, _, journal, protocol, values = setup()
    study = QualificationStudyProtocolV3.build(**values)
    register(journal, protocol, study)
    journal._clock = lambda: study.frozen_at + timedelta(seconds=elapsed)
    with pytest.raises(ValueError, match="EXPIRED_OR_CLOCK_REVERSED"):
        resolve(journal, protocol, study)


@pytest.mark.parametrize(
    "field", ["venue", "instrument_id", "timeframe", "parameter_set"]
)
def test_valid_but_mismatched_protocol_scope_is_rejected(field):
    _, _, journal, protocol, values = setup()
    changes = {
        "venue": "another-spot-provider",
        "instrument_id": "ETH-USDT-SPOT",
        "timeframe": "1h",
        "parameter_set": inputs()["parameter_set"],
    }
    with pytest.raises(ValueError, match="SCOPE_MISMATCH|CANDIDATE_MISMATCH"):
        register(
            journal,
            protocol,
            QualificationStudyProtocolV3.build(
                **dict(values, **{field: changes[field]})
            ),
        )


def test_freeze_during_inflight_run_is_rejected_without_mutation():
    _, _, journal, protocol, values = setup()
    journal._inflight.add("synthetic-running-request")
    before = journal.snapshot
    with pytest.raises(ValueError, match="RUN_IN_PROGRESS"):
        register(journal, protocol, QualificationStudyProtocolV3.build(**values))
    assert journal.snapshot == before


def test_existing_oos_result_still_resolves_with_qualification_receipt():
    request, metrics, journal, protocol, values = setup(complete=False)
    study = QualificationStudyProtocolV3.build(**values)
    receipt = register(journal, protocol, study)
    bundle = asyncio.run(execute(request, metrics, journal, protocol))
    assert bundle.result is not None
    assert resolve_spot_oos_result(bundle, journal=journal) == bundle.result
    assert bundle.result.outcome.value == "INCONCLUSIVE"
    assert receipt in bundle.result.journal.events
    assert resolve(journal, protocol, study) == receipt
    # Recorder authentication does not turn incomplete history into evidence.
    assert "JOURNAL_COMPLETENESS_UNPROVEN" in bundle.reason_codes
