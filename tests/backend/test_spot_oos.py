"""Synthetic recorded-research protocol checks; no profitability claims."""

import asyncio
import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4, uuid5

import pytest
from test_spot_execution import fixture, production_cost_case
from test_spot_replay_inputs import T, _case
from test_validation_contracts import oos as legacy_oos
from trading_platform_api.config import DeploymentEnvironment
from trading_platform_api.contracts.serialization import (
    canonical_json_dumps,
    canonical_sha256,
    serialize_contract,
)
from trading_platform_api.lineage.codec import LineageError, decode, encode, key_for
from trading_platform_api.lineage.store import references
from trading_platform_api.strategy.qualification_rules import _gate_reference_supported
from trading_platform_api.validation.contracts import (
    CheckOutcome,
    DataPartition,
    PartitionPurpose,
)
from trading_platform_api.validation.contracts_v2 import (
    QualificationGateV2,
    ValidationArtifactReferenceV2,
)
from trading_platform_api.validation.oos_contracts_v2 import (
    MAX_EVENTS,
    OOSEventKind,
    OOSJournalEvent,
    OOSOutcome,
    OOSResultV2,
    OOSSelectionMode,
    OOSWindow,
    payload,
    result_receipt_purpose,
)
from trading_platform_api.validation.oos_contracts_v2 import (
    METHOD as OOS_METHOD,
)
from trading_platform_api.validation.oos_contracts_v2 import (
    NAMESPACE as OOS_NAMESPACE,
)
from trading_platform_api.validation.spot_backtest import (
    SpotBacktestArchivePin,
    SpotBacktestBundle,
    SpotBacktestOutcome,
    SpotBacktestParameters,
    SpotBacktestRunRequest,
)
from trading_platform_api.validation.spot_metrics import METHOD, MetricsPolicy
from trading_platform_api.validation.spot_oos import (
    OOSResearchJournal,
    candidate_from_request,
    freeze_spot_oos_protocol,
    resolve_spot_oos_result,
    run_spot_oos,
    run_spot_oos_partition,
    select_spot_oos_candidate,
)

D = Decimal
STEP = timedelta(minutes=1)


@pytest.fixture(autouse=True)
def forbid_unexpected_replay(monkeypatch):
    async def forbidden(**kwargs):
        pytest.fail("unexpected replay; negative preflight must prevent holdout access")

    monkeypatch.setattr(
        "trading_platform_api.validation.spot_oos.run_spot_backtest", forbidden
    )


def case(*, complete=True):
    inputs, _, resolved, _, _ = _case()
    simulation = production_cost_case(dict(fixture(), strategy=resolved.version))
    policy = simulation["policy"]
    parameters = SpotBacktestParameters(
        resolved.version.strategy_version_id,
        resolved.version.content_sha256,
        D("1"),
        STEP,
        STEP,
        STEP,
        1,
        "EXIT_FILLED_QUANTITY_AFTER_LAST_FILL_V1",
    )
    pins = tuple(
        SpotBacktestArchivePin(
            uuid4(), "a" * 64, "b" * 64, uuid4(), "c" * 64, uuid4(), "d" * 64, "e" * 64
        )
        for _ in inputs.decisions
    )
    request = SpotBacktestRunRequest(
        inputs,
        pins,
        simulation["data"].dataset_sha256,
        simulation["data"].manifest_sha256,
        policy,
        parameters,
        simulation["cost_assumptions"],
        simulation["cost_adapter"],
        policy.period_end,
        T + 10 * STEP,
        T + timedelta(days=1),
    )
    metric_policy = MetricsPolicy(
        METHOD,
        "1",
        "USDT",
        "BAR_CLOSE",
        60,
        D(525600),
        D(0),
        D(0),
        1,
        2,
        request.created_at,
    )
    operational_time = T + timedelta(hours=2)
    journal = OOSResearchJournal(
        journal_id=uuid4(),
        authority=ValidationArtifactReferenceV2(
            "SYNTHETIC_RESEARCH_RECORDER", uuid4(), "1", "f" * 64
        ),
        clock=lambda: operational_time,
        declared_complete=complete,
    )
    partitions = (
        DataPartition(
            uuid4(),
            PartitionPurpose.TRAIN,
            T - 20 * STEP,
            T - 10 * STEP,
            T - 10 * STEP,
            True,
        ),
        DataPartition(uuid4(), PartitionPurpose.VALIDATION, T - 10 * STEP, T, T, False),
        DataPartition(
            uuid4(),
            PartitionPurpose.TEST,
            T,
            policy.period_end,
            policy.period_end,
            False,
        ),
    )
    return request, metric_policy, journal, partitions


