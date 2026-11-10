"""Synthetic per-decision replay inputs; no provider or performance claims."""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from test_history_selection import T
from test_spot_execution import fixture as scenario_fixture
from test_strategy_condition_evaluator import _setup
from trading_platform_api.config import DeploymentEnvironment, OperatingMode
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.lineage.codec import key_for
from trading_platform_api.market_data.history_selection import reconstruct_history
from trading_platform_api.strategy.contracts import StrategyLifecycle
from trading_platform_api.strategy.registry import (
    ArtifactVersionLifecycle,
    ResolvedStrategyVersion,
    StrategyAvailability,
    StrategyRegistryError,
    build_personal_spot_strategy_v2,
    strategy_version_content_sha256,
)
from trading_platform_api.validation import spot_replay_inputs
from trading_platform_api.validation.spot_replay_inputs import (
    SpotReplayDecisionRequest,
    SpotReplayInputFailure,
    SpotReplayInputRequest,
    SpotReplayInputUnavailable,
    SpotReplayLimits,
    SpotReplayScope,
    SpotReplayStrategyPin,
    build_spot_replay_input_journal,
)

STEP = timedelta(minutes=1)
EARLY_CUTOFF = T + 3 * STEP
LATER_CUTOFF = T + 6 * STEP


class MemoryResolver:
    def __init__(self, closures):
        self.closures = closures
        self.calls = []

    async def resolve(self, keys, *, maximum_records=2000):
        self.calls.append((keys, maximum_records))
        return self.closures.get(keys[0], {})


class MemoryRegistry:
    def __init__(self, resolved):
        self.resolved = resolved
        self.calls = []

    async def resolve_version(
        self,
        *,
        strategy_id,
        strategy_version_id=None,
        semantic_version=None,
        as_of=None,
    ):
        self.calls.append((strategy_id, strategy_version_id, semantic_version, as_of))
        if strategy_id != self.resolved.strategy.strategy_id:
            raise StrategyRegistryError("strategy unavailable")
        return self.resolved


def _strategy() -> ResolvedStrategyVersion:
    original, _ = _setup()
    parent = replace(
        original.version,
        created_at=T - timedelta(days=2),
        supported_timeframes=("1m",),
        environments=(DeploymentEnvironment.TEST,),
        operating_modes=(OperatingMode.BACKTEST,),
    )
    parent = replace(parent, content_sha256=strategy_version_content_sha256(parent))
    version = build_personal_spot_strategy_v2(
        parent,
        strategy_version_id=uuid4(),
        created_at=T - timedelta(days=1),
    )
    strategy = replace(original.strategy, created_at=T - timedelta(days=2))
    return ResolvedStrategyVersion(
        strategy,
        version,
        StrategyAvailability.ACTIVE,
        StrategyLifecycle.VALIDATED,
        ArtifactVersionLifecycle.VALIDATED,
    )


def _history(*, omit_open: datetime | None = None, nonfinal: bool = False):
    base = scenario_fixture(count=6)["data"]
    universe = base.reconstruction.universe
    revisions = list(base.reconstruction.selected_revisions)
    sources = list(base.sources)
    parent = revisions[1]
    parent_observation = parent.observation
    later_source = replace(
        sources[1],
        source_record_id=uuid4(),
        provider_event_time=T + 5 * STEP,
        retrieval_time=T + 5 * STEP,
        availability_time=T + 5 * STEP,
    )
    corrected_observation = replace(
        parent_observation,
        market_data_id=uuid4(),
        source_record_id=later_source.source_record_id,
        provider_time=T + 5 * STEP,
        ingestion_time=T + 5 * STEP,
        availability_time=T + 5 * STEP,
    )
    correction = replace(
        parent,
        revision_id=uuid4(),
        supersedes_revision_id=parent.revision_id,
        observation=corrected_observation,
        publication_time=T + 5 * STEP,
        ingestion_time=T + 5 * STEP,
        availability_time=T + 5 * STEP,
    )
    revisions.append(correction)
    sources.append(later_source)
    if nonfinal:
        revised = []
        for item in revisions:
            if item.observation.event_time == T + STEP:
                item = replace(
                    item,
                    finalized_interval_end=item.finalized_interval_end
                    - timedelta(seconds=1),
                )
            revised.append(item)
        revisions = revised
    if omit_open is not None:
        revisions = [
            item for item in revisions if item.observation.event_time != omit_open
        ]
    return base, universe, tuple(revisions), tuple(sources)


