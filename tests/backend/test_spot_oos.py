"""Synthetic recorded-research protocol checks; no profitability claims."""

import asyncio
import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from test_spot_execution import fixture, production_cost_case
from test_spot_replay_inputs import T, _case
from test_validation_contracts import oos as legacy_oos
from trading_platform_api.config import DeploymentEnvironment
from trading_platform_api.contracts.serialization import (
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
    OOSEventKind,
    OOSJournalSnapshot,
    OOSOutcome,
    OOSProtocolV2,
    OOSResultV2,
    OOSSelectionMode,
    OOSWindow,
    payload,
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
    _preflight,
    candidate_from_request,
    freeze_spot_oos_protocol,
    resolve_spot_oos_result,
    run_spot_oos,
    select_spot_oos_candidate,
)

D = Decimal
STEP = timedelta(minutes=1)


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
        T + 9 * STEP,
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
    operational_time = T + timedelta(days=2)
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
            uuid4(), PartitionPurpose.TRAIN, T - 20 * STEP, T - 10 * STEP, T, True
        ),
        DataPartition(uuid4(), PartitionPurpose.VALIDATION, T - 10 * STEP, T, T, False),
        DataPartition(
            uuid4(), PartitionPurpose.TEST, T, policy.period_end, T + 9 * STEP, False
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


async def execute(request, metrics, journal, protocol):
    return await run_spot_oos(
        journal=journal,
        protocol=protocol,
        request=request,
        metrics_policy=metrics,
        session=object(),
        strategy_registry=object(),
        lineage_store=object(),
        as_of=request.result_as_of,
        expires_at=T + timedelta(days=3),
    )


def test_freeze_records_real_order_separate_from_historical_candle_time():
    request, metrics, journal, partitions = case()
    protocol = freeze(request, metrics, journal, partitions)
    assert protocol.frozen_at > protocol.window.end
    assert [e.kind for e in journal.snapshot.events] == [
        OOSEventKind.FREEZE,
        OOSEventKind.SELECT,
    ]
    assert _preflight(journal, protocol) == ([], [])
    assert journal.snapshot.events[0].protocol_sha256 == protocol.content_sha256
    assert (
        OOSProtocolV2.build(
            **payload(protocol, {"protocol_id", "content_sha256", "method"})
        )
        == protocol
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


@pytest.mark.parametrize("use", ["INSPECTION", "OPTIMIZATION", "REVISED_DATA_ACCESS"])
def test_previously_inspected_or_tuned_holdout_fails_before_replay(monkeypatch, use):
    request, metrics, journal, parts = case()
    p = request.execution_policy
    journal.record_access(
        OOSWindow("another-venue", p.instrument_id, "5m", p.period_start, p.period_end),
        purpose=use,
    )
    protocol = freeze(request, metrics, journal, parts)

    async def forbidden(**kwargs):
        pytest.fail("contaminated holdout reached the replay engine")

    monkeypatch.setattr(
        "trading_platform_api.validation.spot_oos.run_spot_backtest", forbidden
    )
    result = asyncio.run(execute(request, metrics, journal, protocol))
    assert result.outcome is OOSOutcome.FAILED
    assert "HOLDOUT_PREVIOUSLY_ACCESSED_OR_REUSED" in result.reason_codes
    assert result.result.contamination is CheckOutcome.FAILED
    assert not result.replays
    assert resolve_spot_oos_result(result, journal=journal) == result.result


def test_incomplete_history_is_inconclusive_and_not_a_clean_holdout(monkeypatch):
    request, metrics, journal, parts = case(complete=False)
    protocol = freeze(request, metrics, journal, parts)

    async def forbidden(**kwargs):
        pytest.fail("incomplete journal reached replay")

    monkeypatch.setattr(
        "trading_platform_api.validation.spot_oos.run_spot_backtest", forbidden
    )
    bundle = asyncio.run(execute(request, metrics, journal, protocol))
    assert bundle.outcome is OOSOutcome.INCONCLUSIVE
    assert bundle.result.contamination is CheckOutcome.INCONCLUSIVE
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

    async def forbidden(**kwargs):
        pytest.fail("unselected strategy reached final holdout replay")

    monkeypatch.setattr(
        "trading_platform_api.validation.spot_oos.run_spot_backtest", forbidden
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


def test_selection_change_and_new_protocol_id_do_not_reset_exposure(monkeypatch):
    request, metrics, journal, parts = case()
    first = freeze(request, metrics, journal, parts)
    journal.record_access(first.window, purpose="FINAL_HOLDOUT_INSPECTION")
    select_spot_oos_candidate(
        journal=journal, protocol=first, candidate_id=first.candidates[0].candidate_id
    )
    failed, _ = _preflight(journal, first)
    assert "SELECTION_CHANGED_AFTER_FREEZE" in failed
    parts = tuple(replace(p, partition_id=uuid4()) for p in parts)
    second = freeze(request, metrics, journal, parts)
    assert second.protocol_id != first.protocol_id
    bundle = asyncio.run(execute(request, metrics, journal, second))
    assert bundle.outcome is OOSOutcome.FAILED
    assert "HOLDOUT_PREVIOUSLY_ACCESSED_OR_REUSED" in bundle.reason_codes


def test_recorded_clock_cannot_move_backwards():
    request, metrics, journal, parts = case()
    protocol = freeze(request, metrics, journal, parts)
    journal._clock = lambda: protocol.frozen_at - timedelta(seconds=1)
    with pytest.raises(ValueError, match="CLOCK"):
        journal.record_access(protocol.window)


def test_hashes_and_timestamps_cannot_replace_live_recorder_receipts():
    request, metrics, journal, parts = case(complete=False)
    protocol = freeze(request, metrics, journal, parts)
    bundle = asyncio.run(execute(request, metrics, journal, protocol))
    clone = OOSResearchJournal(
        journal_id=journal.snapshot.journal_id,
        authority=journal.snapshot.authority,
        clock=lambda: protocol.frozen_at,
        declared_complete=True,
        prior_history=journal.snapshot.events,
    )
    with pytest.raises(ValueError, match="FREEZE_RECEIPT|UNAUTHENTICATED_OOS_RESULT"):
        resolve_spot_oos_result(bundle, journal=clone)
    event = journal.snapshot.events[0]
    with pytest.raises(ValueError, match="DIGEST"):
        replace(event, purpose="RETROACTIVE_FREEZE")
    with pytest.raises(ValueError, match="CHAIN"):
        OOSJournalSnapshot(
            journal.snapshot.journal_id,
            journal.snapshot.authority,
            True,
            journal.snapshot.events[1:],
        )


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


def test_missing_archive_remains_inconclusive_and_repeat_is_idempotent(monkeypatch):
    request, metrics, journal, parts = case()
    protocol = freeze(request, metrics, journal, parts)
    calls = []

    async def unavailable(**kwargs):
        calls.append(kwargs)
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
    assert "ARCHIVE_UNAVAILABLE" in bundle.reason_codes
    assert asyncio.run(execute(request, metrics, journal, protocol)) == bundle
    assert len(calls) == 1
    assert resolve_spot_oos_result(bundle, journal=journal) == bundle.result


@pytest.mark.parametrize("change", ["strategy", "policy", "scope", "warmup"])
def test_changed_request_pins_are_rejected_before_replay(change, monkeypatch):
    request, metrics, journal, parts = case()
    protocol = freeze(
        request, metrics, journal, parts, warmup_bars=0 if change == "warmup" else 32
    )
    if change == "policy":
        metrics = replace(metrics, min_trade_sample=2)
    elif change == "scope":
        request = replace(
            request,
            execution_policy=replace(request.execution_policy, period_start=T - STEP),
        )
    elif change == "warmup":
        decisions = request.replay_inputs.decisions
        request = replace(
            request,
            replay_inputs=replace(
                request.replay_inputs,
                decisions=(
                    replace(decisions[0], lookback_start=T - STEP),
                    *decisions[1:],
                ),
            ),
        )
    elif change == "strategy":
        request = replace(
            request, parameters=replace(request.parameters, quantity=D("0.5"))
        )

    async def forbidden(**kwargs):
        pytest.fail("mismatched request reached replay")

    monkeypatch.setattr(
        "trading_platform_api.validation.spot_oos.run_spot_backtest", forbidden
    )
    result = asyncio.run(execute(request, metrics, journal, protocol))
    assert result.outcome is OOSOutcome.FAILED
    assert not result.replays


def test_development_cutoff_cannot_reveal_the_final_holdout():
    request, metrics, journal, parts = case()
    parts = (replace(parts[0], point_in_time_cutoff=parts[-1].start + STEP), *parts[1:])
    with pytest.raises(ValueError, match="DEVELOPMENT_CUTOFF"):
        freeze(request, metrics, journal, parts)


def test_logged_selection_uses_only_complete_declared_development_trials():
    from decimal import localcontext
    from types import SimpleNamespace

    from trading_platform_api.validation.contracts import MetricValue

    request, metrics, journal, parts = case()
    first = candidate_from_request(request)
    second = replace(
        first,
        parameters=ValidationArtifactReferenceV2(
            "PARAMETER_SET", uuid4(), first.parameters.version, "e" * 64
        ),
    )
    protocol = freeze(
        request,
        metrics,
        journal,
        parts,
        candidates=(first, second),
        selection_mode=OOSSelectionMode.VALIDATION_NET_PROFIT,
    )
    with pytest.raises(ValueError, match="INCOMPLETE_SELECTION_HISTORY"):
        select_spot_oos_candidate(
            journal=journal, protocol=protocol, candidate_id=first.candidate_id
        )
    scores = (
        D("0.1000000000000000000000000000000001"),
        D("0.1000000000000000000000000000000002"),
    )
    # Test-owned stand-ins for reports already validated by run_spot_oos_partition.
    # This isolates selection policy and does not publish synthetic performance.
    for partition in parts[:2]:
        window = OOSWindow(
            protocol.window.venue,
            protocol.window.instrument_id,
            protocol.window.timeframe,
            partition.start,
            partition.end,
        )
        for candidate, score in zip((first, second), scores, strict=True):
            event = journal._append(
                OOSEventKind.TRIAL,
                window,
                protocol=protocol,
                candidate=candidate,
                purpose=partition.purpose.value,
            )
            report = SimpleNamespace(
                get=lambda name, value=score: SimpleNamespace(
                    metric=MetricValue(
                        name, value, "USDT", "synthetic-selection-unit-v1"
                    )
                )
            )
            journal._trials[event.content_sha256] = (None, report)
    with localcontext() as context:
        context.prec = 6
        with pytest.raises(ValueError, match="SELECTION_CRITERION_MISMATCH"):
            select_spot_oos_candidate(
                journal=journal, protocol=protocol, candidate_id=first.candidate_id
            )
        select_spot_oos_candidate(
            journal=journal, protocol=protocol, candidate_id=second.candidate_id
        )
    assert journal.snapshot.events[-1].candidate_id == second.candidate_id
    assert _preflight(journal, protocol) == ([], [])


def test_self_consistent_forged_result_is_not_a_recorder_issued_result():
    request, metrics, journal, parts = case(complete=False)
    protocol = freeze(request, metrics, journal, parts)
    bundle = asyncio.run(execute(request, metrics, journal, protocol))
    values = payload(
        bundle.result,
        {
            "result_id",
            "content_sha256",
            "method",
            "contract_id",
            "schema_version",
            "operating_mode",
        },
    )
    forged = OOSResultV2.build(**dict(values, warnings=("FORGED_DECLARATION",)))
    with pytest.raises(ValueError, match="UNAUTHENTICATED_OOS_RESULT"):
        resolve_spot_oos_result(replace(bundle, result=forged), journal=journal)


@pytest.mark.parametrize("complete", [True, False])
def test_as_of_mismatch_is_rejected_before_any_holdout_access(monkeypatch, complete):
    request, metrics, journal, parts = case(complete=complete)
    protocol = freeze(request, metrics, journal, parts)
    before = journal.snapshot

    async def forbidden(**kwargs):
        pytest.fail("mismatched as-of reached replay")

    monkeypatch.setattr(
        "trading_platform_api.validation.spot_oos.run_spot_backtest", forbidden
    )
    with pytest.raises(ValueError, match="OOS_AS_OF_REQUEST_MISMATCH"):
        asyncio.run(
            run_spot_oos(
                journal=journal,
                protocol=protocol,
                request=request,
                metrics_policy=metrics,
                session=object(),
                strategy_registry=object(),
                lineage_store=object(),
                as_of=request.result_as_of - STEP,
                expires_at=T + timedelta(days=3),
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
