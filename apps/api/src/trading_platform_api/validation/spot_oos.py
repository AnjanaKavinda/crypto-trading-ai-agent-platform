"""Controlled Spot research protocol and archive-bound OOS observation workflow."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from trading_platform_api.contracts.serialization import (
    canonical_json_dumps,
    canonical_sha256,
)
from trading_platform_api.lineage.codec import decode, encode
from trading_platform_api.lineage.store import SqlAlchemyLineageStore
from trading_platform_api.market_data.ohlcv import _TIMEFRAMES
from trading_platform_api.strategy.registry import StrategyRegistry
from trading_platform_api.validation.contracts import (
    CheckOutcome,
    DataPartition,
)
from trading_platform_api.validation.contracts_v2 import ValidationArtifactReferenceV2
from trading_platform_api.validation.oos_contracts_v2 import (
    MAX_EVENTS,
    OOSCandidateV2,
    OOSEventKind,
    OOSJournalEvent,
    OOSJournalSnapshot,
    OOSMetricV2,
    OOSOutcome,
    OOSProtocolV2,
    OOSResultV2,
    OOSRunBindingV2,
    OOSSelectionMode,
    OOSWindow,
    payload,
    require,
    utc,
)
from trading_platform_api.validation.spot_backtest import (
    SpotBacktestBundle,
    SpotBacktestOutcome,
    SpotBacktestRunRequest,
    _artifact,
    _parameters_payload,
    resolve_spot_backtest_result,
    run_spot_backtest,
)
from trading_platform_api.validation.spot_metrics import (
    MetricsPolicy,
    SpotPerformanceReport,
    calculate_spot_performance_metrics,
)


@dataclass(frozen=True, slots=True)
class SpotOOSBundle:
    outcome: OOSOutcome
    reason_codes: tuple[str, ...]
    result: OOSResultV2 | None
    replays: tuple[SpotBacktestBundle, ...]
    reports: tuple[SpotPerformanceReport, ...]
    metrics_policy: MetricsPolicy
    request: SpotBacktestRunRequest


def _execution_digest(policy) -> str:
    return canonical_sha256(payload(policy, {"period_start", "period_end"}))


def candidate_from_request(request: SpotBacktestRunRequest) -> OOSCandidateV2:
    require(type(request) is SpotBacktestRunRequest, "INVALID_OOS_BACKTEST_REQUEST")
    require(
        request.execution_policy.initial_inventory == 0
        and request.execution_policy.initial_cash > 0,
        "OOS_REQUIRES_FLAT_POSITIVE_CAPITAL",
    )
    return OOSCandidateV2(
        ValidationArtifactReferenceV2(
            "C-021",
            request.parameters.strategy_version_id,
            "2",
            request.parameters.strategy_sha256,
        ),
        _artifact(
            "PARAMETER_SET",
            "spot-backtest-parameters-v1",
            _parameters_payload(request.parameters),
        ),
        ValidationArtifactReferenceV2(
            "C-027",
            request.cost_assumptions.assumption_set_id,
            "2",
            request.cost_assumptions.content_sha256,
        ),
        request.cost_adapter.adapter_reference,
        _execution_digest(request.execution_policy),
    )


def _candidate_from_replay(bundle: SpotBacktestBundle) -> OOSCandidateV2:
    result = resolve_spot_backtest_result(bundle)
    assert bundle.trace is not None
    return OOSCandidateV2(
        result.strategy_version,
        result.parameter_set,
        result.cost_assumptions,
        bundle.trace.cost_adapter,
        _execution_digest(bundle.trace.policy),
    )


def _request_digest(request: SpotBacktestRunRequest) -> str:
    return canonical_sha256(
        {
            "inputs": request.replay_inputs,
            "archives": request.archive_pins,
            "dataset": request.execution_dataset_sha256,
            "manifest": request.execution_manifest_sha256,
            "execution": request.execution_policy,
            "parameters": _parameters_payload(request.parameters),
            "costs": request.cost_assumptions,
            "adapter": request.cost_adapter.adapter_reference,
            "as_of": request.result_as_of,
            "created": request.created_at,
            "expiry": request.expires_at,
        }
    )


def _replay_request_digest(replay: SpotBacktestBundle) -> str:
    """Reconstruct the originating request pins after canonical replay resolution."""
    result = resolve_spot_backtest_result(replay)
    assert replay.trace is not None
    trace = replay.trace
    return canonical_sha256(
        {
            "inputs": trace.replay_request,
            "archives": tuple(d.archive_pin for d in trace.decisions),
            "dataset": result.dataset_sha256,
            "manifest": result.manifest_sha256,
            "execution": trace.policy,
            "parameters": _parameters_payload(trace.parameters),
            "costs": trace.cost_assumptions,
            "adapter": trace.cost_adapter,
            "as_of": result.as_of,
            "created": result.created_at,
            "expiry": result.expires_at,
        }
    )


def _request_ref(sha: str) -> ValidationArtifactReferenceV2:
    return ValidationArtifactReferenceV2(
        "SPOT_OOS_REQUEST", uuid5(NAMESPACE_URL, "spot-oos-request-v1:" + sha), "1", sha
    )


class OOSResearchJournal:
    """Injected trusted recorder. Completeness is an explicit source assumption.

    This process-local recorder owns event sequencing and its clock. Exported
    hash chains alone cannot authenticate a research history or resume a session.
    No durable write or universal claim about off-system experiments is made.
    """

    def __init__(
        self,
        *,
        journal_id: UUID,
        authority: ValidationArtifactReferenceV2,
        clock: Callable[[], datetime],
        declared_complete: bool = False,
        prior_history: tuple[OOSJournalEvent, ...] = (),
    ) -> None:
        self._snapshot = OOSJournalSnapshot(
            journal_id, authority, declared_complete, prior_history
        )
        require(callable(clock), "UNRESOLVED_JOURNAL_CLOCK")
        self._clock = clock
        self._protocols: dict[str, OOSProtocolV2] = {}
        self._trials: dict[str, tuple[SpotBacktestBundle, SpotPerformanceReport]] = {}
        self._cache: dict[str, SpotOOSBundle] = {}
        self._inflight: set[str] = set()
        self._issued: dict[str, OOSResultV2] = {}

    @property
    def snapshot(self) -> OOSJournalSnapshot:
        return self._snapshot

    def _append(
        self,
        kind: OOSEventKind,
        window: OOSWindow,
        *,
        protocol: OOSProtocolV2 | None = None,
        candidate: OOSCandidateV2 | None = None,
        purpose: str,
        evidence: tuple[ValidationArtifactReferenceV2, ...] = (),
        at: datetime | None = None,
    ) -> OOSJournalEvent:
        recorded = utc(self._clock()) if at is None else utc(at)
        events = self._snapshot.events
        require(
            len(events) < MAX_EVENTS
            and (not events or events[-1].recorded_at <= recorded),
            "JOURNAL_CLOCK_OR_BUDGET_FAILURE",
        )
        event = OOSJournalEvent.build(
            sequence=len(events),
            recorded_at=recorded,
            kind=kind,
            window=window,
            protocol_sha256=protocol.content_sha256 if protocol else None,
            candidate_id=candidate.candidate_id if candidate else None,
            purpose=purpose,
            evidence=evidence,
            previous_sha256=events[-1].content_sha256 if events else "0" * 64,
        )
        self._snapshot = OOSJournalSnapshot(
            self._snapshot.journal_id,
            self._snapshot.authority,
            self._snapshot.declared_complete,
            (*events, event),
        )
        return event

    def record_access(
        self, window: OOSWindow, *, purpose: str = "INSPECTION"
    ) -> OOSJournalEvent:
        return self._append(OOSEventKind.ACCESS, window, purpose=purpose)


def freeze_spot_oos_protocol(
    *,
    journal: OOSResearchJournal,
    window: OOSWindow,
    partitions: tuple[DataPartition, ...],
    candidates: tuple[OOSCandidateV2, ...],
    selection_mode: OOSSelectionMode,
    metrics_policy: MetricsPolicy,
    warmup_bars: int,
    embargo_seconds: int,
    mark_equity: bool,
    environment,
) -> OOSProtocolV2:
    require(
        type(journal) is OOSResearchJournal and type(metrics_policy) is MetricsPolicy,
        "UNRESOLVED_OOS_INPUTS",
    )
    require(
        metrics_policy.interval_seconds == _TIMEFRAMES[window.timeframe],
        "OOS_METRICS_GRID_MISMATCH",
    )
    require(
        len({c.execution_policy_sha256 for c in candidates}) == 1,
        "INCOMPARABLE_CANDIDATE_EXECUTION_POLICIES",
    )
    at = utc(journal._clock())
    protocol = OOSProtocolV2.build(
        journal_id=journal.snapshot.journal_id,
        authority=journal.snapshot.authority,
        window=window,
        partitions=partitions,
        candidates=candidates,
        selection_mode=selection_mode,
        metrics_policy_sha256=canonical_sha256(metrics_policy),
        minimum_trades=metrics_policy.min_trade_sample,
        warmup_bars=warmup_bars,
        embargo_seconds=embargo_seconds,
        mark_equity=mark_equity,
        environment=environment,
        frozen_at=at,
    )
    require(
        protocol.content_sha256 not in journal._protocols, "PROTOCOL_ALREADY_FROZEN"
    )
    journal._append(
        OOSEventKind.FREEZE, window, protocol=protocol, purpose="PRECOMMITMENT", at=at
    )
    journal._protocols[protocol.content_sha256] = protocol
    if selection_mode is OOSSelectionMode.FIXED:
        select_spot_oos_candidate(
            journal=journal, protocol=protocol, candidate_id=candidates[0].candidate_id
        )
    return protocol


def _window(protocol: OOSProtocolV2, partition: DataPartition) -> OOSWindow:
    return OOSWindow(
        protocol.window.venue,
        protocol.window.instrument_id,
        protocol.window.timeframe,
        partition.start,
        partition.end,
    )


def _receipt(
    journal: OOSResearchJournal, protocol: OOSProtocolV2
) -> OOSJournalEvent | None:
    if journal._protocols.get(protocol.content_sha256) != protocol:
        return None
    return next(
        (
            e
            for e in journal.snapshot.events
            if e.kind is OOSEventKind.FREEZE
            and e.protocol_sha256 == protocol.content_sha256
            and e.recorded_at == protocol.frozen_at
        ),
        None,
    )


def _selected(
    journal: OOSResearchJournal, protocol: OOSProtocolV2
) -> OOSCandidateV2 | None:
    selections = tuple(
        e
        for e in journal.snapshot.events
        if e.kind is OOSEventKind.SELECT
        and e.protocol_sha256 == protocol.content_sha256
    )
    if len(selections) != 1:
        return None
    return next(
        (
            c
            for c in protocol.candidates
            if c.candidate_id == selections[0].candidate_id
        ),
        None,
    )


def select_spot_oos_candidate(
    *, journal: OOSResearchJournal, protocol: OOSProtocolV2, candidate_id: UUID
) -> None:
    require(_receipt(journal, protocol) is not None, "UNRESOLVED_FREEZE_RECEIPT")
    candidate = next(
        (c for c in protocol.candidates if c.candidate_id == candidate_id), None
    )
    require(candidate is not None, "UNKNOWN_OOS_CANDIDATE")
    if protocol.selection_mode is OOSSelectionMode.VALIDATION_NET_PROFIT:
        scores = []
        for item in protocol.candidates:
            trial_reports = []
            for partition in protocol.partitions[:2]:
                matches = tuple(
                    e
                    for e in journal.snapshot.events
                    if e.kind is OOSEventKind.TRIAL
                    and e.protocol_sha256 == protocol.content_sha256
                    and e.candidate_id == item.candidate_id
                    and e.window == _window(protocol, partition)
                )
                require(
                    len(matches) == 1 and matches[0].content_sha256 in journal._trials,
                    "INCOMPLETE_SELECTION_HISTORY",
                )
                trial_reports.append(journal._trials[matches[0].content_sha256][1])
            metric = trial_reports[-1].get("net_realized_profit").metric
            require(metric is not None, "VALIDATION_SELECTION_METRIC_UNAVAILABLE")
            assert metric is not None
            scores.append((metric.value, str(item.candidate_id), item.candidate_id))
        winner = sorted(scores, key=lambda x: (x[0].copy_negate(), x[1]))[0][2]
        require(candidate_id == winner, "SELECTION_CRITERION_MISMATCH")
    journal._append(
        OOSEventKind.SELECT,
        protocol.window,
        protocol=protocol,
        candidate=candidate,
        purpose=protocol.selection_mode.value,
    )


def _preflight(
    journal: OOSResearchJournal, protocol: OOSProtocolV2
) -> tuple[list[str], list[str]]:
    failed: list[str] = []
    missing: list[str] = []
    receipt = _receipt(journal, protocol)
    if receipt is None:
        missing.append("FREEZE_RECEIPT_UNRESOLVED")
        return failed, missing
    if not journal.snapshot.declared_complete:
        missing.append("JOURNAL_COMPLETENESS_UNPROVEN")
    selections = tuple(
        e
        for e in journal.snapshot.events
        if e.kind is OOSEventKind.SELECT
        and e.protocol_sha256 == protocol.content_sha256
    )
    if len(selections) > 1:
        failed.append("SELECTION_CHANGED_AFTER_FREEZE")
    elif not selections:
        missing.append("EXACT_SELECTION_RECEIPT_UNRESOLVED")
    for event in journal.snapshot.events:
        if not event.window.overlaps(protocol.window):
            continue
        if event.kind in (OOSEventKind.ACCESS, OOSEventKind.TRIAL):
            failed.append("HOLDOUT_PREVIOUSLY_ACCESSED_OR_REUSED")
        if event.kind is OOSEventKind.SELECT and event.sequence < receipt.sequence:
            # A prior selection on a reused market window is not a new holdout.
            if any(
                e.kind is OOSEventKind.ACCESS
                and e.window.overlaps(protocol.window)
                and e.sequence < receipt.sequence
                for e in journal.snapshot.events
            ):
                failed.append("HOLDOUT_RESELECTION")
    if selections and selections[0].sequence <= receipt.sequence:
        failed.append("SELECTION_PRECEDES_FREEZE")
    return sorted(set(failed)), sorted(set(missing))


def _validate_request(
    protocol: OOSProtocolV2,
    partition: DataPartition,
    request: SpotBacktestRunRequest,
    metrics_policy: MetricsPolicy,
) -> OOSCandidateV2:
    candidate = candidate_from_request(request)
    require(
        candidate in protocol.candidates, "OOS_STRATEGY_PARAMETERS_OR_COST_MISMATCH"
    )
    require(
        canonical_sha256(metrics_policy) == protocol.metrics_policy_sha256,
        "OOS_METRICS_POLICY_MISMATCH",
    )
    p = request.execution_policy
    require(
        (p.venue, p.instrument_id, p.timeframe, p.environment, p.quote_unit)
        == (
            protocol.window.venue,
            protocol.window.instrument_id,
            protocol.window.timeframe,
            protocol.environment,
            metrics_policy.quote_unit,
        ),
        "OOS_SCOPE_OR_UNIT_MISMATCH",
    )
    require(
        (p.period_start, p.period_end) == (partition.start, partition.end),
        "OOS_EXECUTION_WINDOW_MISMATCH",
    )
    require(
        request.result_as_of <= partition.point_in_time_cutoff, "OOS_CUTOFF_MISMATCH"
    )
    step = timedelta(seconds=_TIMEFRAMES[p.timeframe])
    for decision in request.replay_inputs.decisions:
        require(
            partition.start <= decision.decision_time < partition.end,
            "OOS_DECISION_OUTSIDE_PARTITION",
        )
        require(
            decision.lookback_start >= partition.start - protocol.warmup_bars * step,
            "OOS_WARMUP_EXCEEDED",
        )
    return candidate


def _validate_replay(
    protocol: OOSProtocolV2,
    partition: DataPartition,
    candidate: OOSCandidateV2,
    replay: SpotBacktestBundle,
    request: SpotBacktestRunRequest,
) -> None:
    require(
        replay.outcome is SpotBacktestOutcome.OBSERVED,
        "OOS_DEVELOPMENT_REPLAY_INCONCLUSIVE:" + ",".join(replay.reason_codes),
    )
    require(replay.trace is not None, "OOS_TRACE_UNRESOLVED")
    assert replay.trace is not None
    terminal = replay.trace.exit_trace or replay.trace.entry_trace
    require(
        replay.trace.policy.initial_inventory == 0 and terminal.final_inventory == 0,
        "CROSS_BOUNDARY_OPEN_INVENTORY",
    )
    require(
        all(
            partition.start < f.observed_at <= partition.end
            for trace in (replay.trace.entry_trace, replay.trace.exit_trace)
            if trace
            for f in trace.fills
        ),
        "OOS_FILL_OUTSIDE_PARTITION",
    )
    require(
        all(
            partition.start <= d.decision_time < partition.end
            for d in replay.trace.decisions
        ),
        "OOS_DECISION_OUTSIDE_PARTITION",
    )
    result = resolve_spot_backtest_result(replay)
    require(
        _replay_request_digest(replay) == _request_digest(request),
        "OOS_REPLAY_REQUEST_CLOSURE_MISMATCH",
    )
    require(
        _candidate_from_replay(replay) == candidate, "OOS_REPLAY_CANDIDATE_MISMATCH"
    )
    require(
        (result.period_start, result.period_end) == (partition.start, partition.end),
        "OOS_RESULT_WINDOW_MISMATCH",
    )
    require(
        result.as_of <= partition.point_in_time_cutoff, "OOS_RESULT_CUTOFF_MISMATCH"
    )


async def run_spot_oos_partition(
    *,
    journal: OOSResearchJournal,
    protocol: OOSProtocolV2,
    partition_id: UUID,
    request: SpotBacktestRunRequest,
    metrics_policy: MetricsPolicy,
    session: AsyncSession,
    strategy_registry: StrategyRegistry,
    lineage_store: SqlAlchemyLineageStore,
) -> tuple[SpotBacktestBundle, SpotPerformanceReport]:
    """Record one TRAIN/VALIDATION trial; final holdout uses run_spot_oos."""
    require(_receipt(journal, protocol) is not None, "UNRESOLVED_FREEZE_RECEIPT")
    partition = next(
        (p for p in protocol.partitions[:2] if p.partition_id == partition_id), None
    )
    require(partition is not None, "NOT_A_DEVELOPMENT_PARTITION")
    assert partition is not None
    candidate = _validate_request(protocol, partition, request, metrics_policy)
    require(_selected(journal, protocol) is None, "TUNING_AFTER_SELECTION")
    journal._append(
        OOSEventKind.ACCESS,
        _window(protocol, partition),
        protocol=protocol,
        candidate=candidate,
        purpose="DEVELOPMENT",
    )
    replay = await run_spot_backtest(
        request=request,
        session=session,
        strategy_registry=strategy_registry,
        lineage_store=lineage_store,
    )
    _validate_replay(protocol, partition, candidate, replay, request)
    report = calculate_spot_performance_metrics(
        replay,
        metrics_policy,
        price_path=replay.execution_dataset if protocol.mark_equity else None,
    )
    event = journal._append(
        OOSEventKind.TRIAL,
        _window(protocol, partition),
        protocol=protocol,
        candidate=candidate,
        purpose=partition.purpose.value,
        evidence=(
            _backtest_ref(replay),
            _metrics_ref(report),
            _request_ref(_request_digest(request)),
        ),
    )
    journal._trials[event.content_sha256] = (replay, report)
    return replay, report


def _backtest_ref(replay: SpotBacktestBundle) -> ValidationArtifactReferenceV2:
    result = resolve_spot_backtest_result(replay)
    return ValidationArtifactReferenceV2(
        "C-027", result.result_id, "3", result.content_sha256
    )


def _metrics_ref(report: SpotPerformanceReport) -> ValidationArtifactReferenceV2:
    return ValidationArtifactReferenceV2(
        "SPOT_PERFORMANCE_REPORT", report.report_id, "1", report.content_sha256
    )


def _run_binding(partition, replay, report) -> OOSRunBindingV2:
    result = resolve_spot_backtest_result(replay)
    assert replay.trace is not None
    artifacts = {a.reference: a.document for a in replay.artifacts}
    return OOSRunBindingV2(
        partition.partition_id,
        result,
        _metrics_ref(report),
        _candidate_from_replay(replay),
        artifacts[result.execution_model],
        artifacts[result.configuration],
        replay.trace.cost_assumptions,
        _request_ref(_replay_request_digest(replay)),
        canonical_json_dumps(report),
    )


def _assemble(
    *,
    journal: OOSResearchJournal,
    protocol: OOSProtocolV2,
    metrics_policy: MetricsPolicy,
    request: SpotBacktestRunRequest,
    replays: tuple[SpotBacktestBundle, ...],
    reports: tuple[SpotPerformanceReport, ...],
    failed: list[str],
    integrity_failed: list[str],
    missing: list[str],
    as_of: datetime,
    expires_at: datetime,
) -> SpotOOSBundle:
    selected = _selected(journal, protocol)
    runs = []
    # Include every resolved development trial, without pooling it into holdout metrics.
    for event in journal.snapshot.events:
        if (
            event.kind is OOSEventKind.TRIAL
            and event.protocol_sha256 == protocol.content_sha256
        ):
            trial = journal._trials.get(event.content_sha256)
            if trial is None:
                missing.append("SELECTION_TRIAL_UNRESOLVED")
                continue
            replay, report = trial
            partition = next(
                p
                for p in protocol.partitions[:2]
                if _window(protocol, p) == event.window
            )
            runs.append(_run_binding(partition, replay, report))
            replays = (*replays, replay)
            reports = (*reports, report)
    count = 0
    metrics: tuple[OOSMetricV2, ...] = ()
    held_partition = protocol.partitions[-1]
    held = next(
        (
            (r, m)
            for r, m in zip(replays, reports, strict=True)
            if r.result
            and (r.result.period_start, r.result.period_end)
            == (held_partition.start, held_partition.end)
        ),
        None,
    )
    if held:
        replay, report = held
        count = len(replay.result.simulated_trade_ids) if replay.result else 0
        runs.append(_run_binding(held_partition, replay, report))
        metrics = tuple(
            OOSMetricV2(
                m.name, m.state.value, m.reason, m.metric, m.sample_count, m.warnings
            )
            for m in report.metrics
        )
    if count < protocol.minimum_trades:
        missing.append("INSUFFICIENT_OOS_TRADE_SAMPLE")
    reasons = tuple(sorted(set(failed + integrity_failed + missing)))
    outcome = (
        OOSOutcome.FAILED
        if failed or integrity_failed
        else OOSOutcome.INCONCLUSIVE
        if missing
        else OOSOutcome.OBSERVED
    )
    require(utc(as_of) == request.result_as_of, "OOS_AS_OF_REQUEST_MISMATCH")
    if held:
        require(
            resolve_spot_backtest_result(held[0]).as_of == utc(as_of),
            "OOS_AS_OF_REPLAY_MISMATCH",
        )
    evidence = (_request_ref(_request_digest(request)),) + (
        (_backtest_ref(held[0]), _metrics_ref(held[1])) if held else ()
    )
    previous = journal.snapshot.events[-1] if journal.snapshot.events else None
    # Repeating a preflight-only outcome must not manufacture a new journal
    # event and result identity when no input or recorded history has changed.
    if not (
        previous is not None
        and previous.kind is OOSEventKind.RESULT
        and previous.protocol_sha256 == protocol.content_sha256
        and previous.evidence == evidence
    ):
        journal._append(
            OOSEventKind.RESULT,
            protocol.window,
            protocol=protocol,
            candidate=selected,
            purpose="RECORDED_OUTCOME",
            evidence=evidence,
        )
    snapshot = journal.snapshot
    result = OOSResultV2.build(
        protocol=protocol,
        journal=snapshot,
        selected_candidate=selected,
        runs=tuple(runs),
        metrics=metrics,
        contamination=CheckOutcome.FAILED
        if failed
        else CheckOutcome.INCONCLUSIVE
        if any(
            r in missing
            for r in (
                "JOURNAL_COMPLETENESS_UNPROVEN",
                "FREEZE_RECEIPT_UNRESOLVED",
                "EXACT_SELECTION_RECEIPT_UNRESOLVED",
                "SELECTION_TRIAL_UNRESOLVED",
            )
        )
        else CheckOutcome.PASSED,
        integrity=CheckOutcome.FAILED
        if integrity_failed
        else CheckOutcome.INCONCLUSIVE
        if any(r != "INSUFFICIENT_OOS_TRADE_SAMPLE" for r in missing)
        else CheckOutcome.PASSED,
        sample_sufficiency=CheckOutcome.PASSED
        if count >= protocol.minimum_trades
        else CheckOutcome.INCONCLUSIVE,
        sample_size=count,
        outcome=outcome,
        reason_codes=reasons,
        warnings=(
            "OBSERVED_NOT_QUALIFIED",
            "DECLARED_COMPLETE_RECORDED_HISTORY_ONLY",
            "NO_INDEPENDENCE_OR_INTERVAL_ESTIMATE",
        ),
        as_of=utc(as_of),
        created_at=snapshot.events[-1].recorded_at
        if snapshot.events
        else protocol.frozen_at,
        expires_at=utc(expires_at),
    )
    journal._issued[result.content_sha256] = result
    return SpotOOSBundle(
        outcome, reasons, result, replays, reports, metrics_policy, request
    )


async def run_spot_oos(
    *,
    journal: OOSResearchJournal,
    protocol: OOSProtocolV2,
    request: SpotBacktestRunRequest,
    metrics_policy: MetricsPolicy,
    session: AsyncSession,
    strategy_registry: StrategyRegistry,
    lineage_store: SqlAlchemyLineageStore,
    as_of: datetime,
    expires_at: datetime,
) -> SpotOOSBundle:
    """Run one exact held-out experiment after its authenticated local precommitment."""
    require(
        type(journal) is OOSResearchJournal and type(protocol) is OOSProtocolV2,
        "INVALID_OOS_JOURNAL_OR_PROTOCOL",
    )
    require(utc(as_of) == request.result_as_of, "OOS_AS_OF_REQUEST_MISMATCH")
    require(
        (journal.snapshot.journal_id, journal.snapshot.authority)
        == (protocol.journal_id, protocol.authority),
        "JOURNAL_AUTHORITY_MISMATCH",
    )
    key = canonical_sha256(
        (
            protocol.content_sha256,
            _request_digest(request),
            metrics_policy,
            utc(as_of),
            utc(expires_at),
        )
    )
    if key in journal._cache:
        return journal._cache[key]
    failed, missing = _preflight(journal, protocol)
    integrity_failed: list[str] = []
    selected = _selected(journal, protocol)
    partition = protocol.partitions[-1]
    try:
        candidate = _validate_request(protocol, partition, request, metrics_policy)
        if selected is not None:
            require(candidate == selected, "OOS_REQUEST_NOT_SELECTED_STRATEGY")
    except ValueError as error:
        integrity_failed.append(str(error))
    if failed or integrity_failed or missing:
        return _assemble(
            journal=journal,
            protocol=protocol,
            metrics_policy=metrics_policy,
            request=request,
            replays=(),
            reports=(),
            failed=failed,
            integrity_failed=integrity_failed,
            missing=missing,
            as_of=as_of,
            expires_at=expires_at,
        )
    require(key not in journal._inflight, "OOS_RUN_ALREADY_IN_PROGRESS")
    journal._inflight.add(key)
    try:
        journal._append(
            OOSEventKind.ACCESS,
            protocol.window,
            protocol=protocol,
            candidate=selected,
            purpose="FINAL_HOLDOUT_EXECUTION",
        )
        replay = await run_spot_backtest(
            request=request,
            session=session,
            strategy_registry=strategy_registry,
            lineage_store=lineage_store,
        )
        reports: tuple[SpotPerformanceReport, ...] = ()
        replays: tuple[SpotBacktestBundle, ...] = ()
        if replay.outcome is not SpotBacktestOutcome.OBSERVED:
            missing.extend(("OOS_REPLAY_INCONCLUSIVE", *replay.reason_codes))
        else:
            try:
                assert selected is not None
                _validate_replay(protocol, partition, selected, replay, request)
            except ValueError as error:
                integrity_failed.append(str(error))
            else:
                try:
                    report = calculate_spot_performance_metrics(
                        replay,
                        metrics_policy,
                        price_path=replay.execution_dataset
                        if protocol.mark_equity
                        else None,
                    )
                    replays, reports = (replay,), (report,)
                except ValueError as error:
                    missing.append(str(error))
        bundle = _assemble(
            journal=journal,
            protocol=protocol,
            metrics_policy=metrics_policy,
            request=request,
            replays=replays,
            reports=reports,
            failed=failed,
            integrity_failed=integrity_failed,
            missing=missing,
            as_of=as_of,
            expires_at=expires_at,
        )
        journal._cache[key] = bundle
        return bundle
    finally:
        journal._inflight.discard(key)


def resolve_spot_oos_result(
    bundle: SpotOOSBundle, *, journal: OOSResearchJournal
) -> OOSResultV2:
    """Verify canonical readback, recorder receipt, replay and report closure."""
    require(
        type(bundle) is SpotOOSBundle and type(bundle.result) is OOSResultV2,
        "OOS_RESULT_UNAVAILABLE",
    )
    result = decode(encode(bundle.result))
    require(
        type(result) is OOSResultV2 and result == bundle.result,
        "OOS_CANONICAL_READBACK_MISMATCH",
    )
    assert isinstance(result, OOSResultV2)
    require(
        (bundle.outcome, bundle.reason_codes) == (result.outcome, result.reason_codes),
        "OOS_BUNDLE_OUTCOME_MISMATCH",
    )
    require(
        journal._issued.get(result.content_sha256) == result,
        "UNAUTHENTICATED_OOS_RESULT",
    )
    require(result.as_of == bundle.request.result_as_of, "OOS_AS_OF_REQUEST_MISMATCH")
    require(
        result.journal.events[-1].kind is OOSEventKind.RESULT
        and _request_ref(_request_digest(bundle.request))
        in result.journal.events[-1].evidence,
        "OOS_REQUEST_RECEIPT_MISMATCH",
    )
    require(
        canonical_sha256(bundle.metrics_policy)
        == result.protocol.metrics_policy_sha256,
        "OOS_METRICS_POLICY_MISMATCH",
    )
    require(
        type(journal) is OOSResearchJournal
        and _receipt(journal, result.protocol) is not None,
        "UNRESOLVED_FREEZE_RECEIPT",
    )
    require(
        result.journal.events == journal.snapshot.events[: len(result.journal.events)]
        and result.journal.authority == journal.snapshot.authority
        and result.journal.journal_id == journal.snapshot.journal_id,
        "UNAUTHENTICATED_JOURNAL_SNAPSHOT",
    )
    require(
        len(bundle.replays) == len(bundle.reports) == len(result.runs),
        "OOS_RUN_CLOSURE_INCOMPLETE",
    )
    observed = {}
    for replay, report in zip(bundle.replays, bundle.reports, strict=True):
        backtest = resolve_spot_backtest_result(replay)
        require(
            calculate_spot_performance_metrics(
                replay,
                bundle.metrics_policy,
                price_path=replay.execution_dataset
                if result.protocol.mark_equity
                else None,
            )
            == report,
            "OOS_METRICS_CLOSURE_MISMATCH",
        )
        observed[(backtest.result_id, report.report_id)] = (
            backtest,
            _metrics_ref(report),
        )
    for binding in result.runs:
        require(
            observed.get(
                (binding.backtest.result_id, binding.metrics_report.artifact_id)
            )
            == (binding.backtest, binding.metrics_report),
            "OOS_RUN_REFERENCE_MISMATCH",
        )
        replay = next(r for r in bundle.replays if r.result == binding.backtest)
        partition = next(
            p
            for p in result.protocol.partitions
            if p.partition_id == binding.partition_id
        )
        held = partition == result.protocol.partitions[-1]
        require(
            any(
                e.kind is (OOSEventKind.RESULT if held else OOSEventKind.TRIAL)
                and e.protocol_sha256 == result.protocol.content_sha256
                and e.window == _window(result.protocol, partition)
                and _backtest_ref(replay) in e.evidence
                and binding.metrics_report in e.evidence
                and _request_ref(_replay_request_digest(replay)) in e.evidence
                for e in result.journal.events
            ),
            "OOS_RUN_REQUEST_RECEIPT_MISMATCH",
        )
        if held:
            require(
                _replay_request_digest(replay) == _request_digest(bundle.request),
                "OOS_REPLAY_REQUEST_CLOSURE_MISMATCH",
            )
            require(result.as_of == binding.backtest.as_of, "OOS_AS_OF_REPLAY_MISMATCH")
    return result
