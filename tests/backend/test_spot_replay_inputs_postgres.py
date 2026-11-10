"""Disposable PostgreSQL replay-input tests with explicitly synthetic records."""

import asyncio
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_history_selection import T
from test_lineage_postgresql import database_url as database_url
from test_spot_replay_inputs import STEP, _case
from trading_platform_api.config import DeploymentEnvironment, OperatingMode
from trading_platform_api.lineage.codec import LineageKey
from trading_platform_api.lineage.store import SqlAlchemyLineageStore
from trading_platform_api.lineage.tables import records as lineage_records
from trading_platform_api.strategy.contracts import VersionReference
from trading_platform_api.strategy.registry import (
    ArtifactVersionLifecycle,
    LifecycleAxis,
    ResolvedLifecycleReference,
    StrategyRegistry,
)
from trading_platform_api.strategy.registry_store import SqlAlchemyStrategyRegistryStore
from trading_platform_api.strategy.tables import (
    strategy_registry_identities,
    strategy_registry_lifecycle_events,
    strategy_registry_versions,
)
from trading_platform_api.validation.spot_replay_inputs import (
    SpotReplayInputRequest,
    build_spot_replay_input_journal,
)


class FixtureReferenceResolver:
    def __init__(self):
        self.references = {}

    def bind(self, reference, subject_id, status):
        self.references[reference] = ResolvedLifecycleReference(
            reference, status, subject_id
        )

    async def resolve(self, reference, *, at):
        return self.references.get(reference)


def _reference(kind):
    return VersionReference(kind, uuid4(), "1", "a" * 64)


def _bind_transition(resolver, subject_id, *, status="AVAILABLE", kind="C-030"):
    decision = _reference("C-057")
    evidence = _reference(kind)
    resolver.bind(decision, subject_id, "APPROVED")
    resolver.bind(evidence, subject_id, status)
    return decision, (evidence,)


async def _register_strategy(session, resolved):
    strategy, version = resolved.strategy, resolved.version
    references = FixtureReferenceResolver()
    registry = StrategyRegistry(
        SqlAlchemyStrategyRegistryStore(session),
        reference_resolver=references,
        clock=lambda: T + 10 * STEP,
    )
    identity_decision, identity_evidence = _bind_transition(
        references, strategy.strategy_id
    )
    await registry.register_strategy(
        strategy,
        actor="synthetic-test",
        reason="synthetic replay fixture",
        decision_reference=identity_decision,
        evidence_references=identity_evidence,
        effective_at=T,
    )
    version_decision = _reference("C-057")
    references.bind(version_decision, version.strategy_version_id, "APPROVED")
    version_evidence = version.provenance
    for reference in version_evidence:
        references.bind(reference, version.strategy_version_id, "AVAILABLE")
    await registry.register_version(
        version,
        actor="synthetic-test",
        reason="synthetic replay fixture",
        decision_reference=version_decision,
        evidence_references=version_evidence,
        effective_at=T,
    )
    c021_decision, c021_evidence = _bind_transition(
        references, version.strategy_version_id, status="PASSED", kind="C-028"
    )
    result = await registry.transition(
        axis=LifecycleAxis.C021_VERSION,
        strategy_id=version.strategy_id,
        strategy_version_id=version.strategy_version_id,
        to_status="VALIDATED",
        actor="synthetic-test",
        reason="synthetic backtest eligibility",
        decision_reference=c021_decision,
        evidence_references=c021_evidence,
        environment=DeploymentEnvironment.TEST,
        operating_mode=OperatingMode.BACKTEST,
        effective_at=T + STEP,
    )
    assert result.accepted
    candidate_decision, candidate_evidence = _bind_transition(
        references, version.strategy_version_id
    )
    result = await registry.transition(
        axis=LifecycleAxis.ARTIFACT_VERSION,
        strategy_id=version.strategy_id,
        strategy_version_id=version.strategy_version_id,
        to_status=ArtifactVersionLifecycle.CANDIDATE.value,
        actor="synthetic-test",
        reason="synthetic candidate fixture",
        decision_reference=candidate_decision,
        evidence_references=candidate_evidence,
        environment=DeploymentEnvironment.TEST,
        operating_mode=OperatingMode.BACKTEST,
        effective_at=T + STEP,
    )
    assert result.accepted
    validated_decision, validated_evidence = _bind_transition(
        references,
        version.strategy_version_id,
        status="PASSED",
        kind="C-028",
    )
    result = await registry.transition(
        axis=LifecycleAxis.ARTIFACT_VERSION,
        strategy_id=version.strategy_id,
        strategy_version_id=version.strategy_version_id,
        to_status=ArtifactVersionLifecycle.VALIDATED.value,
        actor="synthetic-test",
        reason="synthetic validation fixture",
        decision_reference=validated_decision,
        evidence_references=validated_evidence,
        environment=DeploymentEnvironment.TEST,
        operating_mode=OperatingMode.BACKTEST,
        effective_at=T + 2 * STEP,
    )
    assert result.accepted


