"""Offline rolling and anchored Spot walk-forward observations."""

from __future__ import annotations

import asyncio
import weakref
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from trading_platform_api.config import DeploymentEnvironment
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.lineage.codec import decode, encode
from trading_platform_api.lineage.store import SqlAlchemyLineageStore
from trading_platform_api.strategy.registry import StrategyRegistry
from trading_platform_api.validation.contracts import CheckOutcome, DataPartition
from trading_platform_api.validation.contracts_v2 import ValidationArtifactReferenceV2
from trading_platform_api.validation.oos_contracts_v2 import (
    MAX_EVENTS,
    OOSCandidateV2,
    OOSEventKind,
    OOSOutcome,
    OOSProtocolV2,
    OOSSelectionMode,
    OOSWindow,
    utc,
)
from trading_platform_api.validation.spot_backtest import (
    SpotBacktestRunRequest,
)
from trading_platform_api.validation.spot_metrics import (
    MetricState,
    SpotPerformanceReport,
)
from trading_platform_api.validation.spot_oos import (
    OOSResearchJournal,
    _request_digest,
    _request_ref,
    candidate_from_request,
    freeze_spot_oos_protocol,
    resolve_spot_oos_result,
    run_spot_oos,
    run_spot_oos_partition,
    select_spot_oos_candidate,
)
from trading_platform_api.validation.walk_forward_contracts_v2 import (
    NAMESPACE,
    FoldTerminalState,
    WalkForwardFoldObservationV2,
    WalkForwardFoldPlanV2,
    WalkForwardMetricV2,
    WalkForwardOutcome,
    WalkForwardPlanSpecV2,
    WalkForwardProtocolV2,
    WalkForwardRequestPinV2,
    WalkForwardResultV2,
    build_consistency,
    build_metric_aggregates,
    derive_walk_forward_outcome,
    generate_walk_forward_folds,
    metric_from_report,
    unavailable_metric,
)

_METRIC_UNITS = {
    "total_trades": "count",
    "win_rate": "ratio",
    "expectancy": None,
    "profit_factor": "ratio",
    "maximum_fractional_drawdown": "ratio",
    "sharpe": "ratio",
    "sortino": "ratio",
    "cumulative_return": "ratio",
    "net_realized_profit": None,
}
_LOCKS: weakref.WeakKeyDictionary[OOSResearchJournal, asyncio.Lock] = (
    weakref.WeakKeyDictionary()
)


@dataclass(frozen=True, slots=True)
class SpotWalkForwardCandidateRequests:
    training: SpotBacktestRunRequest | None
    selection_validation: SpotBacktestRunRequest | None
    heldout: SpotBacktestRunRequest


@dataclass(frozen=True, slots=True)
class SpotWalkForwardFoldRequests:
    candidates: tuple[SpotWalkForwardCandidateRequests, ...]


@dataclass(frozen=True, slots=True)
class SpotWalkForwardBundle:
    result: WalkForwardResultV2
    journal: OOSResearchJournal


class SpotWalkForwardCancelled(asyncio.CancelledError):
    """Cancellation carrying the closed partial walk-forward observation."""

    def __init__(self, result: WalkForwardResultV2) -> None:
        super().__init__("Spot walk-forward run cancelled.")
        self.result = result


def _lock_for(journal: OOSResearchJournal) -> asyncio.Lock:
    lock = _LOCKS.get(journal)
    if lock is None:
        lock = asyncio.Lock()
        _LOCKS[journal] = lock
    return lock


def _request_pin(
    *,
    request: SpotBacktestRunRequest,
    fold_id: UUID,
    candidate: OOSCandidateV2,
    partition: DataPartition,
) -> WalkForwardRequestPinV2:
    return WalkForwardRequestPinV2(
        _request_ref(_request_digest(request)),
        fold_id,
        candidate.candidate_id,
        partition.partition_id,
        partition.purpose,
        request.result_as_of,
        request.created_at,
        request.expires_at,
        candidate.strategy,
        candidate.parameters,
        candidate.costs,
        candidate.cost_adapter,
        candidate.execution_policy_sha256,
        request.execution_dataset_sha256,
        request.execution_manifest_sha256,
        canonical_sha256(request.archive_pins),
    )