def freeze(request, metrics, journal, partitions, **changes):
    p = request.execution_policy
    values = dict(
        journal=journal,
        window=OOSWindow(
            p.venue, p.instrument_id, p.timeframe, p.period_start, p.period_end
        ),
        partitions=partitions,
        candidates=(candidate_from_request(request),),
        selection_mode=OOSSelectionMode.FIXED,
        metrics_policy=metrics,
        warmup_bars=32,
        embargo_seconds=0,
        mark_equity=True,
        environment=DeploymentEnvironment.TEST,
    )
    return freeze_spot_oos_protocol(**dict(values, **changes))


async def execute(request, metrics, journal, protocol, **changes):
    return await run_spot_oos(
        journal=journal,
        protocol=protocol,
        request=request,
        metrics_policy=metrics,
        session=object(),
        strategy_registry=object(),
        lineage_store=object(),
        as_of=changes.get("as_of", request.result_as_of),
        expires_at=changes.get("expires_at", request.expires_at),
    )


@pytest.mark.parametrize(
    "change", ["overlap", "empty", "embargo", "grid", "holdout_optimization"]
)
def test_invalid_partitions_and_roles_are_rejected(change):
    request, metrics, journal, parts = case()
    if change == "overlap":
        parts = (parts[0], replace(parts[1], start=parts[0].end - STEP), parts[2])
    elif change == "empty":
        parts = (replace(parts[0], end=parts[0].start), *parts[1:])
    elif change == "grid":
        parts = (
            replace(parts[0], start=parts[0].start + timedelta(seconds=1)),
            *parts[1:],
        )
    elif change == "holdout_optimization":
        with pytest.raises(ValueError):
            replace(parts[-1], used_for_optimization=True)
        return
    with pytest.raises(ValueError):
        freeze(
            request,
            metrics,
            journal,
            parts,
            embargo_seconds=1 if change == "embargo" else 0,
        )


def test_incomplete_history_is_inconclusive_and_not_a_clean_holdout(monkeypatch):
    request, metrics, journal, parts = case(complete=False)
    protocol = freeze(request, metrics, journal, parts)

    bundle = asyncio.run(execute(request, metrics, journal, protocol))
    assert bundle.outcome is OOSOutcome.INCONCLUSIVE
    assert bundle.result.contamination is CheckOutcome.INCONCLUSIVE
    assert bundle.result.integrity is CheckOutcome.INCONCLUSIVE
    assert "JOURNAL_COMPLETENESS_UNPROVEN" in bundle.reason_codes
    assert bundle.result.sample_size == 0 and bundle.result.metrics == ()
    assert resolve_spot_oos_result(bundle, journal=journal) == bundle.result
    assert asyncio.run(execute(request, metrics, journal, protocol)) == bundle
    altered = dict(
        bundle.result.identity_payload(), outcome=OOSOutcome.OBSERVED, reason_codes=()
    )
    with pytest.raises(ValueError):
        OOSResultV2.build(
            **{
                k: v
                for k, v in altered.items()
                if k
                not in {"method", "contract_id", "schema_version", "operating_mode"}
            }
        )


