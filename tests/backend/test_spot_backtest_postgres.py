"""Persisted offline Spot replay against an isolated PostgreSQL schema."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import timedelta
from decimal import Context, Decimal, localcontext
from hashlib import sha256
from io import StringIO
from uuid import uuid4, uuid5

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_lineage_postgresql import database_url as database_url
from test_spot_research_api import (
    INSTRUMENT,
    refresh_body,
    spot_producer_runtime,
)
from test_spot_research_api import persisted_service as persisted_service
from test_strategy_condition_evaluator import _setup
from trading_platform_api.analysis.contracts import AnalyticalDirection
from trading_platform_api.analysis.spot_meta_analysis import FindingReadiness
from trading_platform_api.analysis.versioned_contracts_v4 import (
    AnalysisSnapshotV4,
    ResolvedSpotOHLCVBindingV4,
)
from trading_platform_api.config import (
    AppSettings,
    DeploymentEnvironment,
    OperatingMode,
)
from trading_platform_api.contracts.serialization import (
    canonical_json_dumps,
    canonical_sha256,
)
from trading_platform_api.lineage.codec import LineageError, LineageKey, decode, encode
from trading_platform_api.lineage.store import SqlAlchemyLineageStore
from trading_platform_api.main import create_app
from trading_platform_api.market_data.contracts import (
    DatasetVersion,
    DataSourceRecord,
    MarketData,
    MetricValue,
)
from trading_platform_api.market_data.history_contracts import (
    HistoricalUniverse,
    ObservationRevision,
)
from trading_platform_api.market_data.history_selection import reconstruct_history
from trading_platform_api.spot_research_store import (
    SqlAlchemySpotResearchStore,
    spot_producer_request_reservations,
)
from trading_platform_api.strategy.condition_evaluator import (
    build_spot_condition_context,
)
from trading_platform_api.strategy.contracts import (
    ConditionOperator,
    StrategyCondition,
    StrategyLifecycle,
    VersionReference,
)
from trading_platform_api.strategy.registry import (
    ArtifactVersionLifecycle,
    LifecycleAxis,
    ResolvedLifecycleReference,
    StrategyAvailability,
    StrategyRegistry,
    build_personal_spot_strategy_v2,
    strategy_version_content_sha256,
)
from trading_platform_api.strategy.registry_store import SqlAlchemyStrategyRegistryStore
from trading_platform_api.strategy_api import _compose_persisted_spot_debate
from trading_platform_api.validation.contracts import DataPartition, PartitionPurpose
from trading_platform_api.validation.contracts_v2 import ValidationArtifactReferenceV2
from trading_platform_api.validation.cost_models import (
    CostSourceKind,
    SpotExecutionCostProfile,
    build_spot_cost_assumption_set,
)
from trading_platform_api.validation.oos_contracts_v2 import (
    NAMESPACE,
    OOSJournalEvent,
    OOSOutcome,
    OOSSelectionMode,
    OOSWindow,
    _wire,
    payload,
)
from trading_platform_api.validation.spot_backtest import (
    SpotBacktestArchivePin,
    SpotBacktestOutcome,
    SpotBacktestParameters,
    SpotBacktestRunRequest,
    resolve_spot_backtest_result,
    run_spot_backtest,
)
from trading_platform_api.validation.spot_cost_adapter import SpotExecutionCostAdapter
from trading_platform_api.validation.spot_execution import SpotExecutionPolicy
from trading_platform_api.validation.spot_metrics import (
    METHOD as METRICS_METHOD,
)
from trading_platform_api.validation.spot_metrics import (
    InitialRisk,
    MetricsInputError,
    MetricsPolicy,
    MetricState,
    calculate_spot_performance_metrics,
)
from trading_platform_api.validation.spot_oos import (
    OOSResearchJournal,
    candidate_from_request,
    freeze_spot_oos_protocol,
    resolve_spot_oos_result,
    run_spot_oos,
    run_spot_oos_partition,
    select_spot_oos_candidate,
)
from trading_platform_api.validation.spot_replay_inputs import (
    SpotReplayDecisionRequest,
    SpotReplayInputRequest,
    SpotReplayLimits,
    SpotReplayScope,
    SpotReplayStrategyPin,
)
from trading_platform_api.validation.spot_walk_forward import (
    SpotWalkForwardCandidateRequests,
    SpotWalkForwardFoldRequests,
    resolve_spot_walk_forward_result,
    run_spot_walk_forward,
)
from trading_platform_api.validation.walk_forward_contracts_v2 import (
    WalkForwardMode,
    WalkForwardPlanSpecV2,
    generate_walk_forward_folds,
)

D = Decimal
STEP = timedelta(minutes=1)


class _ReferenceResolver:
    def __init__(self) -> None:
        self.references: dict[VersionReference, ResolvedLifecycleReference] = {}

    def bind(self, reference: VersionReference, subject_id, status: str) -> None:
        self.references[reference] = ResolvedLifecycleReference(
            reference, status, subject_id
        )

    async def resolve(self, reference: VersionReference, *, at):
        return self.references.get(reference)


def _reference(kind: str) -> VersionReference:
    return VersionReference(kind, uuid4(), "1", "a" * 64)


def _bind_transition(
    resolver: _ReferenceResolver,
    subject_id,
    *,
    evidence_kind: str = "C-030",
    evidence_status: str = "AVAILABLE",
):
    decision = _reference("C-057")
    evidence = _reference(evidence_kind)
    resolver.bind(decision, subject_id, "APPROVED")
    resolver.bind(evidence, subject_id, evidence_status)
    return decision, (evidence,)


async def _register_backtest_strategy(
    registry: StrategyRegistry,
    resolver: _ReferenceResolver,
    identity,
    parent,
    version,
    *,
    effective_at,
    register_identity: bool = True,
) -> None:
    if register_identity:
        decision, evidence = _bind_transition(resolver, identity.strategy_id)
        await registry.register_strategy(
            identity,
            actor="synthetic-postgres-replay",
            reason="isolated persisted backtest fixture",
            decision_reference=decision,
            evidence_references=evidence,
            effective_at=effective_at,
        )
    for item in (parent, version) if parent is not None else (version,):
        decision = _reference("C-057")
        resolver.bind(decision, item.strategy_version_id, "APPROVED")
        evidence = item.provenance
        for reference in evidence:
            resolver.bind(reference, item.strategy_version_id, "AVAILABLE")
        await registry.register_version(
            item,
            actor="synthetic-postgres-replay",
            reason="explicit immutable BACKTEST strategy fixture",
            decision_reference=decision,
            evidence_references=evidence,
            effective_at=effective_at,
        )
    decision, evidence = _bind_transition(
        resolver,
        version.strategy_version_id,
        evidence_kind="C-028",
        evidence_status="PASSED",
    )
    result = await registry.transition(
        axis=LifecycleAxis.C021_VERSION,
        strategy_id=version.strategy_id,
        strategy_version_id=version.strategy_version_id,
        to_status="VALIDATED",
        actor="synthetic-postgres-replay",
        reason="synthetic exact-version replay eligibility",
        decision_reference=decision,
        evidence_references=evidence,
        environment=DeploymentEnvironment.TEST,
        operating_mode=OperatingMode.BACKTEST,
        effective_at=effective_at + timedelta(seconds=1),
    )
    assert result.accepted
    for offset, status in enumerate(
        (
            ArtifactVersionLifecycle.CANDIDATE.value,
            ArtifactVersionLifecycle.VALIDATED.value,
        ),
        start=2,
    ):
        decision, evidence = _bind_transition(
            resolver,
            version.strategy_version_id,
            evidence_kind="C-028" if status.endswith("VALIDATED") else "C-030",
            evidence_status="PASSED" if status.endswith("VALIDATED") else "AVAILABLE",
        )
        result = await registry.transition(
            axis=LifecycleAxis.ARTIFACT_VERSION,
            strategy_id=version.strategy_id,
            strategy_version_id=version.strategy_version_id,
            to_status=status,
            actor="synthetic-postgres-replay",
            reason="synthetic exact-version replay eligibility",
            decision_reference=decision,
            evidence_references=evidence,
            environment=DeploymentEnvironment.TEST,
            operating_mode=OperatingMode.BACKTEST,
            effective_at=effective_at + timedelta(seconds=offset),
        )
        assert result.accepted


def _market_records(
    observations: tuple[MarketData, ...],
    sources: tuple[DataSourceRecord, ...],
    *,
    cutoff,
    dataset_id: str,
    venue: str,
    instrument_id: str,
    extra_bars: int = 0,
    extra_start=None,
):
    source_by_id = {item.source_record_id: item for item in sources}
    revisions: list[ObservationRevision] = []
    all_observations = list(observations)
    all_sources = list(sources)

    for index in range(extra_bars):
        opened = (extra_start or cutoff) + (index + 1) * STEP
        closed = opened + STEP
        source_id = uuid4()
        template = sources[0]
        source = DataSourceRecord(
            source_id,
            template.provider_id,
            template.provider_version,
            opened,
            closed,
            closed,
            template.raw_schema_version,
            template.adapter_version,
            template.licensing_reference,
            canonical_sha256((dataset_id, opened, "source")),
        )
        prior_close = (
            next(
                item.value
                for item in all_observations[-1].metrics
                if item.metric_name == "close"
            )
            if all_observations
            else D("100")
        )
        opened_price = prior_close
        closed_price = prior_close + D("1")
        observation = MarketData(
            uuid4(),
            instrument_id,
            venue,
            "OHLCV",
            opened,
            closed,
            closed,
            closed,
            source_id,
            (
                MetricValue("open", opened_price, "USDT"),
                MetricValue("high", closed_price + D("1"), "USDT"),
                MetricValue("low", opened_price - D("1"), "USDT"),
                MetricValue("close", closed_price, "USDT"),
                MetricValue("volume", D("10"), "BTC"),
            ),
        )
        all_sources.append(source)
        all_observations.append(observation)
        source_by_id[source_id] = source

    for observation in all_observations:
        source = source_by_id[observation.source_record_id]
        finality = observation.event_time + STEP
        publication = max(
            observation.provider_time, source.provider_event_time, finality
        )
        ingestion = max(publication, observation.ingestion_time, source.retrieval_time)
        availability = max(
            ingestion, observation.availability_time, source.availability_time
        )
        revisions.append(
            ObservationRevision(
                uuid4(),
                source.provider_id,
                str(observation.market_data_id),
                None,
                observation,
                publication,
                ingestion,
                availability,
                finality,
            )
        )

    universe_source = min(all_sources, key=lambda item: item.availability_time)
    universe = HistoricalUniverse(
        f"synthetic-{dataset_id}",
        "1",
        "synthetic-spot-universe-v1",
        venue,
        min(item.event_time for item in all_observations) - STEP,
        cutoff + timedelta(days=1),
        universe_source.provider_event_time,
        universe_source.retrieval_time,
        universe_source.availability_time,
        (instrument_id,),
        (universe_source.source_record_id,),
        True,
    )
    used_source_ids = {
        universe_source.source_record_id,
        *(item.observation.source_record_id for item in revisions),
    }
    used_sources = tuple(
        sorted(
            (item for item in all_sources if item.source_record_id in used_source_ids),
            key=lambda item: str(item.source_record_id),
        )
    )
    lineage_sha256 = canonical_sha256(
        {
            "sources": tuple(canonical_sha256(item) for item in used_sources),
            "revisions": tuple(canonical_sha256(item) for item in revisions),
        }
    )
    dataset = DatasetVersion(
        dataset_id,
        "1",
        cutoff,
        min(item.event_time for item in all_observations),
        cutoff,
        cutoff,
        tuple(sorted(used_source_ids, key=str)),
        "1",
        lineage_sha256,
    )
    reconstruction = reconstruct_history(
        cutoff=cutoff,
        universe=universe,
        revisions=tuple(revisions),
        sources=used_sources,
        dataset=dataset,
        expected_universe_sha256=canonical_sha256(universe),
        expected_lineage_sha256=lineage_sha256,
    )
    records = (
        *used_sources,
        universe,
        dataset,
        *all_observations,
        *revisions,
        reconstruction.manifest,
    )
    return dataset, reconstruction.manifest, records, reconstruction


async def _append_dataset(store: SqlAlchemyLineageStore, records) -> None:
    for record in records:
        await store.append(record)


def _cost_adapter(*, version, scope, as_of, valid_until):
    profile = SpotExecutionCostProfile(
        scope.venue_id,
        scope.instrument_id,
        scope.asset,
        scope.price_unit,
        scope.volume_unit,
        "synthetic-taker-tier-v1",
        # Explicit test configuration reference; no exchange fee claim is made.
        source_reference=ValidationArtifactReferenceV2(
            "SYNTHETIC_COST_CONFIGURATION", uuid4(), "1", "c" * 64
        ),
        source_kind=CostSourceKind.CONFIGURED_RESEARCH_ASSUMPTION,
        methodology_version="spot-cost-model-v1",
        maker_fee_bps=D("10"),
        taker_fee_bps=D("10"),
        spread_bps=D("4"),
        slippage_bps=D("6"),
        latency_bars=0,
        stress_multiplier=D("1"),
        available_at=as_of,
        effective_from=as_of,
        valid_until=valid_until,
    )
    assumptions = build_spot_cost_assumption_set(
        profile=profile,
        strategy_version_id=version.strategy_version_id,
        as_of=as_of,
    )
    return SpotExecutionCostAdapter(profile, assumptions)


def _oos_substitution_requests(request, execution_dataset):
    return {
        "dataset_id": replace(
            request,
            execution_dataset_sha256=canonical_sha256(
                replace(execution_dataset, dataset_id="different-native-id")
            ),
        ),
        "dataset_version": replace(
            request,
            execution_dataset_sha256=canonical_sha256(
                replace(execution_dataset, version="different-version")
            ),
        ),
        "dataset_digest": replace(request, execution_dataset_sha256="1" * 64),
        "manifest_digest": replace(request, execution_manifest_sha256="2" * 64),
        "archive_pin": replace(
            request,
            archive_pins=(
                replace(request.archive_pins[0], context_id=uuid4()),
                *request.archive_pins[1:],
            ),
        ),
        "replay_inputs": replace(
            request,
            replay_inputs=replace(
                request.replay_inputs,
                decisions=(
                    replace(
                        request.replay_inputs.decisions[0],
                        dataset_sha256="3" * 64,
                    ),
                    *request.replay_inputs.decisions[1:],
                ),
            ),
        ),
        "replay_as_of": replace(request, result_as_of=request.result_as_of - STEP),
    }


async def _fresh_oos_archive(request, at, session, lineage, research, app):
    clock, runtime, monotonic = (
        research.clock,
        research.spot_agent_runtime,
        research.monotonic,
    )
    try:
        research.clock = lambda: at
        research.monotonic = lambda: monotonic() + (at - clock()).total_seconds()
        research.spot_agent_runtime = spot_producer_runtime(at)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client:
            response = await client.post(
                f"/api/research/spot/{INSTRUMENT}/refresh",
                json=refresh_body(timeframe="1m", limit=50, now=at),
            )
        assert response.status_code == 200, response.text
    finally:
        research.clock, research.spot_agent_runtime, research.monotonic = (
            clock,
            runtime,
            monotonic,
        )
    row = (
        (
            await session.execute(
                select(spot_producer_request_reservations).where(
                    spot_producer_request_reservations.c.snapshot_id
                    == response.json()["snapshot_id"],
                    spot_producer_request_reservations.c.status == "COMPLETED",
                )
            )
        )
        .mappings()
        .one()
    )
    key = LineageKey(
        row["context_contract_id"], row["context_record_id"], row["context_version"]
    )
    context = await lineage.get(key)
    result, evaluation, correlation_id, trace_id = await lineage.get_spot_agent_handoff(
        key
    )
    decision_time = max(
        context.as_of, evaluation.ended_at, result.generated_at
    ) + timedelta(seconds=2)
    inputs = await _compose_persisted_spot_debate(
        session=session,
        store=lineage,
        context_key=key,
        context=context,
        result=result,
        evaluation=evaluation,
        correlation_id=correlation_id,
        trace_id=trace_id,
        now=decision_time,
    )
    binding = inputs.resolved_bindings[0]
    data, manifest, records, _ = _market_records(
        binding.observations,
        binding.sources,
        cutoff=context.as_of,
        dataset_id=f"decision-{uuid4()}",
        venue=request.execution_policy.venue,
        instrument_id=request.execution_policy.instrument_id,
    )
    await _append_dataset(lineage, records)
    pin = SpotBacktestArchivePin(
        context.context_id,
        canonical_sha256(context),
        canonical_sha256(inputs.manifest),
        result.result_id,
        canonical_sha256(result),
        evaluation.evaluation_id,
        canonical_sha256(evaluation),
        sha256(canonical_json_dumps(inputs.fanout.outcomes).encode()).hexdigest(),
    )
    decision = SpotReplayDecisionRequest(
        decision_time,
        context.as_of,
        canonical_sha256(data),
        canonical_sha256(manifest),
        binding.binding.window_start,
        binding.binding.window_end,
    )
    return (pin,), replace(request.replay_inputs, decisions=(decision,)), binding


async def _development_oos(
    request, metrics, binding, session, registry, lineage, research, app
):
    metrics = replace(metrics, report_timestamp=request.created_at + timedelta(hours=1))
    start = request.execution_policy.period_start
    edges = (
        start,
        start + 5 * STEP,
        start + 10 * STEP,
        start + 15 * STEP,
    )
    parts = tuple(
        DataPartition(uuid4(), role, edges[i], edges[i + 1], edges[i + 1], i == 0)
        for i, role in enumerate(
            (PartitionPurpose.TRAIN, PartitionPurpose.VALIDATION, PartitionPurpose.TEST)
        )
    )
    requests = {}
    for i, part in enumerate(parts):
        pins, replay_inputs, current_binding = (
            (request.archive_pins, request.replay_inputs, binding)
            if i == 0
            else await _fresh_oos_archive(
                request, part.start, session, lineage, research, app
            )
        )
        dataset, manifest, records, _ = _market_records(
            current_binding.observations,
            current_binding.sources,
            cutoff=part.end,
            dataset_id=f"development-{uuid4()}",
            venue=request.execution_policy.venue,
            instrument_id=request.execution_policy.instrument_id,
            extra_bars=int((part.end - part.start) / STEP),
            extra_start=part.start - STEP,
        )
        await _append_dataset(lineage, records)
        for quantity in (D("1"), D("0.5")):
            requests[i, quantity] = replace(
                request,
                archive_pins=pins,
                replay_inputs=replace(
                    replay_inputs,
                    scope=replace(
                        request.replay_inputs.scope,
                        decision_period_start=part.start,
                        decision_period_end=part.end,
                    ),
                    decisions=replay_inputs.decisions,
                ),
                execution_dataset_sha256=canonical_sha256(dataset),
                execution_manifest_sha256=canonical_sha256(manifest),
                execution_policy=replace(
                    request.execution_policy,
                    period_start=part.start,
                    period_end=part.end,
                ),
                parameters=replace(
                    request.parameters,
                    quantity=quantity,
                ),
                result_as_of=part.end,
                created_at=max(request.created_at, part.end + timedelta(seconds=1)),
            )
    at = request.created_at + timedelta(hours=2)
    journal = OOSResearchJournal(
        journal_id=uuid4(),
        authority=ValidationArtifactReferenceV2(
            "SYNTHETIC_RECORDER", uuid4(), "1", "e" * 64
        ),
        clock=lambda: at,
        declared_complete=True,
    )
    candidates = tuple(
        candidate_from_request(requests[0, q]) for q in (D("1"), D("0.5"))
    )
    p = request.execution_policy
    protocol = freeze_spot_oos_protocol(
        journal=journal,
        window=OOSWindow(
            p.venue, p.instrument_id, p.timeframe, parts[-1].start, parts[-1].end
        ),
        partitions=parts,
        candidates=candidates,
        selection_mode=OOSSelectionMode.VALIDATION_NET_PROFIT,
        metrics_policy=metrics,
        warmup_bars=64,
        embargo_seconds=0,
        mark_equity=True,
        environment=p.environment,
    )
    scores = []
    for quantity in (D("1"), D("0.5")):
        for i in (0, 1):
            replay, report = await run_spot_oos_partition(
                journal=journal,
                protocol=protocol,
                partition_id=parts[i].partition_id,
                request=requests[i, quantity],
                metrics_policy=metrics,
                session=session,
                strategy_registry=registry,
                lineage_store=lineage,
            )
            assert replay.result.period_start == parts[i].start
        scores.append(
            (
                report.get("net_realized_profit").metric.value,
                str(candidate_from_request(requests[0, quantity]).candidate_id),
                quantity,
            )
        )
    winner = sorted(scores, key=lambda x: (-x[0], x[1]))[0][2]
    winner_id = candidate_from_request(requests[0, winner]).candidate_id
    # Use the real public-runner trials; every corruption must fail before SELECT.
    snapshot = journal.snapshot
    event = snapshot.events[-1]
    trial = journal._trials[event.content_sha256]
    for altered in (
        (None, trial[1]),
        (trial[0], replace(trial[1], result_sha256="f" * 64)),
        (
            trial[0],
            calculate_spot_performance_metrics(
                trial[0],
                replace(metrics, min_trade_sample=metrics.min_trade_sample + 1),
                price_path=trial[0].execution_dataset,
            ),
        ),
        journal._trials[
            next(e.content_sha256 for e in snapshot.events if e.kind.value == "TRIAL")
        ],
    ):
        journal._trials[event.content_sha256] = altered
        with pytest.raises(ValueError):
            select_spot_oos_candidate(
                journal=journal, protocol=protocol, candidate_id=winner_id
            )
        assert journal.snapshot == snapshot
    journal._trials[event.content_sha256] = trial
    for evidence in (
        (),
        event.evidence[:2],
        (*event.evidence[:2], replace(event.evidence[2], content_sha256="f" * 64)),
    ):
        altered = OOSJournalEvent.build(
            **dict(payload(event, {"content_sha256"}), evidence=evidence)
        )
        journal._snapshot = replace(snapshot, events=(*snapshot.events[:-1], altered))
        journal._trials[altered.content_sha256] = trial
        with pytest.raises(ValueError, match="TRIAL_EVIDENCE"):
            select_spot_oos_candidate(
                journal=journal, protocol=protocol, candidate_id=winner_id
            )
    journal._snapshot = snapshot
    held = requests[2, winner]
    pending = await run_spot_oos(
        journal=journal,
        protocol=protocol,
        request=held,
        metrics_policy=metrics,
        session=session,
        strategy_registry=registry,
        lineage_store=lineage,
        as_of=held.result_as_of,
        expires_at=held.expires_at,
    )
    assert pending.outcome is OOSOutcome.INCONCLUSIVE
    assert len(resolve_spot_oos_result(pending, journal=journal).runs) == 4
    assert not any(
        e.purpose == "FINAL_HOLDOUT_EXECUTION" for e in journal.snapshot.events
    )
    select_spot_oos_candidate(
        journal=journal,
        protocol=protocol,
        candidate_id=candidate_from_request(requests[0, winner]).candidate_id,
    )
    held = requests[2, winner]
    selected_snapshot = journal.snapshot
    journal._trials[event.content_sha256] = (None, trial[1])
    with pytest.raises(ValueError, match="TRIAL_EVIDENCE"):
        await run_spot_oos(
            journal=journal,
            protocol=protocol,
            request=held,
            metrics_policy=metrics,
            session=session,
            strategy_registry=registry,
            lineage_store=lineage,
            as_of=held.result_as_of,
            expires_at=held.expires_at,
        )
    assert journal.snapshot == selected_snapshot
    journal._trials[event.content_sha256] = trial
    result = await run_spot_oos(
        journal=journal,
        protocol=protocol,
        request=held,
        metrics_policy=metrics,
        session=session,
        strategy_registry=registry,
        lineage_store=lineage,
        as_of=held.result_as_of,
        expires_at=held.expires_at,
    )
    resolved = resolve_spot_oos_result(result, journal=journal)
    assert len(resolved.runs) == 5
    assert sum(r.partition_id == parts[-1].partition_id for r in resolved.runs) == 1
    assert resolved.sample_size == len(
        next(
            r for r in resolved.runs if r.partition_id == parts[-1].partition_id
        ).backtest.simulated_trade_ids
    )
    _assert_oos_contract_rejections(resolved)
    _assert_selection_contract_rejections(resolved)
    return result


def _assert_oos_contract_rejections(result):
    values = {
        k: v
        for k, v in result.identity_payload().items()
        if k not in {"method", "contract_id", "schema_version", "operating_mode"}
    }
    for kind in ("FREEZE", "SELECT", "RESULT"):
        events = []
        for event in result.journal.events:
            if event.kind.value == kind:
                continue
            events.append(
                OOSJournalEvent.build(
                    **dict(
                        payload(
                            event, {"sequence", "previous_sha256", "content_sha256"}
                        ),
                        sequence=len(events),
                        previous_sha256=events[-1].content_sha256
                        if events
                        else "0" * 64,
                    )
                )
            )
        journal = replace(result.journal, events=tuple(events))
        with pytest.raises(ValueError, match="RECEIPT"):
            type(result).build(**dict(values, journal=journal))
    with pytest.raises(ValueError, match="RECEIPT"):
        type(result).build(
            **dict(values, journal=replace(result.journal, declared_complete=False))
        )
    run = result.runs[0]
    for alter in (
        lambda: replace(run, partition_id=uuid4()),
        lambda: replace(
            run, metrics_report=replace(run.metrics_report, content_sha256="f" * 64)
        ),
    ):
        with pytest.raises(ValueError):
            altered = alter()
            type(result).build(**dict(values, runs=(altered, *result.runs[1:])))
    for field in ("configuration", "execution_model", "report_document"):
        with pytest.raises(ValueError, match="ARTIFACT|REPORT"):
            replace(run, **{field: getattr(run, field) + " "})
    with pytest.raises(ValueError, match="REQUEST_DIGEST"):
        replace(run, request=replace(run.request, content_sha256="f" * 64))
    raw = json.loads(encode(result))
    raw["payload"]["journal"]["declared_complete"] = False
    with pytest.raises(LineageError, match="corrupt"):
        decode(json.dumps(raw))
    _assert_metric_projection_rejections(result, values)
    with pytest.raises(ValueError, match="OOS_EXPIRY_EXCEEDS_RUN"):
        type(result).build(
            **dict(
                values,
                expires_at=max(r.backtest.expires_at for r in result.runs) + STEP,
            )
        )


def _assert_metric_projection_rejections(result, values):
    index = next(i for i, m in enumerate(result.metrics) if m.name == "total_trades")
    missing_index = next(
        i for i, m in enumerate(result.metrics) if m.state == "UNAVAILABLE"
    )
    metric, missing = result.metrics[index], result.metrics[missing_index]
    changes = (
        (
            index,
            replace(
                metric, value=replace(metric.value, value=metric.value.value + D(1))
            ),
        ),
        (
            index,
            replace(metric, state="UNAVAILABLE", value=None, reason="ALTERED_STATE"),
        ),
        (missing_index, replace(missing, reason="ALTERED_REASON")),
        (index, replace(metric, warnings=(*metric.warnings, "ALTERED_WARNING"))),
        (index, replace(metric, sample_count=metric.sample_count + 1)),
    )
    original = json.loads(encode(result))

    assert _oos_wire_identity(original) == result.content_sha256
    expired = json.loads(encode(result))
    expired["payload"]["expires_at"] = (
        (max(r.backtest.expires_at for r in result.runs) + STEP)
        .isoformat()
        .replace("+00:00", "Z")
    )
    sha = _oos_wire_identity(expired)
    expired["payload"]["content_sha256"] = sha
    expired["payload"]["result_id"] = str(uuid5(NAMESPACE, "result:" + sha))
    with pytest.raises(LineageError, match="corrupt"):
        decode(json.dumps(expired))
    for at, altered in changes:
        metrics = (*result.metrics[:at], altered, *result.metrics[at + 1 :])
        with pytest.raises(ValueError, match="OOS_METRICS_REPORT_MISMATCH"):
            type(result).build(**dict(values, metrics=metrics))
        raw = json.loads(encode(result))
        raw["payload"]["metrics"][at] = json.loads(canonical_json_dumps(altered))
        sha = _oos_wire_identity(raw)
        raw["payload"]["content_sha256"] = sha
        raw["payload"]["result_id"] = str(uuid5(NAMESPACE, "result:" + sha))
        with pytest.raises(LineageError, match="corrupt"):
            decode(json.dumps(raw))


def _oos_wire_identity(raw):
    return canonical_sha256(
        _wire(
            dict(
                {
                    k: v
                    for k, v in raw["payload"].items()
                    if k not in {"result_id", "content_sha256"}
                },
                contract_id=raw["contract_id"],
                schema_version=raw["schema_version"],
            )
        )
    )


def _assert_selection_contract_rejections(result):
    values = {
        k: v
        for k, v in result.identity_payload().items()
        if k not in {"method", "contract_id", "schema_version", "operating_mode"}
    }

    def rechain(events):
        chain = []
        for event in events:
            chain.append(
                OOSJournalEvent.build(
                    **dict(
                        payload(
                            event, {"sequence", "previous_sha256", "content_sha256"}
                        ),
                        sequence=len(chain),
                        previous_sha256=chain[-1].content_sha256 if chain else "0" * 64,
                    )
                )
            )
        return replace(result.journal, events=tuple(chain))

    def reject(changes, match):
        with pytest.raises(ValueError, match=match):
            type(result).build(**dict(values, **changes))
        raw = json.loads(encode(result))
        raw["payload"].update(
            {k: json.loads(canonical_json_dumps(v)) for k, v in changes.items()}
        )
        sha = _oos_wire_identity(raw)
        raw["payload"].update(
            content_sha256=sha, result_id=str(uuid5(NAMESPACE, "result:" + sha))
        )
        with pytest.raises(LineageError, match="corrupt"):
            decode(json.dumps(raw))

    reject({"runs": (*result.runs, result.runs[0])}, "DUPLICATE_OOS_RUN")
    reject({"runs": result.runs[1:]}, "SELECTION_MATRIX")
    reject(
        {
            "integrity": result.integrity.__class__.FAILED,
            "outcome": OOSOutcome.FAILED,
            "reason_codes": ("OOS_SCOPE_OR_UNIT_MISMATCH",),
        },
        "RESULT_RECEIPT|INTEGRITY_STATUS",
    )
    if result.sample_sufficiency.value == "PASSED":
        reject(
            {
                "outcome": OOSOutcome.INCONCLUSIVE,
                "reason_codes": ("ARBITRARY_DOWNGRADE",),
            },
            "INTEGRITY_STATUS",
        )
    select = next(e for e in result.journal.events if e.kind.value == "SELECT")
    altered = OOSJournalEvent.build(
        **dict(payload(select, {"content_sha256"}), purpose="FORGED_PURPOSE")
    )
    reject(
        {
            "journal": rechain(
                altered if e == select else e for e in result.journal.events
            )
        },
        "SELECTION_PURPOSE",
    )
    trial = next(e for e in result.journal.events if e.kind.value == "TRIAL")
    reject(
        {
            "journal": rechain(
                (*result.journal.events[:-1], trial, result.journal.events[-1])
            )
        },
        "RUN_RECEIPT",
    )
    wrong = next(
        c for c in result.protocol.candidates if c != result.selected_candidate
    )
    # Remove held-out evidence so only the frozen selection proof can reject this.
    altered_events = []
    for event in result.journal.events:
        if event == select:
            event = OOSJournalEvent.build(
                **dict(
                    payload(event, {"content_sha256"}), candidate_id=wrong.candidate_id
                )
            )
        altered_events.append(event)
    reject(
        {
            "journal": rechain(altered_events),
            "selected_candidate": wrong,
            "runs": tuple(
                r
                for r in result.runs
                if r.partition_id != result.protocol.partitions[-1].partition_id
            ),
            "metrics": (),
            "sample_size": 0,
            "sample_sufficiency": result.sample_sufficiency.__class__.INCONCLUSIVE,
            "outcome": OOSOutcome.INCONCLUSIVE,
            "reason_codes": ("INSUFFICIENT_OOS_TRADE_SAMPLE",),
        },
        "CONTAMINATION_REASON",
    )


@pytest.mark.parametrize("synthetic_ready", [False, True])
def test_persisted_postgresql_spot_backtest_entry_and_fail_closed_cases(
    persisted_service,
    synthetic_ready,
    database_url,
    monkeypatch,
):
    research, market_calls, _, now = persisted_service
    if synthetic_ready:
        # Explicit synthetic analysis producer, invoked before persistence.
        # This exercises the supported task interface without changing RSI policy.
        from trading_platform_api.analysis.spot_meta_analysis import SpotMetaFinding
        from trading_platform_api.analysis.versioned_contracts import (
            ConfluenceEvidenceStrengthV2,
        )
        from trading_platform_api.orchestration.spot_analysis_fanout import (
            SpotAnalysisTask,
        )

        def synthetic_task(*, resolved_binding, **kwargs):
            async def run():
                b = resolved_binding
                return SpotMetaFinding(
                    uuid4(),
                    "spot-trend",
                    b.regime.direction,
                    b.evidence[0].relation,
                    ConfluenceEvidenceStrengthV2.MODERATE,
                    FindingReadiness.READY,
                    tuple(sorted((e.evidence_id for e in b.evidence), key=str)),
                    (b.binding.binding_id,),
                    b.binding.regime_method,
                )

            return SpotAnalysisTask(uuid4(), "spot-trend", run)

        monkeypatch.setattr(
            "trading_platform_api.orchestration.spot_request_handoff.build_spot_rsi14_task",
            synthetic_task,
        )

    migration_output = StringIO()
    command.upgrade(
        Config("apps/api/alembic.ini", output_buffer=migration_output),
        "head",
        sql=True,
    )
    schema = f"spot_backtest_test_{uuid4().hex}"

    async def check():
        url = make_url(database_url)
        assert url.drivername == "postgresql+asyncpg"
        assert url.host in ("127.0.0.1", "localhost")
        assert url.database == "lineage_test"
        admin = create_async_engine(database_url)
        engine = create_async_engine(
            database_url,
            connect_args={"server_settings": {"search_path": schema}},
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        created = False
        try:
            async with admin.begin() as connection:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
            async with engine.connect() as connection:
                raw = await connection.get_raw_connection()
                await raw.driver_connection.execute(migration_output.getvalue())

            repository = SqlAlchemySpotResearchStore(sessions)
            research.repository = repository
            app = create_app(
                settings=AppSettings(
                    environment=DeploymentEnvironment.TEST,
                    mode=OperatingMode.RESEARCH,
                ),
                research_service=research,
            )
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://127.0.0.1"
            ) as client:
                response = await client.post(
                    f"/api/research/spot/{INSTRUMENT}/refresh",
                    json=refresh_body(timeframe="1m", limit=50, now=now),
                )
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["analysis_fanout"]["status"] == "AVAILABLE"

            async with sessions.begin() as session:
                reservation = (
                    (
                        await session.execute(
                            select(spot_producer_request_reservations).where(
                                spot_producer_request_reservations.c.snapshot_id
                                == payload["snapshot_id"],
                                spot_producer_request_reservations.c.status
                                == "COMPLETED",
                            )
                        )
                    )
                    .mappings()
                    .one()
                )
                context_key = LineageKey(
                    reservation["context_contract_id"],
                    reservation["context_record_id"],
                    reservation["context_version"],
                )
                lineage = SqlAlchemyLineageStore(session)
                handoff = await lineage.get_spot_agent_handoff(context_key)
                assert handoff is not None
                agent_result, agent_evaluation, correlation_id, trace_id = handoff
                context = await lineage.get(context_key)
                assert context is not None
                decision_time = max(
                    context.as_of, agent_evaluation.ended_at, agent_result.generated_at
                ) + timedelta(seconds=2)
                inputs = await _compose_persisted_spot_debate(
                    session=session,
                    store=lineage,
                    context_key=context_key,
                    context=context,
                    result=agent_result,
                    evaluation=agent_evaluation,
                    correlation_id=correlation_id,
                    trace_id=trace_id,
                    now=decision_time,
                )
                assert type(inputs.manifest) is AnalysisSnapshotV4
                assert len(inputs.resolved_bindings) == 1
                binding = inputs.resolved_bindings[0]
                assert type(binding) is ResolvedSpotOHLCVBindingV4
                assert binding.observations
                assert binding.sources
                assert tuple(
                    item.observation.record_id
                    for item in inputs.manifest.bindings[0].observations
                ) == tuple(str(item.market_data_id) for item in binding.observations)
                archive_sources = tuple(
                    (item.record_id, item.content_sha256)
                    for item in binding.binding.source_records
                )
                expected_archive_sources = tuple(
                    (
                        str(source_id),
                        canonical_sha256(
                            next(
                                source
                                for source in binding.sources
                                if source.source_record_id == source_id
                            )
                        ),
                    )
                    for source_id in dict.fromkeys(
                        item.source_record_id for item in binding.observations
                    )
                )
                assert archive_sources == expected_archive_sources, (
                    archive_sources,
                    expected_archive_sources,
                )

                raw_resolved, _ = _setup()
                identity = replace(
                    raw_resolved.strategy, created_at=now - timedelta(days=2)
                )
                parent = replace(
                    raw_resolved.version,
                    created_at=now - timedelta(days=1),
                    environments=(DeploymentEnvironment.TEST,),
                    supported_timeframes=("1m",),
                    operating_modes=(OperatingMode.BACKTEST,),
                )
                parent = replace(
                    parent, content_sha256=strategy_version_content_sha256(parent)
                )
                base_version = build_personal_spot_strategy_v2(
                    parent,
                    strategy_version_id=uuid4(),
                    created_at=now - timedelta(hours=1),
                )
                context_features = build_spot_condition_context(
                    strategy=replace(
                        raw_resolved,
                        strategy=identity,
                        version=base_version,
                        availability=StrategyAvailability.ACTIVE,
                        c021_lifecycle=StrategyLifecycle.VALIDATED,
                        artifact_lifecycle=ArtifactVersionLifecycle.VALIDATED,
                    ),
                    debate=inputs.debate,
                    fanout=inputs.fanout,
                    now=decision_time,
                    mode=OperatingMode.BACKTEST,
                )
                persisted_finding = inputs.fanout.findings[0]
                assert persisted_finding.direction is AnalyticalDirection.BULLISH
                assert persisted_finding.readiness is (
                    FindingReadiness.READY
                    if synthetic_ready
                    else FindingReadiness.PARTIAL
                )
                assert (
                    any(
                        feature.path
                        == f"spot.finding.{persisted_finding.domain}.direction"
                        for feature in context_features.features
                    )
                    is synthetic_ready
                )
                condition = StrategyCondition(
                    uuid4(),
                    f"spot.finding.{persisted_finding.domain}.direction",
                    ConditionOperator.EQUALS,
                    (persisted_finding.direction.value,),
                    "1",
                )
                version = replace(
                    base_version,
                    semantic_version="2.0.1",
                    preferred_regimes=("trend",),
                    acceptable_regimes=(),
                    incompatible_regimes=(),
                    conditions=(condition,),
                    condition_groups=(
                        replace(
                            base_version.condition_groups[0],
                            condition_ids=(condition.condition_id,),
                        ),
                    ),
                    content_sha256="0" * 64,
                )
                version = replace(
                    version, content_sha256=strategy_version_content_sha256(version)
                )
                version_pin = SpotReplayStrategyPin(
                    version.strategy_id,
                    version.strategy_version_id,
                    version.semantic_version,
                    version.content_sha256,
                )
                resolver = _ReferenceResolver()
                registry = StrategyRegistry(
                    SqlAlchemyStrategyRegistryStore(session),
                    reference_resolver=resolver,
                    clock=lambda: decision_time - timedelta(seconds=1),
                )
                await _register_backtest_strategy(
                    registry,
                    resolver,
                    identity,
                    parent,
                    version,
                    effective_at=decision_time - timedelta(minutes=2),
                )

                scope = SpotReplayScope(
                    binding.binding.venue_id,
                    binding.binding.instrument_id,
                    context.asset,
                    "USDT",
                    "BTC",
                    binding.binding.timeframe,
                    DeploymentEnvironment.TEST,
                    decision_time,
                    now + timedelta(minutes=20),
                )
                input_dataset, input_manifest, input_records, _ = _market_records(
                    binding.observations,
                    binding.sources,
                    cutoff=context.as_of,
                    dataset_id=f"decision-{uuid4()}",
                    venue=scope.venue_id,
                    instrument_id=scope.instrument_id,
                )
                await _append_dataset(lineage, input_records)
                decision = SpotReplayDecisionRequest(
                    decision_time,
                    context.as_of,
                    canonical_sha256(input_dataset),
                    canonical_sha256(input_manifest),
                    binding.binding.window_start,
                    binding.binding.window_end,
                )
                replay_inputs = SpotReplayInputRequest(
                    scope,
                    version_pin,
                    (decision,),
                    SpotReplayLimits(4, 4096, 2000),
                )
                pin = SpotBacktestArchivePin(
                    context.context_id,
                    canonical_sha256(context),
                    canonical_sha256(inputs.manifest),
                    agent_result.result_id,
                    canonical_sha256(agent_result),
                    agent_evaluation.evaluation_id,
                    canonical_sha256(agent_evaluation),
                    sha256(
                        canonical_json_dumps(inputs.fanout.outcomes).encode("utf-8")
                    ).hexdigest(),
                )

                execution_cutoff = context.as_of + timedelta(minutes=20)
                execution_dataset, execution_manifest, execution_records, _ = (
                    _market_records(
                        binding.observations,
                        binding.sources,
                        cutoff=execution_cutoff,
                        dataset_id=f"execution-{uuid4()}",
                        venue=scope.venue_id,
                        instrument_id=scope.instrument_id,
                        extra_bars=20,
                        extra_start=context.as_of - STEP,
                    )
                )
                await _append_dataset(lineage, execution_records)
                policy = SpotExecutionPolicy(
                    scope.venue_id,
                    scope.instrument_id,
                    scope.asset,
                    scope.price_unit,
                    scope.volume_unit,
                    scope.timeframe,
                    scope.environment,
                    context.as_of,
                    execution_cutoff,
                    D("1"),
                    D("0.1"),
                    D("1000"),
                    D("0"),
                    0,
                    0,
                )
                adapter = _cost_adapter(
                    version=version,
                    scope=scope,
                    as_of=context.as_of,
                    valid_until=execution_cutoff + timedelta(days=1),
                )
                parameters = SpotBacktestParameters(
                    version.strategy_version_id,
                    version.content_sha256,
                    D("1"),
                    timedelta(minutes=3),
                    STEP,
                    timedelta(minutes=3),
                    1,
                    "EXIT_FILLED_QUANTITY_AFTER_LAST_FILL_V1",
                )
                request = SpotBacktestRunRequest(
                    replay_inputs,
                    (pin,),
                    canonical_sha256(execution_dataset),
                    canonical_sha256(execution_manifest),
                    policy,
                    parameters,
                    adapter.assumptions,
                    adapter,
                    execution_cutoff,
                    execution_cutoff + timedelta(seconds=1),
                    execution_cutoff + timedelta(days=1),
                )
                before_model_calls = research.spot_agent_runtime.provider.calls
                bundle = await run_spot_backtest(
                    request=request,
                    session=session,
                    strategy_registry=registry,
                    lineage_store=lineage,
                )
                assert bundle.outcome is SpotBacktestOutcome.OBSERVED, (
                    bundle.reason_codes
                )
                assert bundle.trace is not None
                assert bundle.trace.entry_trace is not None
                if synthetic_ready:
                    assert bundle.trace.entry_trace.fills, [
                        (
                            d.eligibility_evaluation.reason_codes,
                            d.condition_evaluation.truth,
                        )
                        for d in bundle.trace.decisions
                    ]
                    assert bundle.trace.exit_trace is not None
                    assert bundle.trace.exit_trace.fills
                    assert bundle.trace.trades
                    fills = (
                        *bundle.trace.entry_trace.fills,
                        *bundle.trace.exit_trace.fills,
                    )
                    assert all(fill.costs.fee > 0 for fill in fills)
                    assert all(fill.costs.spread > 0 for fill in fills)
                    assert all(fill.observed_at > decision_time for fill in fills)
                    assert bundle.trace.entry_trace.final_inventory > 0
                    assert bundle.trace.exit_trace.final_inventory == 0
                    for trade in bundle.trace.trades:
                        assert trade.entry_cash_outflow > 0
                        assert trade.exit_cash_inflow > 0
                        assert trade.realized_cash_delta == (
                            trade.exit_cash_inflow - trade.entry_cash_outflow
                        )
                else:
                    assert bundle.trace.decisions[0].kind.value == "NO_ORDER"
                    assert bundle.trace.decisions[0].setup.reason_codes == (
                        "ELIGIBILITY_INSUFFICIENT_DATA",
                    )
                    assert (
                        bundle.trace.decisions[0].eligibility_evaluation.state.value
                        == "INSUFFICIENT_DATA"
                    )
                    assert bundle.trace.decisions[
                        0
                    ].condition_evaluation.truth.value == ("UNKNOWN")
                    assert not bundle.trace.entry_trace.fills
                    assert bundle.trace.exit_trace is None
                    assert not bundle.trace.trades
                assert bundle.result is not None
                assert resolve_spot_backtest_result(bundle) == bundle.result
                assert research.spot_agent_runtime.provider.calls == before_model_calls

                metrics_policy = MetricsPolicy(
                    METRICS_METHOD,
                    "1",
                    "USDT",
                    "BAR_CLOSE",
                    60,
                    D(525600),
                    D(0),
                    D(0),
                    30,
                    2,
                    request.created_at,
                )
                report = calculate_spot_performance_metrics(bundle, metrics_policy)
                assert report.result_id == bundle.result.result_id
                assert report.result_sha256 == bundle.result.content_sha256
                assert report.get("total_trades").metric.value == int(synthetic_ready)
                assert (
                    report.get("cumulative_return").reason == "PRICE_PATH_NOT_PROVIDED"
                )
                assert report == calculate_spot_performance_metrics(
                    bundle, metrics_policy
                )
                marked = calculate_spot_performance_metrics(
                    bundle,
                    metrics_policy,
                    price_path=bundle.execution_dataset,
                )
                assert marked.equity
                assert marked.get("cumulative_return").state is MetricState.AVAILABLE
                assert marked.equity[-1].inventory == 0
                assert (
                    marked.get("benchmark_relative_return").reason
                    == "BENCHMARK_NOT_PROVIDED"
                )
                if synthetic_ready:
                    trade = bundle.trace.trades[0]
                    assert (
                        report.get("net_realized_profit").metric.value
                        == trade.realized_cash_delta
                    )
                    with localcontext(Context(prec=50)):
                        assert (
                            report.trades[0].cash_return
                            == trade.realized_cash_delta / trade.entry_cash_outflow
                        )
                    assert marked.equity[-1].cash == bundle.trace.exit_trace.final_cash
                    assert (
                        marked.trades[0].excursion_reason
                        == "PARTIAL_EXIT_BAR_AMBIGUITY"
                    )
                    risk = InitialRisk(
                        trade.trade_id,
                        D(10),
                        "USDT",
                        "synthetic-initial-risk-v1",
                        ValidationArtifactReferenceV2("C-034", uuid4(), "1", "b" * 64),
                    )
                    risk_report = calculate_spot_performance_metrics(
                        bundle, metrics_policy, initial_risks=(risk,)
                    )
                    assert (
                        risk_report.get("average_r").metric.value
                        == trade.realized_cash_delta / 10
                    )
                    with pytest.raises(MetricsInputError, match="RISK_ID_OR_UNIT"):
                        calculate_spot_performance_metrics(
                            bundle, metrics_policy, initial_risks=(risk, risk)
                        )
                else:
                    assert report.get("win_rate").state is MetricState.UNDEFINED
                    assert marked.get("cumulative_return").metric.value == 0
                with pytest.raises(MetricsInputError):
                    calculate_spot_performance_metrics(
                        replace(bundle, artifacts=()), metrics_policy
                    )
                with pytest.raises(MetricsInputError, match="QUOTE_UNIT"):
                    calculate_spot_performance_metrics(
                        bundle, replace(metrics_policy, quote_unit="USD")
                    )
                with pytest.raises(MetricsInputError, match="PRICE_PATH_PIN"):
                    calculate_spot_performance_metrics(
                        bundle,
                        metrics_policy,
                        price_path=replace(
                            bundle.execution_dataset, dataset_sha256="f" * 64
                        ),
                    )

                # Explicit synthetic recorder authority: verifies the recorded
                # experiment, not the absence of off-system owner research.
                recorded_at = request.created_at + timedelta(hours=2)
                oos_metrics_policy = replace(metrics_policy, min_trade_sample=1)
                development = await _development_oos(
                    request,
                    oos_metrics_policy,
                    binding,
                    session,
                    registry,
                    lineage,
                    research,
                    app,
                )
                assert development.outcome is (
                    OOSOutcome.OBSERVED if synthetic_ready else OOSOutcome.INCONCLUSIVE
                ), development.reason_codes
                recorder = OOSResearchJournal(
                    journal_id=uuid4(),
                    authority=ValidationArtifactReferenceV2(
                        "SYNTHETIC_RESEARCH_RECORDER", uuid4(), "1", "e" * 64
                    ),
                    clock=lambda: recorded_at,
                    declared_complete=True,
                )
                partitions = (
                    DataPartition(
                        uuid4(),
                        PartitionPurpose.TRAIN,
                        policy.period_start - 20 * STEP,
                        policy.period_start - 10 * STEP,
                        policy.period_start - 10 * STEP,
                        True,
                    ),
                    DataPartition(
                        uuid4(),
                        PartitionPurpose.VALIDATION,
                        policy.period_start - 10 * STEP,
                        policy.period_start,
                        policy.period_start,
                        False,
                    ),
                    DataPartition(
                        uuid4(),
                        PartitionPurpose.TEST,
                        policy.period_start,
                        policy.period_end,
                        policy.period_end,
                        False,
                    ),
                )
                oos_window = OOSWindow(
                    policy.venue,
                    policy.instrument_id,
                    policy.timeframe,
                    policy.period_start,
                    policy.period_end,
                )
                freeze_kwargs = dict(
                    journal=recorder,
                    window=oos_window,
                    partitions=partitions,
                    candidates=(candidate_from_request(request),),
                    selection_mode=OOSSelectionMode.FIXED,
                    metrics_policy=oos_metrics_policy,
                    warmup_bars=64,
                    embargo_seconds=0,
                    mark_equity=True,
                    environment=policy.environment,
                )
                protocol = freeze_spot_oos_protocol(**freeze_kwargs)
                oos_kwargs = dict(
                    journal=recorder,
                    protocol=protocol,
                    request=request,
                    metrics_policy=oos_metrics_policy,
                    session=session,
                    strategy_registry=registry,
                    lineage_store=lineage,
                    as_of=request.result_as_of,
                    expires_at=request.expires_at,
                )
                # Return a complete, canonically valid replay for different
                # requested pins. Internal replay consistency alone is insufficient.
                alternate_requests = _oos_substitution_requests(
                    request, execution_dataset
                )

                async def substituted_replay(**kwargs):
                    return bundle

                for changed_pin, alternate in alternate_requests.items():
                    isolated_recorder = OOSResearchJournal(
                        journal_id=uuid4(),
                        authority=recorder.snapshot.authority,
                        clock=lambda: recorded_at,
                        declared_complete=True,
                    )
                    isolated_protocol = freeze_spot_oos_protocol(
                        **dict(freeze_kwargs, journal=isolated_recorder)
                    )
                    with monkeypatch.context() as patch:
                        patch.setattr(
                            "trading_platform_api.validation.spot_oos.run_spot_backtest",
                            substituted_replay,
                        )
                        rejected = await run_spot_oos(
                            **dict(
                                oos_kwargs,
                                journal=isolated_recorder,
                                protocol=isolated_protocol,
                                request=alternate,
                                as_of=alternate.result_as_of,
                            )
                        )
                    assert rejected.outcome is OOSOutcome.FAILED, changed_pin
                    assert rejected.result.integrity.value == "FAILED"
                    assert rejected.result.contamination.value == "PASSED"
                    assert (
                        "OOS_REPLAY_REQUEST_CLOSURE_MISMATCH" in rejected.reason_codes
                    )
                    assert not rejected.replays and not rejected.reports
                    assert (
                        resolve_spot_oos_result(rejected, journal=isolated_recorder)
                        == rejected.result
                    )

                trace = bundle.trace
                terminal_name = "exit_trace" if trace.exit_trace else "entry_trace"
                terminal = getattr(trace, terminal_name)
                bad_traces = {
                    "CROSS_BOUNDARY_OPEN_INVENTORY": replace(
                        trace,
                        **{terminal_name: replace(terminal, final_inventory=D("1"))},
                    ),
                    "OOS_DECISION_OUTSIDE_PARTITION": replace(
                        trace,
                        decisions=(
                            replace(
                                trace.decisions[0], decision_time=policy.period_end
                            ),
                            *trace.decisions[1:],
                        ),
                    ),
                }
                if trace.entry_trace.fills:
                    for at in (
                        policy.period_start,
                        policy.period_end + timedelta(microseconds=1),
                    ):
                        bad_traces[f"OOS_FILL_OUTSIDE_PARTITION:{at}"] = replace(
                            trace,
                            entry_trace=replace(
                                trace.entry_trace,
                                fills=(
                                    replace(trace.entry_trace.fills[0], observed_at=at),
                                    *trace.entry_trace.fills[1:],
                                ),
                            ),
                        )
                for reason, bad_trace in bad_traces.items():
                    isolated_recorder = OOSResearchJournal(
                        journal_id=uuid4(),
                        authority=recorder.snapshot.authority,
                        clock=lambda: recorded_at,
                        declared_complete=True,
                    )
                    isolated_protocol = freeze_spot_oos_protocol(
                        **dict(freeze_kwargs, journal=isolated_recorder)
                    )

                    async def invalid_boundary(**kwargs):
                        return replace(bundle, trace=bad_trace)

                    with monkeypatch.context() as patch:
                        patch.setattr(
                            "trading_platform_api.validation.spot_oos.run_spot_backtest",
                            invalid_boundary,
                        )
                        rejected = await run_spot_oos(
                            **dict(
                                oos_kwargs,
                                journal=isolated_recorder,
                                protocol=isolated_protocol,
                            )
                        )
                    assert rejected.result.integrity.value == "FAILED"
                    assert rejected.result.contamination.value == "PASSED"
                    assert reason.split(":")[0] in rejected.reason_codes
                oos_bundle = await run_spot_oos(**oos_kwargs)
                assert oos_bundle.outcome is (
                    OOSOutcome.OBSERVED if synthetic_ready else OOSOutcome.INCONCLUSIVE
                ), oos_bundle.reason_codes
                oos_result = resolve_spot_oos_result(oos_bundle, journal=recorder)
                _assert_oos_contract_rejections(oos_result)
                assert oos_result.as_of == request.result_as_of == bundle.result.as_of
                result_values = {
                    name: value
                    for name, value in oos_result.identity_payload().items()
                    if name
                    not in {"method", "contract_id", "schema_version", "operating_mode"}
                }
                with pytest.raises(ValueError, match="OOS_AS_OF_REPLAY_MISMATCH"):
                    type(oos_result).build(
                        **dict(result_values, as_of=oos_result.as_of - STEP)
                    )
                with pytest.raises(ValueError, match="OOS_AS_OF_REQUEST_MISMATCH"):
                    await run_spot_oos(
                        **dict(oos_kwargs, as_of=request.result_as_of - STEP)
                    )
                with pytest.raises(ValueError, match="OOS_REQUEST_RECEIPT_MISMATCH"):
                    resolve_spot_oos_result(
                        replace(oos_bundle, request=alternate_requests["archive_pin"]),
                        journal=recorder,
                    )
                assert oos_result.sample_size == int(synthetic_ready)
                assert oos_result.contamination.value == "PASSED"
                assert (
                    oos_result.runs[0].backtest.dataset.dataset_id
                    == execution_dataset.dataset_id
                )
                assert (
                    oos_result.runs[0].backtest.dataset.version
                    == execution_dataset.version
                )
                assert (
                    oos_result.runs[0].backtest.dataset_sha256
                    == request.execution_dataset_sha256
                )
                assert (
                    oos_result.runs[0].backtest.manifest_sha256
                    == request.execution_manifest_sha256
                )
                if not synthetic_ready:
                    assert (
                        next(
                            m for m in oos_result.metrics if m.name == "win_rate"
                        ).state
                        == "UNDEFINED"
                    )
                    assert "INSUFFICIENT_OOS_TRADE_SAMPLE" in oos_result.reason_codes
                assert await run_spot_oos(**oos_kwargs) == oos_bundle
                altered_report = replace(oos_bundle.reports[0], result_sha256="f" * 64)
                with pytest.raises(ValueError, match="METRICS_CLOSURE"):
                    resolve_spot_oos_result(
                        replace(oos_bundle, reports=(altered_report,)), journal=recorder
                    )
                # A new plan ID or later revision cannot make inspected dates unseen.
                reused_protocol = freeze_spot_oos_protocol(
                    **dict(
                        freeze_kwargs,
                        partitions=tuple(
                            replace(part, partition_id=uuid4()) for part in partitions
                        ),
                    )
                )
                reused = await run_spot_oos(
                    **dict(oos_kwargs, protocol=reused_protocol)
                )
                assert reused.outcome is OOSOutcome.FAILED
                assert "HOLDOUT_PREVIOUSLY_ACCESSED_OR_REUSED" in reused.reason_codes
                assert not reused.replays
                assert (
                    resolve_spot_oos_result(oos_bundle, journal=recorder) == oos_result
                )

                walk_journal = OOSResearchJournal(
                    journal_id=uuid4(),
                    authority=recorder.snapshot.authority,
                    clock=lambda: recorded_at,
                    declared_complete=True,
                )
                walk_scope = OOSWindow(
                    policy.venue,
                    policy.instrument_id,
                    policy.timeframe,
                    policy.period_start,
                    policy.period_end,
                )
                walk_spec = WalkForwardPlanSpecV2(
                    scope=walk_scope,
                    mode=WalkForwardMode.ROLLING,
                    training_bars=2,
                    validation_bars=2,
                    heldout_bars=8,
                    step_bars=8,
                    embargo_bars=0,
                    warmup_bars=64,
                    minimum_folds=2,
                    minimum_trades=1,
                    minimum_returns=oos_metrics_policy.min_return_sample,
                    maximum_folds=2,
                    maximum_candidates=1,
                    maximum_events=8,
                    candidates=(candidate_from_request(request),),
                    selection_mode=OOSSelectionMode.FIXED,
                    metrics_policy=oos_metrics_policy,
                    environment=policy.environment,
                    journal_id=walk_journal.snapshot.journal_id,
                    authority=walk_journal.snapshot.authority,
                    frozen_at=recorded_at,
                )
                walk_folds = generate_walk_forward_folds(walk_spec)
                walk_requests = []
                original_decision = replay_inputs.decisions[0]
                for fold in walk_folds:
                    walk_policy = replace(
                        policy,
                        period_start=fold.heldout.start,
                        period_end=fold.heldout.end,
                    )
                    walk_scope_input = replace(
                        replay_inputs.scope,
                        decision_period_start=fold.heldout.start,
                        decision_period_end=fold.heldout.end,
                    )
                    walk_decision = replace(
                        original_decision,
                        decision_time=fold.heldout.start + timedelta(seconds=1),
                    )
                    walk_input = replace(
                        replay_inputs,
                        scope=walk_scope_input,
                        decisions=(walk_decision,),
                    )
                    walk_request = replace(
                        request,
                        replay_inputs=walk_input,
                        execution_policy=walk_policy,
                        result_as_of=fold.heldout.end,
                    )
                    walk_requests.append(
                        SpotWalkForwardFoldRequests(
                            (
                                SpotWalkForwardCandidateRequests(
                                    None, None, walk_request
                                ),
                            )
                        )
                    )
                walk_bundle = await run_spot_walk_forward(
                    journal=walk_journal,
                    spec=walk_spec,
                    requests=tuple(walk_requests),
                    session=session,
                    strategy_registry=registry,
                    lineage_store=lineage,
                )
                walk_result = resolve_spot_walk_forward_result(
                    walk_bundle, journal=walk_journal
                )
                assert len(walk_result.observations) == 2
                assert all(
                    item.oos_result is not None
                    for item in walk_result.observations
                )
                if synthetic_ready:
                    assert all(
                        item.oos_result.sample_size > 0
                        for item in walk_result.observations
                    )
                else:
                    assert all(
                        item.oos_result.sample_size == 0
                        for item in walk_result.observations
                    )
                    assert all(
                        "INSUFFICIENT_OOS_TRADE_SAMPLE"
                        in item.oos_result.reason_codes
                        for item in walk_result.observations
                    )

                no_setup_condition = replace(
                    condition, condition_id=uuid4(), expected_values=("never",)
                )
                no_order_version = replace(
                    version,
                    strategy_version_id=uuid4(),
                    semantic_version="2.0.2",
                    parent_version_id=version.strategy_version_id,
                    conditions=(no_setup_condition,),
                    condition_groups=(
                        replace(
                            version.condition_groups[0],
                            condition_ids=(no_setup_condition.condition_id,),
                        ),
                    ),
                    created_at=now - timedelta(minutes=30),
                    content_sha256="0" * 64,
                )
                no_order_version = replace(
                    no_order_version,
                    content_sha256=strategy_version_content_sha256(no_order_version),
                )
                await _register_backtest_strategy(
                    registry,
                    resolver,
                    identity,
                    None,
                    no_order_version,
                    effective_at=decision_time - timedelta(minutes=1),
                    register_identity=False,
                )
                no_order_pin = SpotReplayStrategyPin(
                    no_order_version.strategy_id,
                    no_order_version.strategy_version_id,
                    no_order_version.semantic_version,
                    no_order_version.content_sha256,
                )
                no_order_inputs = replace(replay_inputs, strategy=no_order_pin)
                no_order_adapter = _cost_adapter(
                    version=no_order_version,
                    scope=scope,
                    as_of=context.as_of,
                    valid_until=execution_cutoff + timedelta(days=1),
                )
                no_order_request = replace(
                    request,
                    replay_inputs=no_order_inputs,
                    parameters=replace(
                        parameters,
                        strategy_version_id=no_order_version.strategy_version_id,
                        strategy_sha256=no_order_version.content_sha256,
                    ),
                    cost_assumptions=no_order_adapter.assumptions,
                    cost_adapter=no_order_adapter,
                )
                no_order = await run_spot_backtest(
                    request=no_order_request,
                    session=session,
                    strategy_registry=registry,
                    lineage_store=lineage,
                )
                assert no_order.outcome is SpotBacktestOutcome.OBSERVED, (
                    no_order.reason_codes
                )
                assert no_order.trace is not None
                assert no_order.trace.entry_trace is not None
                assert not no_order.trace.entry_trace.fills
                assert no_order.trace.exit_trace is None
                assert not no_order.trace.trades
                assert resolve_spot_backtest_result(no_order) == no_order.result

                mismatch = replace(
                    request,
                    archive_pins=(replace(pin, context_sha256="f" * 64),),
                )
                rejected_archive = await run_spot_backtest(
                    request=mismatch,
                    session=session,
                    strategy_registry=registry,
                    lineage_store=lineage,
                )
                assert rejected_archive.outcome is SpotBacktestOutcome.INCONCLUSIVE
                assert rejected_archive.reason_codes == (
                    "ARCHIVED_ANALYSIS_PIN_OR_TIME_MISMATCH",
                )

                with pytest.raises(ValueError):
                    resolve_spot_backtest_result(
                        replace(bundle, artifacts=bundle.artifacts[:-1])
                    )
                with pytest.raises(ValueError):
                    resolve_spot_backtest_result(
                        replace(
                            bundle,
                            artifacts=tuple(
                                replace(item, document=f"{item.document} ")
                                if item.reference == bundle.result.trace
                                else item
                                for item in bundle.artifacts
                            ),
                        )
                    )

                original_revision = bundle.input_journal.decisions[0].usable_revisions[
                    0
                ]
                original_observation = original_revision.observation
                original_source = next(
                    item
                    for item in bundle.input_journal.decisions[0].dataset.sources
                    if item.source_record_id == original_observation.source_record_id
                )
                corrected_at = decision_time + STEP
                corrected_source = replace(
                    original_source,
                    source_record_id=uuid4(),
                    provider_event_time=corrected_at,
                    retrieval_time=corrected_at,
                    availability_time=corrected_at,
                    content_sha256=canonical_sha256(
                        (original_source.source_record_id, corrected_at)
                    ),
                )
                corrected_observation = replace(
                    original_observation,
                    market_data_id=uuid4(),
                    provider_time=corrected_at,
                    ingestion_time=corrected_at,
                    availability_time=corrected_at,
                    source_record_id=corrected_source.source_record_id,
                    metrics=tuple(
                        replace(metric, value=metric.value + D("1"))
                        if metric.metric_name == "close"
                        else metric
                        for metric in original_observation.metrics
                    ),
                )
                correction = ObservationRevision(
                    uuid4(),
                    original_revision.provider_id,
                    original_revision.observation_key,
                    original_revision.revision_id,
                    corrected_observation,
                    corrected_at,
                    corrected_at,
                    corrected_at,
                    original_revision.finalized_interval_end,
                )
                await lineage.append(corrected_source)
                await lineage.append(corrected_observation)
                await lineage.append(correction)
                replay_after_correction = await run_spot_backtest(
                    request=request,
                    session=session,
                    strategy_registry=registry,
                    lineage_store=lineage,
                )
                assert replay_after_correction == bundle
                assert await run_spot_oos(**oos_kwargs) == oos_bundle
                assert (
                    resolve_spot_oos_result(oos_bundle, journal=recorder) == oos_result
                )
                assert (
                    calculate_spot_performance_metrics(
                        replay_after_correction, metrics_policy
                    )
                    == report
                )
                assert (
                    calculate_spot_performance_metrics(
                        replay_after_correction,
                        metrics_policy,
                        price_path=replay_after_correction.execution_dataset,
                    )
                    == marked
                )

            async with sessions() as session:
                assert (
                    await session.scalar(
                        select(spot_producer_request_reservations.c.status)
                        .where(
                            spot_producer_request_reservations.c.snapshot_id
                            == payload["snapshot_id"]
                        )
                        .limit(1)
                    )
                    == "COMPLETED"
                )
        finally:
            await engine.dispose()
            try:
                if created:
                    async with admin.begin() as connection:
                        await connection.execute(
                            text(f'DROP SCHEMA "{schema}" CASCADE')
                        )
            finally:
                await admin.dispose()

    asyncio.run(check())
    assert market_calls == [1, 1, 1]  # Initial plus two fresh research archives.