def _check_request(
    request: SpotBacktestRunRequest,
    candidate: OOSCandidateV2,
    partition: DataPartition,
    spec: WalkForwardPlanSpecV2,
    *,
    now: datetime,
) -> None:
    if type(request) is not SpotBacktestRunRequest:
        raise ValueError("INVALID_WALK_FORWARD_REQUEST")
    policy = request.execution_policy
    scope = request.replay_inputs.scope
    expected_scope = (
        spec.scope.venue,
        spec.scope.instrument_id,
        spec.scope.timeframe,
        spec.environment,
    )
    request_scope = (
        policy.venue,
        policy.instrument_id,
        policy.timeframe,
        policy.environment,
    )
    input_scope = (
        scope.venue_id,
        scope.instrument_id,
        scope.timeframe,
        scope.environment,
    )
    if (
        candidate_from_request(request) != candidate
        or request_scope != expected_scope
        or input_scope != expected_scope
        or policy.quote_unit != spec.metrics_policy.quote_unit
        or policy.period_start != partition.start
        or policy.period_end != partition.end
        or scope.decision_period_start != partition.start
        or scope.decision_period_end != partition.end
        or request.result_as_of != partition.end
        or request.created_at < request.result_as_of
        or request.created_at > now
        or request.expires_at <= now
        or scope.environment
        not in (DeploymentEnvironment.DEV, DeploymentEnvironment.TEST)
        or not request.replay_inputs.decisions
        or len(request.replay_inputs.decisions)
        > request.replay_inputs.limits.maximum_decisions
        or any(
            not partition.start <= decision.decision_time < partition.end
            or decision.lookback_start
            < partition.start
            - spec.warmup_bars * timedelta(seconds=spec.metrics_policy.interval_seconds)
            for decision in request.replay_inputs.decisions
        )
    ):
        raise ValueError("WALK_FORWARD_REQUEST_PARTITION_MISMATCH")


def _fold_request_pins(
    *,
    spec: WalkForwardPlanSpecV2,
    folds: tuple[WalkForwardFoldPlanV2, ...],
    requests: tuple[SpotWalkForwardFoldRequests, ...],
    now: datetime,
) -> tuple[tuple[WalkForwardRequestPinV2, ...], ...]:
    if len(requests) != len(folds):
        raise ValueError("WALK_FORWARD_REQUEST_FOLD_COUNT_MISMATCH")
    output = []
    for fold, row in zip(folds, requests, strict=True):
        if (
            type(row) is not SpotWalkForwardFoldRequests
            or type(row.candidates) is not tuple
            or len(row.candidates) != len(spec.candidates)
        ):
            raise ValueError("WALK_FORWARD_REQUEST_CANDIDATE_COUNT_MISMATCH")
        pins: list[WalkForwardRequestPinV2] = []
        for candidate, item in zip(spec.candidates, row.candidates, strict=True):
            if type(item) is not SpotWalkForwardCandidateRequests:
                raise ValueError("INVALID_WALK_FORWARD_REQUEST_ROW")
            if spec.selection_mode is OOSSelectionMode.FIXED:
                if item.training is not None or item.selection_validation is not None:
                    raise ValueError("FIXED_SELECTION_HAS_UNUSED_DEVELOPMENT_REQUESTS")
            else:
                if item.training is None or item.selection_validation is None:
                    raise ValueError("WALK_FORWARD_DEVELOPMENT_REQUEST_REQUIRED")
                _check_request(item.training, candidate, fold.training, spec, now=now)
                _check_request(
                    item.selection_validation,
                    candidate,
                    fold.selection_validation,
                    spec,
                    now=now,
                )
                pins.extend(
                    (
                        _request_pin(
                            request=item.training,
                            fold_id=fold.fold_id,
                            candidate=candidate,
                            partition=fold.training,
                        ),
                        _request_pin(
                            request=item.selection_validation,
                            fold_id=fold.fold_id,
                            candidate=candidate,
                            partition=fold.selection_validation,
                        ),
                    )
                )
            _check_request(item.heldout, candidate, fold.heldout, spec, now=now)
            if spec.selection_mode is OOSSelectionMode.FIXED or (
                spec.selection_mode is OOSSelectionMode.VALIDATION_NET_PROFIT
            ):
                pins.append(
                    _request_pin(
                        request=item.heldout,
                        fold_id=fold.fold_id,
                        candidate=candidate,
                        partition=fold.heldout,
                    )
                )
        output.append(tuple(pins))
    return tuple(output)