def test_missing_selection_receipt_is_inconclusive_before_holdout_access(monkeypatch):
    request, metrics, journal, parts = case()
    protocol = freeze(
        request,
        metrics,
        journal,
        parts,
        selection_mode=OOSSelectionMode.VALIDATION_NET_PROFIT,
    )

    bundle = asyncio.run(execute(request, metrics, journal, protocol))
    assert bundle.outcome is OOSOutcome.INCONCLUSIVE
    assert bundle.result.contamination is CheckOutcome.INCONCLUSIVE
    assert "EXACT_SELECTION_RECEIPT_UNRESOLVED" in bundle.reason_codes
    assert "OOS_REQUEST_NOT_SELECTED_STRATEGY" not in bundle.reason_codes
    assert not bundle.replays
    assert [event.kind for event in journal.snapshot.events] == [
        OOSEventKind.FREEZE,
        OOSEventKind.RESULT,
    ]
    assert resolve_spot_oos_result(bundle, journal=journal) == bundle.result


def test_canonical_v1_compatibility_v2_zero_samples_and_closed_dispatch():
    old = legacy_oos()
    assert encode(old) == serialize_contract(old, payload_version="wire-1")
    assert decode(encode(old)) == old
    request, metrics, journal, parts = case(complete=False)
    protocol = freeze(request, metrics, journal, parts)
    bundle = asyncio.run(execute(request, metrics, journal, protocol))
    result = bundle.result
    assert decode(encode(result)) == result
    assert key_for(result).version == "2"
    for version in ("0", "3", "999"):
        raw = json.loads(encode(result))
        raw["schema_version"] = version
        with pytest.raises(LineageError):
            decode(json.dumps(raw))
    with pytest.raises(LineageError, match="retention"):
        references(result)
    with pytest.raises(LineageError, match="retention"):
        references(old)
    assert not _gate_reference_supported(
        QualificationGateV2.OOS,
        ValidationArtifactReferenceV2(
            "C-071", result.result_id, "2", result.content_sha256
        ),
    )


@pytest.mark.parametrize("partition_index", (0, 1, 2))
def test_development_cutoff_cannot_reveal_a_later_partition(partition_index):
    request, metrics, journal, parts = case()
    altered = list(parts)
    altered[partition_index] = replace(
        altered[partition_index],
        point_in_time_cutoff=altered[partition_index].end + STEP,
    )
    with pytest.raises(ValueError, match="DEVELOPMENT_CUTOFF_EXCEEDS_PARTITION"):
        freeze(request, metrics, journal, tuple(altered))


def test_selection_rejects_empty_or_untyped_trial_evidence():
    request, metrics, journal, parts = case()
    candidate = candidate_from_request(request)
    protocol = freeze(
        request,
        metrics,
        journal,
        parts,
        selection_mode=OOSSelectionMode.VALIDATION_NET_PROFIT,
    )
    with pytest.raises(ValueError, match="INCOMPLETE_SELECTION_HISTORY"):
        select_spot_oos_candidate(
            journal=journal, protocol=protocol, candidate_id=candidate.candidate_id
        )
    event = journal._append(
        OOSEventKind.TRIAL,
        OOSWindow(
            protocol.window.venue,
            protocol.window.instrument_id,
            protocol.window.timeframe,
            parts[0].start,
            parts[0].end,
        ),
        protocol=protocol,
        candidate=candidate,
        purpose="TRAIN",
    )
    journal._trials[event.content_sha256] = (None, object())
    before = journal.snapshot
    with pytest.raises(ValueError, match="UNRESOLVED_TRIAL_EVIDENCE"):
        select_spot_oos_candidate(
            journal=journal, protocol=protocol, candidate_id=candidate.candidate_id
        )
    assert journal.snapshot == before