def _closure(base, universe, revisions, sources, cutoff, dataset_id):
    eligible = tuple(item for item in revisions if item.availability_time <= cutoff)
    source_ids = set(universe.source_record_ids) | {
        item.observation.source_record_id for item in eligible
    }
    selected_sources = tuple(
        sorted(
            (item for item in sources if item.source_record_id in source_ids),
            key=lambda item: str(item.source_record_id),
        )
    )
    dataset = replace(
        base.dataset,
        dataset_id=dataset_id,
        version="1",
        coverage_end=cutoff,
        point_in_time_cutoff=cutoff,
        source_record_ids=tuple(sorted(source_ids, key=str)),
    )
    reconstruction = reconstruct_history(
        cutoff=cutoff,
        universe=universe,
        revisions=eligible,
        sources=selected_sources,
        dataset=dataset,
        expected_universe_sha256=canonical_sha256(universe),
        expected_lineage_sha256=dataset.lineage_sha256,
    )
    records = (
        *selected_sources,
        dataset,
        universe,
        *(item.observation for item in eligible),
        *eligible,
        reconstruction.manifest,
    )
    return dataset, reconstruction.manifest, records


def _case(*, omit_open=None, nonfinal=False, dataset_prefix="decision"):
    base, universe, revisions, sources = _history(
        omit_open=omit_open, nonfinal=nonfinal
    )
    closures = {}
    pins = {}
    for cutoff, dataset_id in (
        (EARLY_CUTOFF, f"{dataset_prefix}-early"),
        (LATER_CUTOFF, f"{dataset_prefix}-later"),
    ):
        dataset, manifest, records = _closure(
            base, universe, revisions, sources, cutoff, dataset_id
        )
        dataset_sha256 = canonical_sha256(dataset)
        manifest_sha256 = canonical_sha256(manifest)
        closures[key_for(manifest)] = {key_for(item): item for item in records}
        pins[cutoff] = (dataset_sha256, manifest_sha256, manifest)
    resolved = _strategy()
    strategy_pin = SpotReplayStrategyPin(
        resolved.version.strategy_id,
        resolved.version.strategy_version_id,
        resolved.version.semantic_version,
        resolved.version.content_sha256,
    )
    scope = SpotReplayScope(
        "fixture",
        "BTC-USDT-SPOT",
        "BTC",
        "USDT",
        "BTC",
        "1m",
        DeploymentEnvironment.TEST,
        EARLY_CUTOFF,
        LATER_CUTOFF + STEP,
    )
    decisions = (
        SpotReplayDecisionRequest(
            EARLY_CUTOFF,
            EARLY_CUTOFF,
            pins[EARLY_CUTOFF][0],
            pins[EARLY_CUTOFF][1],
            T + STEP,
            EARLY_CUTOFF,
        ),
        SpotReplayDecisionRequest(
            LATER_CUTOFF,
            LATER_CUTOFF,
            pins[LATER_CUTOFF][0],
            pins[LATER_CUTOFF][1],
            T + STEP,
            LATER_CUTOFF,
        ),
    )
    request = SpotReplayInputRequest(
        scope, strategy_pin, decisions, SpotReplayLimits(8, 4096, 2000)
    )
    return request, closures, resolved, pins, revisions


def test_point_in_time_journal_is_stable_and_uses_only_available_correction():
    request, closures, resolved, _, revisions = _case()
    resolver = MemoryResolver(closures)
    registry = MemoryRegistry(resolved)
    first = asyncio.run(
        build_spot_replay_input_journal(
            resolver=resolver, strategy_registry=registry, request=request
        )
    )
    second = asyncio.run(
        build_spot_replay_input_journal(
            resolver=MemoryResolver(closures),
            strategy_registry=MemoryRegistry(resolved),
            request=request,
        )
    )
    assert first == second
    assert first.method == "spot-per-decision-replay-input-v1"
    assert len(first.decisions) == 2
    assert (
        first.decisions[0].usable_revisions[0].revision_id == revisions[1].revision_id
    )
    assert (
        first.decisions[1].usable_revisions[0].revision_id == revisions[-1].revision_id
    )
    assert first.decisions[0].content_sha256 != first.decisions[1].content_sha256
    assert [call[3] for call in registry.calls] == [
        decision.decision_time for decision in request.decisions
    ]


def test_oversized_journal_preimage_is_rejected_before_encoding(monkeypatch):
    monkeypatch.setattr(
        spot_replay_inputs,
        "canonical_json_dumps",
        lambda value: pytest.fail("oversized value reached canonical encoding"),
    )
    with pytest.raises(ValueError, match="byte budget"):
        spot_replay_inputs._sha256_bounded({"payload": "x" * 170_000})