def _oos_protocol(
    *,
    journal: OOSResearchJournal,
    spec: WalkForwardPlanSpecV2,
    fold: WalkForwardFoldPlanV2,
) -> OOSProtocolV2:
    return freeze_spot_oos_protocol(
        journal=journal,
        window=OOSWindow(
            spec.scope.venue,
            spec.scope.instrument_id,
            spec.scope.timeframe,
            fold.heldout.start,
            fold.heldout.end,
        ),
        partitions=(fold.training, fold.selection_validation, fold.heldout),
        candidates=spec.candidates,
        selection_mode=spec.selection_mode,
        metrics_policy=spec.metrics_policy,
        warmup_bars=spec.warmup_bars,
        embargo_seconds=spec.embargo_bars * spec.metrics_policy.interval_seconds,
        mark_equity=True,
        environment=spec.environment,
    )


def _select_candidate(
    journal: OOSResearchJournal,
    protocol: OOSProtocolV2,
    validation_reports: dict[UUID, SpotPerformanceReport],
) -> UUID:
    scores = []
    for candidate in protocol.candidates:
        report = validation_reports.get(candidate.candidate_id)
        if report is None:
            raise ValueError("INCOMPLETE_SELECTION_HISTORY")
        metric = report.get("net_realized_profit")
        if metric.state is not MetricState.AVAILABLE or metric.metric is None:
            raise ValueError("VALIDATION_SELECTION_METRIC_UNAVAILABLE")
        scores.append((metric.metric.value, str(candidate.candidate_id), candidate))
    winner = sorted(
        scores,
        key=lambda item: (item[0].copy_negate(), item[1]),
    )[0][2]
    select_spot_oos_candidate(
        journal=journal,
        protocol=protocol,
        candidate_id=winner.candidate_id,
    )
    return winner.candidate_id


def _unit(name: str, spec: WalkForwardPlanSpecV2) -> str:
    return _METRIC_UNITS[name] or spec.metrics_policy.quote_unit


def _metrics_from_bundle(
    result,
    spec: WalkForwardPlanSpecV2,
) -> tuple[tuple[WalkForwardMetricV2, ...], tuple, tuple[str, ...]]:
    heldout = tuple(
        run
        for run in result.runs
        if run.partition_id == result.protocol.partitions[-1].partition_id
    )
    if heldout:
        if len(heldout) != 1:
            raise ValueError("DUPLICATE_WALK_FORWARD_HELDOUT_RUN")
        report = heldout[0].resolve_report()
        metrics = tuple(
            metric_from_report(report, name, _unit(name, spec))
            for name in (
                "total_trades",
                "win_rate",
                "expectancy",
                "profit_factor",
                "maximum_fractional_drawdown",
                "sharpe",
                "sortino",
                "cumulative_return",
                "net_realized_profit",
            )
        )
        return metrics, report.trades, result.reason_codes
    reason = (
        result.reason_codes[0] if result.reason_codes else "OOS_METRICS_UNAVAILABLE"
    )
    return (
        tuple(
            unavailable_metric(name, _unit(name, spec), reason)
            for name in (
                "total_trades",
                "win_rate",
                "expectancy",
                "profit_factor",
                "maximum_fractional_drawdown",
                "sharpe",
                "sortino",
                "cumulative_return",
                "net_realized_profit",
            )
        ),
        (),
        result.reason_codes,
    )


