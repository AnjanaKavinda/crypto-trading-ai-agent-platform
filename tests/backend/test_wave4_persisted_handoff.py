"""Checkpoint the real persisted producer/consumer bridge with synthetic providers."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from test_lineage_postgresql import database_url as database_url
from test_spot_research_api import (
    INSTRUMENT,
    client_for,
    refresh_body,
)
from test_spot_research_api import (
    persisted_service as persisted_service,
)
from test_strategy_condition_evaluator import _setup
from test_strategy_registry import Resolver, bind_registration
from trading_platform_api.config import DeploymentEnvironment, OperatingMode
from trading_platform_api.lineage.codec import LineageKey
from trading_platform_api.lineage.store import SqlAlchemyLineageStore
from trading_platform_api.spot_research_store import spot_producer_request_reservations
from trading_platform_api.strategy.registry import (
    StrategyRegistry,
    build_personal_spot_strategy_v2,
    strategy_version_content_sha256,
)
from trading_platform_api.strategy.registry_store import SqlAlchemyStrategyRegistryStore
from trading_platform_api.strategy_api import (
    ApiVersionReference,
    SqlAlchemyStrategySignalApiService,
    StrategyEvaluationRequest,
    _compose_persisted_spot_debate,
)


def test_persisted_producer_recomposes_exact_strategy_consumer_inputs(
    persisted_service,
    monkeypatch,
):
    research, market_calls, repository, now = persisted_service
    with client_for(research) as client:
        response = client.post(
            f"/api/research/spot/{INSTRUMENT}/refresh",
            json=refresh_body(timeframe="1m", limit=50, now=now),
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["analysis_fanout"]["status"] == "AVAILABLE"

    async def check():
        async with repository._session_factory() as session:
            row = (
                (
                    await session.execute(
                        select(spot_producer_request_reservations).where(
                            spot_producer_request_reservations.c.snapshot_id
                            == payload["snapshot_id"],
                            spot_producer_request_reservations.c.status == "COMPLETED",
                        )
                    )
                )
                .mappings()
                .one()
            )
            key = LineageKey(
                row["context_contract_id"],
                row["context_record_id"],
                row["context_version"],
            )
            store = SqlAlchemyLineageStore(session)
            handoff = await store.get_spot_agent_handoff(key)
            assert handoff is not None
            result, evaluation, correlation_id, trace_id = handoff
            inputs = await _compose_persisted_spot_debate(
                session=session,
                store=store,
                context_key=key,
                context=result.output,
                result=result,
                evaluation=evaluation,
                correlation_id=correlation_id,
                trace_id=trace_id,
                now=result.generated_at,
            )
            assert inputs.debate.market_context == result.output
            assert (
                inputs.manifest.snapshot_id
                == result.output.analysis_snapshot.snapshot_id
            )
            assert inputs.fanout.correlation_id == correlation_id
            assert inputs.resolved_bindings

            original, _ = _setup()
            identity = replace(original.strategy, created_at=now - timedelta(days=2))
            parent = replace(
                original.version,
                created_at=now - timedelta(days=1),
                environments=(DeploymentEnvironment.TEST,),
                supported_timeframes=("1m",),
            )
            parent = replace(
                parent, content_sha256=strategy_version_content_sha256(parent)
            )
            version = build_personal_spot_strategy_v2(
                parent, strategy_version_id=uuid4(), created_at=now - timedelta(hours=1)
            )
            resolver = Resolver()
            tick = [now - timedelta(seconds=10)]

            def clock():
                tick[0] += timedelta(microseconds=1)
                return tick[0]

            registry = StrategyRegistry(
                SqlAlchemyStrategyRegistryStore(session),
                reference_resolver=resolver,
                clock=clock,
            )
            decision, evidence, _, _ = bind_registration(resolver, identity.strategy_id)
            await registry.register_strategy(
                identity,
                actor="checkpoint",
                reason="synthetic checkpoint identity",
                decision_reference=decision,
                evidence_references=evidence,
            )
            for item in (parent, version):
                _, _, decision, evidence = bind_registration(
                    resolver, identity.strategy_id, item
                )
                await registry.register_version(
                    item,
                    actor="checkpoint",
                    reason="synthetic checkpoint version",
                    decision_reference=decision,
                    evidence_references=evidence,
                )
            await session.commit()

            class ClockMeta(type):
                def __instancecheck__(cls, value):
                    return isinstance(value, datetime)

            class EvaluationClock(datetime, metaclass=ClockMeta):
                @classmethod
                def now(cls, tz=None):
                    return (result.generated_at + timedelta(seconds=1)).astimezone(tz)

            monkeypatch.setattr(
                "trading_platform_api.strategy_api.datetime", EvaluationClock
            )
            request = StrategyEvaluationRequest(
                strategy_version=ApiVersionReference(
                    contract_id="C-021",
                    schema_version="2",
                    artifact_id=version.strategy_version_id,
                    content_sha256=version.content_sha256,
                ),
                market_context=ApiVersionReference(
                    contract_id="C-006",
                    schema_version="5",
                    artifact_id=result.output.context_id,
                    content_sha256=row["context_sha256"],
                ),
            )
        service = SqlAlchemyStrategySignalApiService(
            repository._session_factory,
            environment=DeploymentEnvironment.TEST,
            mode=OperatingMode.RESEARCH,
        )
        first = await service.evaluate(request, correlation_id="checkpoint-first")
        replay = await service.evaluate(request, correlation_id="checkpoint-replay")
        assert first == replay
        assert first.projection_state == "NO_TRADE"
        assert any(view.reference.contract_id == "C-026" for view in first.artifacts)
        assert all(view.reference.contract_id != "C-070" for view in first.artifacts)
        for artifact in first.artifacts:
            ref = artifact.reference
            if ref.contract_id == "C-022":
                continue  # Eligibility is internal, outside #90's detail-read surface.
            read = await service.get_artifact(
                contract_id=ref.contract_id,
                artifact_id=ref.artifact_id,
                schema_version=ref.schema_version,
                content_sha256=ref.content_sha256,
            )
            assert read is not None
            assert read.reference == ref

    asyncio.run(check())
    assert market_calls == [1]
    assert research.spot_agent_runtime.provider.calls == 1