@pytest.mark.parametrize("expired", [False, True])
def test_expiry_is_rejected_before_holdout_access(expired):
    request, metrics, journal, parts = case()
    protocol = freeze(request, metrics, journal, parts)
    before = journal.snapshot
    expiry = protocol.frozen_at if expired else request.expires_at + STEP
    with pytest.raises(ValueError, match="OOS_EXPIRY"):
        asyncio.run(execute(request, metrics, journal, protocol, expires_at=expiry))
    assert journal.snapshot == before


@pytest.mark.parametrize("complete", [True, False])
def test_as_of_mismatch_is_rejected_before_any_holdout_access(monkeypatch, complete):
    request, metrics, journal, parts = case(complete=complete)
    protocol = freeze(request, metrics, journal, parts)
    before = journal.snapshot

    with pytest.raises(ValueError, match="OOS_AS_OF_REQUEST_MISMATCH"):
        asyncio.run(
            execute(
                request, metrics, journal, protocol, as_of=request.result_as_of - STEP
            )
        )
    assert journal.snapshot == before


def test_inconclusive_readback_binds_original_request_and_as_of():
    request, metrics, journal, parts = case(complete=False)
    protocol = freeze(request, metrics, journal, parts)
    bundle = asyncio.run(execute(request, metrics, journal, protocol))
    assert bundle.result.as_of == request.result_as_of
    with pytest.raises(ValueError, match="OOS_AS_OF_REQUEST_MISMATCH"):
        resolve_spot_oos_result(
            replace(
                bundle,
                request=replace(request, result_as_of=request.result_as_of - STEP),
            ),
            journal=journal,
        )
    with pytest.raises(ValueError, match="OOS_REQUEST_RECEIPT_MISMATCH"):
        resolve_spot_oos_result(
            replace(
                bundle, request=replace(request, execution_manifest_sha256="f" * 64)
            ),
            journal=journal,
        )


def _self_consistent_forged_wire(result, **changes):
    values = dict(result.identity_payload(), **changes)
    preimage = dict(
        values,
        method=OOS_METHOD,
        contract_id="C-071",
        schema_version="2",
        operating_mode=result.operating_mode,
    )
    digest = canonical_sha256(preimage)
    raw = json.loads(encode(result))
    for key, value in changes.items():
        raw["payload"][key] = json.loads(canonical_json_dumps(value))
    raw["payload"]["content_sha256"] = digest
    raw["payload"]["result_id"] = str(uuid5(OOS_NAMESPACE, "result:" + digest))
    return json.dumps(raw)


def test_non_observed_codec_rejects_self_consistent_status_forgeries(monkeypatch):
    request, metrics, incomplete, parts = case(complete=False)
    protocol = freeze(request, metrics, incomplete, parts)
    inconclusive = asyncio.run(execute(request, metrics, incomplete, protocol)).result
    assert inconclusive.outcome is OOSOutcome.INCONCLUSIVE
    for change in (
        {"contamination": CheckOutcome.PASSED},
        {"integrity": CheckOutcome.PASSED},
    ):
        with pytest.raises(LineageError):
            decode(_self_consistent_forged_wire(inconclusive, **change))

    request, metrics, contaminated, parts = case()
    protocol = freeze(request, metrics, contaminated, parts)
    contaminated.record_access(protocol.window, purpose="FINAL_HOLDOUT_INSPECTION")
    failed = asyncio.run(execute(request, metrics, contaminated, protocol)).result
    assert failed.outcome is OOSOutcome.FAILED
    with pytest.raises(LineageError):
        decode(_self_consistent_forged_wire(failed, contamination=CheckOutcome.PASSED))
    substituted_reasons = ("SELECTION_CHANGED_AFTER_FREEZE",)
    terminal = failed.journal.events[-1]
    altered_terminal = OOSJournalEvent.build(
        **dict(
            payload(terminal, {"content_sha256", "purpose"}),
            purpose=result_receipt_purpose(
                failed.outcome,
                failed.contamination,
                failed.integrity,
                failed.sample_sufficiency,
                substituted_reasons,
            ),
        )
    )
    altered_journal = replace(
        failed.journal, events=(*failed.journal.events[:-1], altered_terminal)
    )
    with pytest.raises(LineageError):
        decode(
            _self_consistent_forged_wire(
                failed,
                journal=altered_journal,
                reason_codes=substituted_reasons,
            )
        )
    with pytest.raises(LineageError):
        decode(
            _self_consistent_forged_wire(
                failed,
                reason_codes=tuple(
                    sorted((*failed.reason_codes, "INVALID_OOS_BACKTEST_REQUEST"))
                ),
            )
        )

    request, metrics, missing, parts = case()
    protocol = freeze(request, metrics, missing, parts)

    async def unavailable(**kwargs):
        return SpotBacktestBundle(
            SpotBacktestOutcome.INCONCLUSIVE,
            ("ARCHIVE_UNAVAILABLE",),
            None,
            None,
            None,
            None,
            (),
        )

    monkeypatch.setattr(
        "trading_platform_api.validation.spot_oos.run_spot_backtest", unavailable
    )
    unresolved = asyncio.run(execute(request, metrics, missing, protocol)).result
    assert unresolved.outcome is OOSOutcome.INCONCLUSIVE
    with pytest.raises(LineageError):
        decode(_self_consistent_forged_wire(unresolved, integrity=CheckOutcome.PASSED))