def _receipt_event(
    journal: OOSResearchJournal,
    protocol: OOSProtocolV2,
):
    events = tuple(
        event
        for event in journal.snapshot.events
        if event.protocol_sha256 == protocol.content_sha256
        and event.kind is OOSEventKind.RESULT
    )
    return events[-1] if events else None


def _check_outcomes(event) -> tuple[CheckOutcome, CheckOutcome, CheckOutcome]:
    if event is None or event.kind is not OOSEventKind.RESULT:
        return (
            CheckOutcome.INCONCLUSIVE,
            CheckOutcome.INCONCLUSIVE,
            CheckOutcome.INCONCLUSIVE,
        )
    fields = event.purpose.split(":", 5)
    if len(fields) != 6 or fields[0] != "RECORDED_OUTCOME":
        return (
            CheckOutcome.INCONCLUSIVE,
            CheckOutcome.INCONCLUSIVE,
            CheckOutcome.INCONCLUSIVE,
        )
    try:
        return (
            CheckOutcome(fields[3]),
            CheckOutcome(fields[2]),
            CheckOutcome(fields[4]),
        )
    except ValueError:
        return (
            CheckOutcome.INCONCLUSIVE,
            CheckOutcome.INCONCLUSIVE,
            CheckOutcome.INCONCLUSIVE,
        )


def _fold_observation(
    *,
    fold: WalkForwardFoldPlanV2,
    protocol: OOSProtocolV2,
    request_bindings: tuple[ValidationArtifactReferenceV2, ...],
    journal: OOSResearchJournal,
    spec: WalkForwardPlanSpecV2,
    oos_result=None,
    cancelled: bool = False,
    failure_reason: str | None = None,
) -> WalkForwardFoldObservationV2:
    receipt = _receipt_event(journal, protocol)
    if oos_result is not None:
        state = {
            OOSOutcome.OBSERVED: FoldTerminalState.OBSERVED,
            OOSOutcome.INCONCLUSIVE: (
                FoldTerminalState.CANCELLED
                if cancelled
                else FoldTerminalState.INCONCLUSIVE
            ),
            OOSOutcome.FAILED: FoldTerminalState.FAILED,
        }[oos_result.outcome]
        metrics, trades, reasons = _metrics_from_bundle(oos_result, spec)
        receipt = oos_result.journal.events[-1]
        return WalkForwardFoldObservationV2(
            fold.fold_id,
            state,
            protocol,
            oos_result,
            request_bindings,
            journal.snapshot.journal_id,
            uuid5(NAMESPACE, "journal-receipt:" + receipt.content_sha256),
            receipt.content_sha256,
            oos_result.integrity,
            oos_result.contamination,
            oos_result.sample_sufficiency,
            (
                oos_result.selected_candidate.candidate_id
                if oos_result.selected_candidate
                else None
            ),
            metrics,
            trades,
            reasons,
        )
    integrity, contamination, sample = _check_outcomes(receipt)
    state = (
        FoldTerminalState.CANCELLED
        if cancelled
        else FoldTerminalState.FAILED
        if failure_reason
        or integrity is CheckOutcome.FAILED
        or contamination is CheckOutcome.FAILED
        else FoldTerminalState.INCONCLUSIVE
    )
    reason = failure_reason or (
        "WALK_FORWARD_FOLD_CANCELLED"
        if cancelled
        else "WALK_FORWARD_FOLD_RESULT_UNAVAILABLE"
    )
    selections = tuple(
        event
        for event in journal.snapshot.events
        if event.kind is OOSEventKind.SELECT
        and event.protocol_sha256 == protocol.content_sha256
    )
    selected_candidate_id = selections[0].candidate_id if len(selections) == 1 else None
    metrics = tuple(
        unavailable_metric(name, _unit(name, spec), reason)
        for name in (
            "total_trades",
            "win_rate",
            "expectancy",
            "profit_factor",
            "maximum_fractional_drawdown",
            "sharpe",
            "sortino",
            "cumulative_return",
            "net_realized_profit",
        )
    )
    return WalkForwardFoldObservationV2(
        fold.fold_id,
        state,
        protocol,
        None,
        request_bindings,
        journal.snapshot.journal_id,
        uuid5(NAMESPACE, "journal-receipt:" + receipt.content_sha256)
        if receipt is not None
        else None,
        receipt.content_sha256 if receipt is not None else None,
        integrity,
        contamination,
        sample,
        selected_candidate_id,
        metrics,
        (),
        (reason,),
    )


