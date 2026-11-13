"""Focused C-029v2 fold, aggregation, and codec checks."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Context, Decimal, localcontext
from types import SimpleNamespace
from uuid import uuid4

import pytest
from trading_platform_api.config import DeploymentEnvironment
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.lineage.codec import LineageError, decode, encode, key_for
from trading_platform_api.lineage.store import references
from trading_platform_api.validation.contracts import (
    CheckOutcome,
    MetricValue,
    PartitionPurpose,
)
from trading_platform_api.validation.contracts_v2 import ValidationArtifactReferenceV2
from trading_platform_api.validation.oos_contracts_v2 import (
    OOSCandidateV2,
    OOSEventKind,
    OOSJournalEvent,
    OOSJournalSnapshot,
    OOSProtocolV2,
    OOSSelectionMode,
    OOSWindow,
)
from trading_platform_api.validation.spot_metrics import (
    METHOD as METRICS_METHOD,
)
from trading_platform_api.validation.spot_metrics import (
    MetricsPolicy,
    MetricState,
)
from trading_platform_api.validation.walk_forward_contracts_v2 import (
    FoldTerminalState,
    MetricDirection,
    WalkForwardConsistencyV2,
    WalkForwardFoldObservationV2,
    WalkForwardMetricV2,
    WalkForwardMode,
    WalkForwardOutcome,
    WalkForwardPlanSpecV2,
    WalkForwardProtocolV2,
    WalkForwardRequestPinV2,
    WalkForwardResultV2,
    build_consistency,
    build_metric_aggregates,
    generate_walk_forward_folds,
    unavailable_metric,
)

D = Decimal
STEP = timedelta(minutes=1)
UNITS = {
    "total_trades": "count",
    "win_rate": "ratio",
    "expectancy": "USDT",
    "profit_factor": "ratio",
    "maximum_fractional_drawdown": "ratio",
    "sharpe": "ratio",
    "sortino": "ratio",
    "cumulative_return": "ratio",
    "net_realized_profit": "USDT",
}


def _reference(kind: str, version: str = "1") -> ValidationArtifactReferenceV2:
    return ValidationArtifactReferenceV2(kind, uuid4(), version, "a" * 64)


def _plan(
    mode: WalkForwardMode = WalkForwardMode.ROLLING,
) -> WalkForwardPlanSpecV2:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    scope = OOSWindow("synthetic-venue", "BTC-USDT-SPOT", "1m", start, start + 5 * STEP)
    strategy = _reference("C-021", "2")
    oos_candidate = OOSCandidateV2(
        strategy,
        _reference("PARAMETER_SET"),
        _reference("C-027", "2"),
        _reference("SPOT_EXECUTION_COST_ADAPTER"),
        "b" * 64,
    )
    metrics = MetricsPolicy(
        METRICS_METHOD,
        "1",
        "USDT",
        "BAR_CLOSE",
        60,
        D(525600),
        D(0),
        D(0),
        1,
        1,
        scope.end + timedelta(days=1),
    )
    authority = _reference("SYNTHETIC_RESEARCH_RECORDER")
    journal_id = uuid4()
    frozen_at = scope.end + timedelta(days=1)
    base = WalkForwardPlanSpecV2(
        scope=scope,
        mode=mode,
        training_bars=2,
        validation_bars=1,
        heldout_bars=1,
        step_bars=1,
        embargo_bars=0,
        warmup_bars=0,
        minimum_folds=2,
        minimum_trades=1,
        minimum_returns=1,
        maximum_folds=4,
        maximum_candidates=1,
        maximum_events=16,
        candidates=(oos_candidate,),
        selection_mode=OOSSelectionMode.FIXED,
        metrics_policy=metrics,
        environment=DeploymentEnvironment.TEST,
        journal_id=journal_id,
        authority=authority,
        frozen_at=frozen_at,
    )
    folds = generate_walk_forward_folds(base)
    request_rows = tuple(
        (
            WalkForwardRequestPinV2(
                _reference("SPOT_OOS_REQUEST"),
                fold.fold_id,
                oos_candidate.candidate_id,
                fold.heldout.partition_id,
                PartitionPurpose.TEST,
                fold.heldout.end,
                frozen_at,
                frozen_at + timedelta(days=10),
                oos_candidate.strategy,
                oos_candidate.parameters,
                oos_candidate.costs,
                oos_candidate.cost_adapter,
                oos_candidate.execution_policy_sha256,
                "c" * 64,
                "d" * 64,
                "e" * 64,
            ),
        )
        for fold in folds
    )
    return replace(base, request_bindings_by_fold=request_rows)


def _cancelled_result(
    spec: WalkForwardPlanSpecV2,
) -> WalkForwardResultV2:
    protocol = WalkForwardProtocolV2.build(spec)
    oos_protocols = []
    events = []
    previous = "0" * 64
    frozen_at = spec.frozen_at
    for fold in protocol.folds:
        window = OOSWindow(
            spec.scope.venue,
            spec.scope.instrument_id,
            spec.scope.timeframe,
            fold.heldout.start,
            fold.heldout.end,
        )
        oos_protocol = OOSProtocolV2.build(
            journal_id=spec.journal_id,
            authority=spec.authority,
            window=window,
            partitions=(fold.training, fold.selection_validation, fold.heldout),
            candidates=spec.candidates,
            selection_mode=spec.selection_mode,
            metrics_policy_sha256=canonical_sha256(spec.metrics_policy),
            minimum_trades=spec.minimum_trades,
            warmup_bars=spec.warmup_bars,
            embargo_seconds=0,
            mark_equity=True,
            environment=spec.environment,
            frozen_at=frozen_at,
        )
        oos_protocols.append(oos_protocol)
        for kind, candidate_id, purpose in (
            (OOSEventKind.FREEZE, None, "PRECOMMITMENT"),
            (
                OOSEventKind.SELECT,
                spec.candidates[0].candidate_id,
                spec.selection_mode.value,
            ),
        ):
            event = OOSJournalEvent.build(
                sequence=len(events),
                recorded_at=frozen_at,
                kind=kind,
                window=window,
                protocol_sha256=oos_protocol.content_sha256,
                candidate_id=candidate_id,
                purpose=purpose,
                evidence=(),
                previous_sha256=previous,
            )
            events.append(event)
            previous = event.content_sha256
    journal = OOSJournalSnapshot(spec.journal_id, spec.authority, True, tuple(events))
    observations = tuple(
        WalkForwardFoldObservationV2(
            fold.fold_id,
            FoldTerminalState.CANCELLED,
            oos_protocol,
            None,
            tuple(pin.request for pin in pins),
            spec.journal_id,
            None,
            None,
            CheckOutcome.INCONCLUSIVE,
            CheckOutcome.INCONCLUSIVE,
            CheckOutcome.INCONCLUSIVE,
            spec.candidates[0].candidate_id,
            tuple(
                unavailable_metric(name, UNITS[name], "WALK_FORWARD_FOLD_CANCELLED")
                for name in UNITS
            ),
            (),
            ("WALK_FORWARD_FOLD_CANCELLED",),
        )
        for fold, pins, oos_protocol in zip(
            protocol.folds,
            spec.request_bindings_by_fold,
            oos_protocols,
            strict=True,
        )
    )
    as_of = max(fold.heldout.end for fold in protocol.folds)
    expires_at = min(
        pin.expires_at for row in spec.request_bindings_by_fold for pin in row
    )
    return WalkForwardResultV2.build(
        protocol=protocol,
        journal=journal,
        observations=observations,
        aggregates=build_metric_aggregates(observations),
        consistency=build_consistency(observations),
        outcome=WalkForwardOutcome.INCONCLUSIVE,
        reason_codes=(
            "WALK_FORWARD_COVERAGE_INCOMPLETE",
            "WALK_FORWARD_FOLD_CANCELLED",
        ),
        as_of=as_of,
        created_at=frozen_at + timedelta(days=1),
        expires_at=expires_at,
    )


def test_rolling_and_anchored_folds_are_deterministic_and_grid_aligned():
    rolling_spec = _plan()
    rolling = generate_walk_forward_folds(rolling_spec)
    anchored = generate_walk_forward_folds(_plan(WalkForwardMode.ANCHORED))

    assert len(rolling) == len(anchored) == 2
    assert rolling == generate_walk_forward_folds(rolling_spec)
    assert rolling[0].training.start == rolling[1].training.start - STEP
    assert rolling[0].training.end == rolling[1].training.end - STEP
    assert anchored[0].training.start == anchored[1].training.start
    assert anchored[0].training.end < anchored[1].training.end
    assert all(
        fold.training.end
        <= fold.selection_validation.start
        <= fold.selection_validation.end
        <= fold.heldout.start
        < fold.heldout.end
        for fold in (*rolling, *anchored)
    )


def test_walk_forward_fold_and_event_budgets_reject_before_execution():
    with pytest.raises(ValueError, match="HELDOUT_WINDOWS_OVERLAP"):
        replace(_plan(), heldout_bars=2, step_bars=1)
    with pytest.raises(ValueError, match="WALK_FORWARD_EVENT_BUDGET_EXCEEDED"):
        generate_walk_forward_folds(replace(_plan(), maximum_events=7))
    with pytest.raises(ValueError, match="INVALID_CANDIDATE_BUDGET"):
        replace(_plan(), maximum_candidates=0)


def test_decimal_aggregates_preserve_missing_coverage_and_consistency():
    ids = tuple(uuid4() for _ in range(4))
    values = (D("2"), D("-1"), D("5"), None)
    observations = []
    for fold_id, amount in zip(ids, values, strict=True):
        metrics = []
        for name, unit in UNITS.items():
            if name == "net_realized_profit" and amount is not None:
                metrics.append(
                    WalkForwardMetricV2(
                        name,
                        MetricState.AVAILABLE,
                        None,
                        MetricValue(name, amount, unit, METRICS_METHOD),
                        unit,
                        3,
                        (),
                    )
                )
            else:
                metrics.append(unavailable_metric(name, unit, "NO_OBSERVATION"))
        observations.append(
            SimpleNamespace(
                fold_id=fold_id,
                state=(
                    FoldTerminalState.OBSERVED
                    if amount is not None
                    else FoldTerminalState.INCONCLUSIVE
                ),
                metrics=tuple(metrics),
            )
        )

    aggregates = build_metric_aggregates(tuple(observations))
    net = next(item for item in aggregates if item.name == "net_realized_profit")
    trades = next(item for item in aggregates if item.name == "total_trades")
    consistency = build_consistency(tuple(observations))

    assert (net.planned_count, net.completed_count, net.available_count) == (4, 3, 3)
    assert (net.unavailable_count, net.inconclusive_count) == (1, 1)
    assert (net.mean, net.median, net.minimum, net.maximum) == (
        D(2),
        D(2),
        D(-1),
        D(5),
    )
    with localcontext(Context(prec=50)):
        assert net.population_standard_deviation == D(6).sqrt()
    assert net.minimum_fold_id == ids[1]
    assert net.maximum_fold_id == ids[2]
    assert net.best_fold_id == ids[2]
    assert net.worst_fold_id == ids[1]
    assert trades.direction is MetricDirection.DESCRIPTIVE
    assert trades.best_fold_id is trades.worst_fold_id is None
    assert isinstance(consistency, WalkForwardConsistencyV2)
    with localcontext(Context(prec=50)):
        expected_ratio = D(2) / D(3)
    assert (
        consistency.positive_folds,
        consistency.available_return_folds,
        consistency.planned_folds,
        consistency.missing_return_folds,
        consistency.ratio,
    ) == (2, 3, 4, 1, expected_ratio)


def test_c029_v2_round_trips_with_closed_version_and_denies_retention():
    result = _cancelled_result(_plan())
    encoded = encode(result)

    assert decode(encoded) == result
    assert key_for(result).contract_id == "C-029"
    assert key_for(result).version == "2"
    with pytest.raises(LineageError):
        references(result)

    unknown = json.loads(encoded)
    unknown["schema_version"] = "1"
    with pytest.raises(LineageError):
        decode(json.dumps(unknown, separators=(",", ":"), sort_keys=True))


def test_cancelled_contract_keeps_every_planned_fold_and_no_fake_metrics():
    result = _cancelled_result(_plan())

    assert len(result.observations) == result.protocol.spec.minimum_folds
    assert all(
        item.state is FoldTerminalState.CANCELLED for item in result.observations
    )
    assert all(
        metric.state is not MetricState.AVAILABLE
        for item in result.observations
        for metric in item.metrics
    )


def test_contract_rejects_forged_aggregate_and_selection_bindings():
    result = _cancelled_result(_plan())
    altered_observation = replace(
        result.observations[0],
        selected_candidate_id=None,
    )

    with pytest.raises(ValueError, match="WALK_FORWARD_SELECTION_BINDING_MISMATCH"):
        replace(
            result,
            observations=(altered_observation, *result.observations[1:]),
        )
    with pytest.raises(ValueError, match="WALK_FORWARD_AGGREGATE_MISMATCH"):
        replace(result, aggregates=())