@pytest.mark.parametrize(
    "change",
    [
        lambda req: replace(req, decisions=()),
        lambda req: replace(req, decisions=list(req.decisions)),
        lambda req: replace(req, decisions=(req.decisions[1], req.decisions[0])),
        lambda req: replace(req, decisions=(req.decisions[0], req.decisions[0])),
        lambda req: replace(
            req,
            decisions=(
                replace(req.decisions[0], decision_time=datetime(2026, 1, 1)),
                req.decisions[1],
            ),
        ),
        lambda req: replace(
            req,
            decisions=(
                req.decisions[0],
                replace(
                    req.decisions[1],
                    information_cutoff=T + 2 * STEP,
                    lookback_end=T + 2 * STEP,
                ),
            ),
        ),
    ],
)
def test_invalid_schedule_is_rejected_before_any_resolution(change):
    request, closures, resolved, _, _ = _case()
    resolver = MemoryResolver(closures)
    registry = MemoryRegistry(resolved)
    with pytest.raises(SpotReplayInputUnavailable) as error:
        asyncio.run(
            build_spot_replay_input_journal(
                resolver=resolver,
                strategy_registry=registry,
                request=change(request),
            )
        )
    assert error.value.reason in {
        SpotReplayInputFailure.INVALID_SCHEDULE,
        SpotReplayInputFailure.INVALID_REQUEST,
    }
    assert resolver.calls == []
    assert registry.calls == []


def test_later_manifest_cannot_be_substituted_for_earlier_decision():
    request, closures, resolved, pins, _ = _case()
    earlier = replace(request.decisions[0], manifest_sha256=pins[LATER_CUTOFF][1])
    bad_request = replace(request, decisions=(earlier, request.decisions[1]))
    with pytest.raises(SpotReplayInputUnavailable) as error:
        asyncio.run(
            build_spot_replay_input_journal(
                resolver=MemoryResolver(closures),
                strategy_registry=MemoryRegistry(resolved),
                request=bad_request,
            )
        )
    assert error.value.decision_index == 0


@pytest.mark.parametrize(
    ("case_changes", "scope_changes", "expected"),
    [
        ({"nonfinal": True}, {}, SpotReplayInputFailure.BAR_UNAVAILABLE),
        ({"omit_open": T + 2 * STEP}, {}, SpotReplayInputFailure.LOOKBACK_UNAVAILABLE),
        ({}, {"venue_id": "other"}, SpotReplayInputFailure.HISTORICAL_SCOPE_MISMATCH),
        (
            {},
            {"instrument_id": "ETH-USDT-SPOT"},
            SpotReplayInputFailure.HISTORICAL_SCOPE_MISMATCH,
        ),
        ({}, {"price_unit": "BTC"}, SpotReplayInputFailure.BAR_UNAVAILABLE),
    ],
)
def test_invalid_bar_scope_finality_and_coverage_fail_closed(
    case_changes, scope_changes, expected
):
    request, closures, resolved, _, _ = _case(**case_changes)
    request = replace(request, scope=replace(request.scope, **scope_changes))
    with pytest.raises(SpotReplayInputUnavailable) as error:
        asyncio.run(
            build_spot_replay_input_journal(
                resolver=MemoryResolver(closures),
                strategy_registry=MemoryRegistry(resolved),
                request=request,
            )
        )
    assert error.value.reason is expected


def test_wrong_timeframe_is_rejected_without_using_shorter_bars():
    request, closures, resolved, _, _ = _case()
    request = replace(
        request,
        scope=replace(request.scope, timeframe="3m"),
        decisions=tuple(replace(item, lookback_start=T) for item in request.decisions),
    )
    with pytest.raises(SpotReplayInputUnavailable) as error:
        asyncio.run(
            build_spot_replay_input_journal(
                resolver=MemoryResolver(closures),
                strategy_registry=MemoryRegistry(resolved),
                request=request,
            )
        )
    assert error.value.reason is SpotReplayInputFailure.BAR_UNAVAILABLE