@pytest.mark.parametrize("complete", (True, False))
def test_contamination_preserves_independent_integrity_state(complete):
    request, metrics, journal, parts = case(complete=complete)
    protocol = freeze(request, metrics, journal, parts)
    journal.record_access(protocol.window, purpose="FINAL_HOLDOUT_INSPECTION")
    if complete:
        request = replace(
            request,
            execution_policy=replace(
                request.execution_policy, initial_inventory=D("1")
            ),
        )

    result = asyncio.run(execute(request, metrics, journal, protocol)).result

    assert result.outcome is OOSOutcome.FAILED
    assert result.contamination is CheckOutcome.FAILED
    assert result.integrity is (
        CheckOutcome.FAILED if complete else CheckOutcome.INCONCLUSIVE
    )
    assert decode(encode(result)) == result


def test_recorded_reselection_produces_resolvable_failed_result():
    request, metrics, journal, parts = case()
    protocol = freeze(request, metrics, journal, parts)
    select_spot_oos_candidate(
        journal=journal,
        protocol=protocol,
        candidate_id=protocol.candidates[0].candidate_id,
    )

    bundle = asyncio.run(execute(request, metrics, journal, protocol))

    assert bundle.outcome is OOSOutcome.FAILED
    assert bundle.result.contamination is CheckOutcome.FAILED
    assert "SELECTION_CHANGED_AFTER_FREEZE" in bundle.reason_codes
    assert resolve_spot_oos_result(bundle, journal=journal) == bundle.result


@pytest.mark.parametrize(("inventory", "cash"), ((D("1"), D("100")), (D("0"), D("0"))))
def test_invalid_initial_capital_produces_resolvable_failed_result(inventory, cash):
    request, metrics, journal, parts = case()
    protocol = freeze(request, metrics, journal, parts)
    request = replace(
        request,
        execution_policy=replace(
            request.execution_policy,
            initial_inventory=inventory,
            initial_cash=cash,
        ),
    )

    bundle = asyncio.run(execute(request, metrics, journal, protocol))

    assert bundle.outcome is OOSOutcome.FAILED
    assert bundle.result.integrity is CheckOutcome.FAILED
    assert "OOS_REQUIRES_FLAT_POSITIVE_CAPITAL" in bundle.reason_codes
    assert resolve_spot_oos_result(bundle, journal=journal) == bundle.result