def _merge_records(closures, *, manifest_sha256):
    key = LineageKey("C-103", manifest_sha256)
    return closures[key]


def _counts():
    return (
        select(func.count()).select_from(lineage_records),
        select(func.count()).select_from(strategy_registry_identities),
        select(func.count()).select_from(strategy_registry_versions),
        select(func.count()).select_from(strategy_registry_lifecycle_events),
    )


def test_postgresql_read_only_journal_survives_later_correction(database_url):
    async def check():
        url = make_url(database_url)
        assert url.drivername == "postgresql+asyncpg"
        assert url.host in ("127.0.0.1", "localhost") and url.database == "lineage_test"
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        request, closures, resolved, _, _ = _case(dataset_prefix=f"postgres-{uuid4()}")
        early_closure = _merge_records(
            closures, manifest_sha256=request.decisions[0].manifest_sha256
        )
        later_closure = _merge_records(
            closures, manifest_sha256=request.decisions[1].manifest_sha256
        )
        try:
            async with sessions.begin() as session:
                await _register_strategy(session, resolved)
                store = SqlAlchemyLineageStore(session)
                for record in early_closure.values():
                    await store.append(record)

            async def replay(run_request: SpotReplayInputRequest):
                async with sessions.begin() as session:
                    await session.execute(text("SET TRANSACTION READ ONLY"))
                    before = tuple(
                        (await session.execute(statement)).scalar_one()
                        for statement in _counts()
                    )
                    journal = await build_spot_replay_input_journal(
                        resolver=SqlAlchemyLineageStore(session),
                        strategy_registry=StrategyRegistry(
                            SqlAlchemyStrategyRegistryStore(session),
                            reference_resolver=None,
                            clock=lambda: T + 10 * STEP,
                        ),
                        request=run_request,
                    )
                    after = tuple(
                        (await session.execute(statement)).scalar_one()
                        for statement in _counts()
                    )
                    assert after == before
                    return journal

            early_request = replace_request(request, (request.decisions[0],))
            first_early = await replay(early_request)
            async with sessions.begin() as session:
                store = SqlAlchemyLineageStore(session)
                existing = set(early_closure)
                for key, record in later_closure.items():
                    if key not in existing:
                        await store.append(record)

            full_first = await replay(request)
            full_second = await replay(request)
            assert full_first == full_second
            assert full_first.decisions[0] == first_early.decisions[0]
            assert full_first.decisions[1].usable_revisions[0].revision_id != (
                first_early.decisions[0].usable_revisions[0].revision_id
            )
        finally:
            await engine.dispose()

    asyncio.run(check())


def replace_request(request, decisions):
    return SpotReplayInputRequest(
        request.scope, request.strategy, decisions, request.limits
    )