def _build_result(
    *,
    protocol: WalkForwardProtocolV2,
    journal: OOSResearchJournal,
    observations: tuple[WalkForwardFoldObservationV2, ...],
) -> WalkForwardResultV2:
    outcome = derive_walk_forward_outcome(
        observations,
        protocol.spec.minimum_folds,
        protocol.spec.minimum_returns,
    )
    reasons = tuple(
        sorted(
            {
                reason
                for observation in observations
                for reason in observation.reason_codes
            }
        )
    )
    if outcome is WalkForwardOutcome.INCONCLUSIVE:
        reasons = tuple(sorted(set(reasons) | {"WALK_FORWARD_COVERAGE_INCOMPLETE"}))
    if outcome is WalkForwardOutcome.FAILED:
        reasons = tuple(
            sorted(set(reasons) | {"WALK_FORWARD_INTEGRITY_OR_CONTAMINATION_FAILURE"})
        )
    request_rows = protocol.spec.request_bindings_by_fold
    test_as_of = max(
        pin.result_as_of
        for row in request_rows
        for pin in row
        if pin.partition_role.name == "TEST"
    )
    expires_at = min(pin.expires_at for row in request_rows for pin in row)
    created_at = utc(journal._clock())
    return WalkForwardResultV2.build(
        protocol=protocol,
        journal=journal.snapshot,
        observations=observations,
        aggregates=build_metric_aggregates(observations),
        consistency=build_consistency(observations),
        outcome=outcome,
        reason_codes=reasons,
        as_of=test_as_of,
        created_at=created_at,
        expires_at=expires_at,
    )


async def run_spot_walk_forward(
    *,
    journal: OOSResearchJournal,
    spec: WalkForwardPlanSpecV2,
    requests: tuple[SpotWalkForwardFoldRequests, ...],
    session: AsyncSession,
    strategy_registry: StrategyRegistry,
    lineage_store: SqlAlchemyLineageStore,
) -> SpotWalkForwardBundle:
    """Freeze and execute archive-bound folds using the established Spot OOS path."""
    if (
        type(journal) is not OOSResearchJournal
        or type(spec) is not WalkForwardPlanSpecV2
        or type(requests) is not tuple
    ):
        raise ValueError("INVALID_WALK_FORWARD_INPUT")
    async with _lock_for(journal):
        return await _run_spot_walk_forward_locked(
            journal=journal,
            spec=spec,
            requests=requests,
            session=session,
            strategy_registry=strategy_registry,
            lineage_store=lineage_store,
        )