@pytest.mark.parametrize("change", ("remove", "replace", "duplicate", "wrong_type"))
def test_no_run_codec_rejects_terminal_request_receipt_forgery(change):
    request, metrics, journal, parts = case(complete=False)
    protocol = freeze(request, metrics, journal, parts)
    result = asyncio.run(execute(request, metrics, journal, protocol)).result
    event = result.journal.events[-1]
    replacement = ValidationArtifactReferenceV2(
        "SPOT_OOS_REQUEST", uuid4(), "1", "a" * 64
    )
    if change == "remove":
        evidence = ()
    elif change == "replace":
        evidence = (replacement,)
    elif change == "duplicate":
        evidence = (result.request_reference, result.request_reference)
    else:
        evidence = (ValidationArtifactReferenceV2("C-027", uuid4(), "3", "a" * 64),)
    altered_event = OOSJournalEvent.build(
        **dict(payload(event, {"content_sha256"}), evidence=evidence)
    )
    altered_journal = replace(
        result.journal,
        events=(*result.journal.events[:-1], altered_event),
    )
    with pytest.raises(LineageError):
        decode(_self_consistent_forged_wire(result, journal=altered_journal))


def _fill_journal_to(journal, size, protocol):
    duration = protocol.window.end - protocol.window.start
    outside = OOSWindow(
        protocol.window.venue,
        protocol.window.instrument_id,
        protocol.window.timeframe,
        protocol.window.start - duration - STEP,
        protocol.window.start - STEP,
    )
    while len(journal.snapshot.events) < size:
        journal.record_access(outside, purpose="UNRELATED_RESEARCH")


def test_holdout_capacity_rejects_before_access_or_replay_and_allows_receipt(
    monkeypatch,
):
    request, metrics, journal, parts = case()
    protocol = freeze(request, metrics, journal, parts)
    _fill_journal_to(journal, MAX_EVENTS - 1, protocol)
    before = journal.snapshot
    with pytest.raises(ValueError, match="SEQUENCE_CAPACITY"):
        asyncio.run(execute(request, metrics, journal, protocol))
    assert journal.snapshot == before

    request, metrics, journal, parts = case()
    protocol = freeze(request, metrics, journal, parts)
    _fill_journal_to(journal, MAX_EVENTS - 2, protocol)

    async def unavailable(**kwargs):
        with pytest.raises(ValueError, match="BUDGET"):
            journal.record_access(protocol.window, purpose="UNRELATED_RESEARCH")
        return SpotBacktestBundle(
            SpotBacktestOutcome.INCONCLUSIVE,
            ("ARCHIVE_UNAVAILABLE",),
            None,
            None,
            None,
            None,
            (),
        )

    monkeypatch.setattr(
        "trading_platform_api.validation.spot_oos.run_spot_backtest", unavailable
    )
    bundle = asyncio.run(execute(request, metrics, journal, protocol))
    assert bundle.outcome is OOSOutcome.INCONCLUSIVE
    assert len(journal.snapshot.events) == MAX_EVENTS
    assert [event.kind for event in journal.snapshot.events[-2:]] == [
        OOSEventKind.ACCESS,
        OOSEventKind.RESULT,
    ]