def test_exact_dataset_hash_and_total_resolution_budget_are_required():
    request, closures, resolved, _, _ = _case()
    tampered = replace(request.decisions[0], dataset_sha256="f" * 64)
    with pytest.raises(SpotReplayInputUnavailable) as error:
        asyncio.run(
            build_spot_replay_input_journal(
                resolver=MemoryResolver(closures),
                strategy_registry=MemoryRegistry(resolved),
                request=replace(request, decisions=(tampered, request.decisions[1])),
            )
        )
    assert error.value.reason is SpotReplayInputFailure.DATASET_UNAVAILABLE
    limited = replace(request, limits=SpotReplayLimits(8, 1, 2000))
    with pytest.raises(SpotReplayInputUnavailable) as budget_error:
        asyncio.run(
            build_spot_replay_input_journal(
                resolver=MemoryResolver(closures),
                strategy_registry=MemoryRegistry(resolved),
                request=limited,
            )
        )
    assert (
        budget_error.value.reason is SpotReplayInputFailure.RESOLUTION_BUDGET_EXHAUSTED
    )


def test_tampered_source_and_strategy_hashes_are_rejected():
    request, closures, resolved, _, _ = _case()
    early_key = next(
        key
        for key in closures
        if key.contract_id == "C-103"
        and key.record_id == request.decisions[0].manifest_sha256
    )
    corrupted = {key: dict(records) for key, records in closures.items()}
    early_records = corrupted[early_key]
    source = next(
        value
        for value in early_records.values()
        if getattr(value, "contract_id", None) == "C-091"
    )
    early_records[key_for(source)] = replace(source, licensing_reference="changed")
    with pytest.raises(SpotReplayInputUnavailable) as source_error:
        asyncio.run(
            build_spot_replay_input_journal(
                resolver=MemoryResolver(corrupted),
                strategy_registry=MemoryRegistry(resolved),
                request=request,
            )
        )
    assert source_error.value.reason is SpotReplayInputFailure.DATASET_UNAVAILABLE
    bad_strategy = replace(request.strategy, content_sha256="f" * 64)
    with pytest.raises(SpotReplayInputUnavailable) as strategy_error:
        asyncio.run(
            build_spot_replay_input_journal(
                resolver=MemoryResolver(closures),
                strategy_registry=MemoryRegistry(resolved),
                request=replace(request, strategy=bad_strategy),
            )
        )
    assert strategy_error.value.reason is SpotReplayInputFailure.STRATEGY_UNAVAILABLE


@pytest.mark.parametrize(
    "resolved_change",
    [
        lambda value: replace(value, c021_lifecycle=StrategyLifecycle.RESEARCH),
        lambda value: replace(value, availability=StrategyAvailability.SUSPENDED),
        lambda value: replace(
            value, artifact_lifecycle=ArtifactVersionLifecycle.RETIRED
        ),
    ],
)
def test_ineligible_historical_strategy_lifecycle_is_rejected(resolved_change):
    request, closures, resolved, _, _ = _case()
    with pytest.raises(SpotReplayInputUnavailable) as error:
        asyncio.run(
            build_spot_replay_input_journal(
                resolver=MemoryResolver(closures),
                strategy_registry=MemoryRegistry(resolved_change(resolved)),
                request=request,
            )
        )
    assert error.value.reason is SpotReplayInputFailure.STRATEGY_UNAVAILABLE


def test_late_strategy_creation_and_non_backtest_scope_are_rejected():
    request, closures, resolved, _, _ = _case()
    late_version = replace(
        resolved.version, created_at=LATER_CUTOFF + STEP, content_sha256="0" * 64
    )
    late_version = replace(
        late_version, content_sha256=strategy_version_content_sha256(late_version)
    )
    late = replace(resolved, version=late_version)
    late_pin = replace(
        request.strategy,
        content_sha256=late_version.content_sha256,
    )
    late_request = replace(request, strategy=late_pin)
    with pytest.raises(SpotReplayInputUnavailable) as error:
        asyncio.run(
            build_spot_replay_input_journal(
                resolver=MemoryResolver(closures),
                strategy_registry=MemoryRegistry(late),
                request=late_request,
            )
        )
    assert error.value.reason is SpotReplayInputFailure.STRATEGY_UNAVAILABLE
    research_version = replace(
        resolved.version,
        operating_modes=(OperatingMode.RESEARCH,),
        content_sha256="0" * 64,
    )
    research_version = replace(
        research_version,
        content_sha256=strategy_version_content_sha256(research_version),
    )
    research_request = replace(
        request,
        strategy=replace(
            request.strategy, content_sha256=research_version.content_sha256
        ),
    )
    with pytest.raises(SpotReplayInputUnavailable):
        asyncio.run(
            build_spot_replay_input_journal(
                resolver=MemoryResolver(closures),
                strategy_registry=MemoryRegistry(
                    replace(resolved, version=research_version)
                ),
                request=research_request,
            )
        )