async def _run_spot_walk_forward_locked(
    *,
    journal: OOSResearchJournal,
    spec: WalkForwardPlanSpecV2,
    requests: tuple[SpotWalkForwardFoldRequests, ...],
    session: AsyncSession,
    strategy_registry: StrategyRegistry,
    lineage_store: SqlAlchemyLineageStore,
) -> SpotWalkForwardBundle:
    if (journal.snapshot.journal_id, journal.snapshot.authority) != (
        spec.journal_id,
        spec.authority,
    ):
        raise ValueError("WALK_FORWARD_JOURNAL_AUTHORITY_MISMATCH")
    folds = generate_walk_forward_folds(spec)
    now = utc(journal._clock())
    request_pins = _fold_request_pins(
        spec=spec,
        folds=folds,
        requests=requests,
        now=now,
    )
    bound_spec = replace(
        spec,
        frozen_at=now,
        request_bindings_by_fold=request_pins,
    )
    protocol = WalkForwardProtocolV2.build(bound_spec)
    cache = getattr(journal, "_walk_forward_cache", None)
    if cache is None:
        cache = {}
        setattr(journal, "_walk_forward_cache", cache)
    cache_key = canonical_sha256(
        {
            "plan": {
                name: getattr(bound_spec, name)
                for name in bound_spec.__dataclass_fields__
                if name != "frozen_at"
            }
        }
    )
    if cache_key in cache:
        return cache[cache_key]
    event_budget = len(folds) * (
        4
        if spec.selection_mode is OOSSelectionMode.FIXED
        else 4 * len(spec.candidates) + 4
    )
    if (
        event_budget > spec.maximum_events
        or len(journal.snapshot.events)
        + sum(journal._reservations.values())
        + event_budget
        > MAX_EVENTS
    ):
        raise ValueError("WALK_FORWARD_EVENT_BUDGET_EXCEEDED")
    protocols = []
    for fold in protocol.folds:
        existing = next(
            (
                value
                for value in journal._protocols.values()
                if value.journal_id == journal.snapshot.journal_id
                and value.partitions
                == (fold.training, fold.selection_validation, fold.heldout)
                and value.candidates == spec.candidates
                and value.selection_mode is spec.selection_mode
                and value.metrics_policy_sha256 == canonical_sha256(spec.metrics_policy)
                and value.warmup_bars == spec.warmup_bars
                and value.embargo_seconds
                == spec.embargo_bars * spec.metrics_policy.interval_seconds
                and value.environment is spec.environment
                and value.mark_equity
            ),
            None,
        )
        protocols.append(
            existing
            if existing is not None
            else _oos_protocol(journal=journal, spec=bound_spec, fold=fold)
        )
    observations = []
    cancelled = False
    for index, (fold, fold_requests, oos_protocol) in enumerate(
        zip(protocol.folds, requests, protocols, strict=True)
    ):
        candidate_reports: dict[UUID, SpotPerformanceReport] = {}
        failure: str | None = None
        if (
            spec.selection_mode is OOSSelectionMode.VALIDATION_NET_PROFIT
            and not cancelled
        ):
            for candidate, candidate_requests in zip(
                spec.candidates, fold_requests.candidates, strict=True
            ):
                try:
                    assert candidate_requests.training is not None
                    assert candidate_requests.selection_validation is not None
                    await run_spot_oos_partition(
                        journal=journal,
                        protocol=oos_protocol,
                        partition_id=fold.training.partition_id,
                        request=candidate_requests.training,
                        metrics_policy=spec.metrics_policy,
                        session=session,
                        strategy_registry=strategy_registry,
                        lineage_store=lineage_store,
                    )
                    _, report = await run_spot_oos_partition(
                        journal=journal,
                        protocol=oos_protocol,
                        partition_id=fold.selection_validation.partition_id,
                        request=candidate_requests.selection_validation,
                        metrics_policy=spec.metrics_policy,
                        session=session,
                        strategy_registry=strategy_registry,
                        lineage_store=lineage_store,
                    )
                    candidate_reports[candidate.candidate_id] = report
                except asyncio.CancelledError:
                    cancelled = True
                    break
                except Exception:
                    failure = "DEVELOPMENT_TRIAL_FAILED"
                    break
        selected = (
            next(
                (
                    event.candidate_id
                    for event in journal.snapshot.events
                    if event.kind is OOSEventKind.SELECT
                    and event.protocol_sha256 == oos_protocol.content_sha256
                ),
                None,
            )
            if spec.selection_mode is OOSSelectionMode.FIXED
            else None
        )
        if (
            selected is None
            and spec.selection_mode is OOSSelectionMode.VALIDATION_NET_PROFIT
            and not cancelled
            and failure is None
        ):
            try:
                selected = _select_candidate(journal, oos_protocol, candidate_reports)
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                failure = "CANDIDATE_SELECTION_FAILED"
        selected_request = next(
            (
                item.heldout
                for candidate, item in zip(
                    spec.candidates, fold_requests.candidates, strict=True
                )
                if candidate.candidate_id == selected
            ),
            fold_requests.candidates[0].heldout,
        )
        try:
            if cancelled and spec.selection_mode is OOSSelectionMode.FIXED:
                observation = _fold_observation(
                    fold=fold,
                    protocol=oos_protocol,
                    request_bindings=tuple(pin.request for pin in request_pins[index]),
                    journal=journal,
                    spec=bound_spec,
                    cancelled=True,
                )
            else:
                oos_bundle = await run_spot_oos(
                    journal=journal,
                    protocol=oos_protocol,
                    request=selected_request,
                    metrics_policy=spec.metrics_policy,
                    session=session,
                    strategy_registry=strategy_registry,
                    lineage_store=lineage_store,
                    as_of=selected_request.result_as_of,
                    expires_at=selected_request.expires_at,
                )
                oos_result = resolve_spot_oos_result(oos_bundle, journal=journal)
                observation = _fold_observation(
                    fold=fold,
                    protocol=oos_protocol,
                    request_bindings=tuple(pin.request for pin in request_pins[index]),
                    journal=journal,
                    spec=bound_spec,
                    oos_result=oos_result,
                    cancelled=cancelled,
                )
        except asyncio.CancelledError:
            cancelled = True
            observation = _fold_observation(
                fold=fold,
                protocol=oos_protocol,
                request_bindings=tuple(pin.request for pin in request_pins[index]),
                journal=journal,
                spec=bound_spec,
                cancelled=True,
            )
        except Exception:
            observation = _fold_observation(
                fold=fold,
                protocol=oos_protocol,
                request_bindings=tuple(pin.request for pin in request_pins[index]),
                journal=journal,
                spec=bound_spec,
                failure_reason=failure or "WALK_FORWARD_FOLD_EXECUTION_FAILED",
                cancelled=cancelled,
            )
        observations.append(observation)
    for index in range(len(observations), len(protocol.folds)):
        fold = protocol.folds[index]
        observations.append(
            _fold_observation(
                fold=fold,
                protocol=protocols[index],
                request_bindings=tuple(pin.request for pin in request_pins[index]),
                journal=journal,
                spec=bound_spec,
                cancelled=True,
            )
        )
        cancelled = True

    walk_result = _build_result(
        protocol=protocol,
        journal=journal,
        observations=tuple(observations),
    )
    walk_bundle = SpotWalkForwardBundle(walk_result, journal)
    issued = getattr(journal, "_walk_forward_issued", None)
    if issued is None:
        issued = {}
        setattr(journal, "_walk_forward_issued", issued)
    issued[walk_result.content_sha256] = walk_result
    cache[cache_key] = walk_bundle
    if cancelled:
        raise SpotWalkForwardCancelled(walk_result)
    return walk_bundle


def resolve_spot_walk_forward_result(
    bundle: SpotWalkForwardBundle,
    *,
    journal: OOSResearchJournal,
) -> WalkForwardResultV2:
    if (
        type(bundle) is not SpotWalkForwardBundle
        or type(journal) is not OOSResearchJournal
    ):
        raise ValueError("WALK_FORWARD_RESULT_UNAVAILABLE")
    result = decode(encode(bundle.result))
    if (
        type(result) is not WalkForwardResultV2
        or result != bundle.result
        or bundle.journal is not journal
        or journal.snapshot.journal_id != result.journal.journal_id
        or journal.snapshot.events[: len(result.journal.events)]
        != result.journal.events
        or getattr(journal, "_walk_forward_issued", {}).get(result.content_sha256)
        != result
    ):
        raise ValueError("UNAUTHENTICATED_WALK_FORWARD_RESULT")
    return result