def test_development_exception_records_reserved_terminal_receipt(monkeypatch):
    request, metrics, journal, parts = case()
    now = [journal._clock()]
    journal._clock = lambda: now[0]
    protocol = freeze(
        request,
        metrics,
        journal,
        parts,
        selection_mode=OOSSelectionMode.VALIDATION_NET_PROFIT,
    )
    candidate = protocol.candidates[0]
    monkeypatch.setattr(
        "trading_platform_api.validation.spot_oos._validate_request",
        lambda *args, **kwargs: candidate,
    )

    async def raises_without_secret(**kwargs):
        now[0] += STEP
        journal.record_access(
            OOSWindow(
                protocol.window.venue,
                protocol.window.instrument_id,
                protocol.window.timeframe,
                T - 100 * STEP,
                T - 99 * STEP,
            ),
            purpose="UNRELATED_RESEARCH",
        )
        raise RuntimeError("sensitive provider detail")

    monkeypatch.setattr(
        "trading_platform_api.validation.spot_oos.run_spot_backtest",
        raises_without_secret,
    )
    with pytest.raises(RuntimeError, match="sensitive provider detail"):
        asyncio.run(
            run_spot_oos_partition(
                journal=journal,
                protocol=protocol,
                partition_id=parts[0].partition_id,
                request=request,
                metrics_policy=metrics,
                session=object(),
                strategy_registry=object(),
                lineage_store=object(),
            )
        )
    assert journal.snapshot.events[-3].kind is OOSEventKind.ACCESS
    assert journal.snapshot.events[-1].kind is OOSEventKind.TRIAL
    assert journal.snapshot.events[-1].purpose == "DEVELOPMENT_ABORTED:RuntimeError"
    assert "sensitive" not in journal.snapshot.events[-1].purpose


def test_holdout_exception_terminalizes_and_next_attempt_records_reuse(monkeypatch):
    request, metrics, journal, parts = case()
    now = [journal._clock()]
    journal._clock = lambda: now[0]
    protocol = freeze(request, metrics, journal, parts)

    async def raises_without_secret(**kwargs):
        now[0] += STEP
        journal.record_access(
            OOSWindow(
                protocol.window.venue,
                protocol.window.instrument_id,
                protocol.window.timeframe,
                T - 100 * STEP,
                T - 99 * STEP,
            ),
            purpose="UNRELATED_RESEARCH",
        )
        raise RuntimeError("sensitive provider detail")

    monkeypatch.setattr(
        "trading_platform_api.validation.spot_oos.run_spot_backtest",
        raises_without_secret,
    )
    with pytest.raises(RuntimeError, match="sensitive provider detail"):
        asyncio.run(execute(request, metrics, journal, protocol))
    assert journal.snapshot.events[-3].kind is OOSEventKind.ACCESS
    assert journal.snapshot.events[-1].kind is OOSEventKind.RESULT
    assert "sensitive" not in journal.snapshot.events[-1].purpose

    failed = asyncio.run(
        execute(
            request,
            metrics,
            journal,
            protocol,
            expires_at=request.expires_at - STEP,
        )
    )
    assert failed.outcome is OOSOutcome.FAILED
    assert failed.result.contamination is CheckOutcome.FAILED
    assert "HOLDOUT_PREVIOUSLY_ACCESSED_OR_REUSED" in failed.reason_codes
    assert journal.snapshot.events[-1].kind is OOSEventKind.RESULT


def test_concurrent_exact_repeat_waits_for_one_terminal_result(monkeypatch):
    request, metrics, journal, parts = case()
    protocol = freeze(request, metrics, journal, parts)

    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def unavailable(**kwargs):
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return SpotBacktestBundle(
                SpotBacktestOutcome.INCONCLUSIVE,
                ("ARCHIVE_UNAVAILABLE",),
                None,
                None,
                None,
                None,
                (),
            )

        monkeypatch.setattr(
            "trading_platform_api.validation.spot_oos.run_spot_backtest", unavailable
        )
        first = asyncio.create_task(execute(request, metrics, journal, protocol))
        await started.wait()
        second = asyncio.create_task(execute(request, metrics, journal, protocol))
        await asyncio.sleep(0)
        assert not second.done()
        release.set()
        results = await asyncio.gather(first, second)
        return results, calls

    results, calls = asyncio.run(scenario())
    assert results[0] == results[1]
    assert calls == 1
    assert [event.kind for event in journal.snapshot.events[-2:]] == [
        OOSEventKind.ACCESS,
        OOSEventKind.RESULT,
    ]


def test_concurrent_holdout_access_returns_resolvable_failed_result(monkeypatch):
    request, metrics, journal, parts = case()
    protocol = freeze(request, metrics, journal, parts)

    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()

        async def unavailable(**kwargs):
            started.set()
            await release.wait()
            return SpotBacktestBundle(
                SpotBacktestOutcome.INCONCLUSIVE,
                ("ARCHIVE_UNAVAILABLE",),
                None,
                None,
                None,
                None,
                (),
            )

        monkeypatch.setattr(
            "trading_platform_api.validation.spot_oos.run_spot_backtest", unavailable
        )
        task = asyncio.create_task(execute(request, metrics, journal, protocol))
        await started.wait()
        journal.record_access(protocol.window, purpose="FINAL_HOLDOUT_INSPECTION")
        release.set()
        return await task

    bundle = asyncio.run(scenario())
    assert bundle.outcome is OOSOutcome.FAILED
    assert bundle.result.contamination is CheckOutcome.FAILED
    assert "HOLDOUT_PREVIOUSLY_ACCESSED_OR_REUSED" in bundle.reason_codes
    assert resolve_spot_oos_result(bundle, journal=journal) == bundle.result


def test_inconclusive_replay_integrity_reason_produces_failed_result(monkeypatch):
    request, metrics, journal, parts = case()
    protocol = freeze(request, metrics, journal, parts)

    async def invalid(**kwargs):
        return SpotBacktestBundle(
            SpotBacktestOutcome.INCONCLUSIVE,
            ("OOS_SCOPE_OR_UNIT_MISMATCH",),
            None,
            None,
            None,
            None,
            (),
        )

    monkeypatch.setattr(
        "trading_platform_api.validation.spot_oos.run_spot_backtest", invalid
    )
    bundle = asyncio.run(execute(request, metrics, journal, protocol))
    assert bundle.outcome is OOSOutcome.FAILED
    assert bundle.result.integrity is CheckOutcome.FAILED
    assert resolve_spot_oos_result(bundle, journal=journal) == bundle.result


def test_development_exact_repeats_share_one_claim(monkeypatch):
    request, metrics, journal, parts = case()
    protocol = freeze(
        request,
        metrics,
        journal,
        parts,
        selection_mode=OOSSelectionMode.VALIDATION_NET_PROFIT,
    )

    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0
        expected = (object(), object())

        async def one_trial(**kwargs):
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return expected

        monkeypatch.setattr(
            "trading_platform_api.validation.spot_oos._run_spot_oos_partition_locked",
            one_trial,
        )
        values = dict(
            journal=journal,
            protocol=protocol,
            partition_id=parts[0].partition_id,
            request=request,
            metrics_policy=metrics,
            session=object(),
            strategy_registry=object(),
            lineage_store=object(),
        )
        first = asyncio.create_task(run_spot_oos_partition(**values))
        await started.wait()
        second = asyncio.create_task(run_spot_oos_partition(**values))
        await asyncio.sleep(0)
        assert not second.done()
        release.set()
        results = await asyncio.gather(first, second)
        return expected, results, calls

    expected, results, calls = asyncio.run(scenario())
    assert results == [expected, expected]
    assert calls == 1


def test_development_duplicate_request_conflict_rejects_before_access(monkeypatch):
    request, metrics, journal, parts = case()
    protocol = freeze(
        request,
        metrics,
        journal,
        parts,
        selection_mode=OOSSelectionMode.VALIDATION_NET_PROFIT,
    )
    journal._trial_claims[
        (
            protocol.content_sha256,
            parts[0].partition_id,
            protocol.candidates[0].candidate_id,
        )
    ] = "f" * 64
    before = journal.snapshot
    with pytest.raises(ValueError, match="OOS_DEVELOPMENT_DUPLICATE_CONFLICT"):
        asyncio.run(
            run_spot_oos_partition(
                journal=journal,
                protocol=protocol,
                partition_id=parts[0].partition_id,
                request=request,
                metrics_policy=metrics,
                session=object(),
                strategy_registry=object(),
                lineage_store=object(),
            )
        )
    assert journal.snapshot == before
