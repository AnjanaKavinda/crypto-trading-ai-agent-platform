"""Deterministic strategy registry tests using synthetic records only."""

from __future__ import annotations

import asyncio
import io
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from trading_platform_api.config import DeploymentEnvironment, OperatingMode
from trading_platform_api.contracts.serialization import serialize_contract
from trading_platform_api.strategy.contracts import (
    ConditionGroup,
    ConditionGroupOperator,
    ConditionOperator,
    Strategy,
    StrategyCondition,
    StrategyLifecycle,
    StrategyParameter,
    StrategyVersion,
    VersionReference,
)
from trading_platform_api.strategy.registry import (
    ArtifactVersionLifecycle,
    LifecycleAxis,
    ResolvedLifecycleReference,
    StrategyAvailability,
    StrategyRegistry,
    StrategyRegistryError,
    semantic_version_is_greater,
    strategy_version_content_sha256,
    validate_semantic_version,
)
from trading_platform_api.strategy.registry_store import (
    SqlAlchemyStrategyRegistryStore,
    _decode_contract,
)

NOW = datetime(2026, 10, 19, 12, tzinfo=UTC)
DIGEST = "a" * 64
REPO_ROOT = Path(__file__).resolve().parents[2]


def ref(
    kind: str, artifact_id: UUID | None = None, digest: str = DIGEST
) -> VersionReference:
    return VersionReference(kind, artifact_id or uuid4(), "1", digest)


class MemoryStore:
    """Small transaction-free test double; stored contracts remain frozen."""

    def __init__(self) -> None:
        self.strategies: dict[UUID, Strategy] = {}
        self.versions: dict[UUID, StrategyVersion] = {}
        self.events: list[object] = []
        self.audits: list[object] = []

    async def register_strategy(self, strategy, initial_event, audit_event) -> None:
        if strategy.strategy_id in self.strategies:
            raise StrategyRegistryError("duplicate strategy identity")
        self.strategies[strategy.strategy_id] = strategy
        self.events.append(initial_event)
        self.audits.append(audit_event)

    async def register_version(self, version, initial_events, audit_events) -> None:
        if version.strategy_version_id in self.versions:
            raise StrategyRegistryError("duplicate strategy version ID")
        if any(
            item.strategy_id == version.strategy_id
            and item.semantic_version == version.semantic_version
            for item in self.versions.values()
        ):
            raise StrategyRegistryError("duplicate semantic version")
        self.versions[version.strategy_version_id] = version
        self.events.extend(initial_events)
        self.audits.extend(audit_events)

    async def get_strategy(self, strategy_id):
        return self.strategies.get(strategy_id)

    async def get_version(self, strategy_version_id):
        return self.versions.get(strategy_version_id)

    async def get_version_by_semantic_version(self, strategy_id, semantic_version):
        return next(
            (
                item
                for item in self.versions.values()
                if item.strategy_id == strategy_id
                and item.semantic_version == semantic_version
            ),
            None,
        )

    async def current_status(
        self, axis, strategy_id, strategy_version_id, *, as_of=None
    ):
        rows = [
            event
            for event in self.events
            if event.axis is axis
            and event.strategy_id == strategy_id
            and event.strategy_version_id == strategy_version_id
            and (as_of is None or event.effective_at <= as_of)
        ]
        rows.sort(
            key=lambda event: (
                event.effective_at,
                event.recorded_at,
                str(event.event_id),
            )
        )
        return rows[-1].to_status if rows else None

    async def history(self, axis, strategy_id, strategy_version_id):
        rows = [
            event
            for event in self.events
            if event.axis is axis
            and event.strategy_id == strategy_id
            and event.strategy_version_id == strategy_version_id
        ]
        return tuple(
            sorted(
                rows,
                key=lambda event: (
                    event.effective_at,
                    event.recorded_at,
                    str(event.event_id),
                ),
            )
        )

    async def append_transition(self, event, audit_event, *, expected_from_status):
        current = await self.current_status(
            event.axis, event.strategy_id, event.strategy_version_id
        )
        if event.from_status != expected_from_status or current != expected_from_status:
            return False
        self.events.append(event)
        self.audits.append(audit_event)
        return True

    async def append_rejected_transition(self, audit_event):
        self.audits.append(audit_event)


class Resolver:
    def __init__(self) -> None:
        self.items: dict[VersionReference, ResolvedLifecycleReference] = {}

    def bind(
        self,
        reference: VersionReference,
        subject_id: UUID,
        status: str = "APPROVED",
        *,
        expires_at: datetime | None = None,
        environment: DeploymentEnvironment | None = None,
        operating_mode: OperatingMode | None = None,
    ) -> None:
        self.items[reference] = ResolvedLifecycleReference(
            reference, status, subject_id, expires_at, environment, operating_mode
        )

    async def resolve(self, reference, *, at):
        return self.items.get(reference)


class LyingResolver(Resolver):
    def __init__(
        self, requested: VersionReference, wrong: VersionReference, subject_id: UUID
    ):
        super().__init__()
        self.items[requested] = ResolvedLifecycleReference(
            wrong, "APPROVED", subject_id
        )


def strategy(strategy_id: UUID | None = None) -> Strategy:
    return Strategy(
        strategy_id or uuid4(),
        "Trend pullback",
        "Synthetic test strategy",
        "RULE_BASED",
        NOW,
    )


def version(strategy_id: UUID, **overrides: object) -> StrategyVersion:
    condition = StrategyCondition(
        uuid4(), "market.regime", ConditionOperator.EQUALS, ("trend",), "v1"
    )
    values: dict[str, object] = {
        "strategy_version_id": uuid4(),
        "strategy_id": strategy_id,
        "semantic_version": "1.0.0",
        "lifecycle": StrategyLifecycle.RESEARCH,
        "content_sha256": DIGEST,
        "parent_version_id": None,
        "parameters": (StrategyParameter("lookback", "20", "bars"),),
        "conditions": (condition,),
        "condition_groups": (
            ConditionGroup(
                uuid4(), ConditionGroupOperator.AND, (condition.condition_id,)
            ),
        ),
        "supported_assets": ("BTC",),
        "supported_instruments": ("BTC-USDT-SPOT",),
        "supported_timeframes": ("1h",),
        "preferred_regimes": ("trend",),
        "acceptable_regimes": (),
        "incompatible_regimes": (),
        "required_evidence_categories": ("technical",),
        "entry_concept": "breakout retest",
        "invalidation_concept": "structure break",
        "target_concepts": ("next resistance",),
        "environments": (DeploymentEnvironment.DEV,),
        "operating_modes": (OperatingMode.RESEARCH,),
        "provenance": (ref("C-030"),),
        "created_at": NOW,
    }
    values.update(overrides)
    result = StrategyVersion(**values)  # type: ignore[arg-type]
    return replace(result, content_sha256=strategy_version_content_sha256(result))


def configured_registry():
    store = MemoryStore()
    resolver = Resolver()
    current = [NOW]

    def clock():
        value = current[0]
        current[0] += timedelta(microseconds=1)
        return value

    registry = StrategyRegistry(store, reference_resolver=resolver, clock=clock)
    return store, resolver, registry


def bind_registration(
    resolver: Resolver, strategy_id: UUID, item: StrategyVersion | None = None
):
    identity_decision = ref("C-057")
    identity_evidence = ref("C-030")
    resolver.bind(identity_decision, strategy_id)
    resolver.bind(identity_evidence, uuid4(), "AVAILABLE")
    version_decision = None
    version_evidence = None
    if item is not None:
        version_decision = ref("C-057")
        version_evidence = item.provenance[0]
        resolver.bind(version_decision, item.strategy_version_id)
        resolver.bind(version_evidence, uuid4(), "AVAILABLE")
    return (
        identity_decision,
        (identity_evidence,),
        version_decision,
        (version_evidence,) if version_evidence else (),
    )


def bind_transition(
    resolver: Resolver,
    subject_id: UUID,
    *,
    decision_status: str = "APPROVED",
    evidence_type: str = "C-030",
    evidence_status: str = "AVAILABLE",
) -> tuple[VersionReference, tuple[VersionReference, ...]]:
    decision = ref("C-057")
    evidence = ref(evidence_type)
    resolver.bind(decision, subject_id, decision_status)
    resolver.bind(evidence, subject_id, evidence_status)
    return decision, (evidence,)


def setup_registered():
    store, resolver, registry = configured_registry()
    identity = strategy()
    item = version(identity.strategy_id)
    identity_decision, identity_evidence, version_decision, version_evidence = (
        bind_registration(resolver, identity.strategy_id, item)
    )
    asyncio.run(
        registry.register_strategy(
            identity,
            actor="unit-test",
            reason="synthetic registration",
            decision_reference=identity_decision,
            evidence_references=identity_evidence,
        )
    )
    asyncio.run(
        registry.register_version(
            item,
            actor="unit-test",
            reason="synthetic version registration",
            decision_reference=version_decision,
            evidence_references=version_evidence,
        )
    )
    return store, resolver, registry, identity, item


def test_semver_is_canonical_and_compares_prereleases_by_spec():
    validate_semantic_version("1.2.3-alpha.2+build.9")
    assert semantic_version_is_greater("1.0.0", "1.0.0-rc.1")
    assert semantic_version_is_greater("1.0.0-rc.2", "1.0.0-rc.1")
    assert semantic_version_is_greater("1.0.0-alpha", "1.0.0-9")
    assert not semantic_version_is_greater("1.0.0-rc.1", "1.0.0")
    for invalid in ("01.0.0", "1.0", "1.0.0-01", "1.0.0-", "1.0.0+", "1.0.0-a..b"):
        with pytest.raises(StrategyRegistryError):
            validate_semantic_version(invalid)


def test_register_and_resolve_exact_immutable_contracts_on_three_axes():
    store, _, registry, identity, item = setup_registered()
    resolved = asyncio.run(
        registry.resolve_version(
            strategy_id=identity.strategy_id,
            strategy_version_id=item.strategy_version_id,
        )
    )
    assert resolved.strategy == identity
    assert resolved.version == item
    assert resolved.availability is StrategyAvailability.EXPERIMENTAL
    assert resolved.c021_lifecycle is StrategyLifecycle.RESEARCH
    assert resolved.artifact_lifecycle is ArtifactVersionLifecycle.DRAFT
    assert resolved.selectable_for_research
    assert len(store.events) == 3
    assert all(event.event_id == event.audit_id for event in store.events)
    assert all(
        event.event_id == audit.audit_id
        for event, audit in zip(store.events, store.audits, strict=True)
    )
    assert (
        asyncio.run(
            registry.resolve_version(
                strategy_id=identity.strategy_id, semantic_version="1.0.0"
            )
        )
        == resolved
    )
    with pytest.raises(StrategyRegistryError, match="exactly one"):
        asyncio.run(registry.resolve_version(strategy_id=identity.strategy_id))


def test_duplicate_identity_version_and_conflicting_hash_are_rejected():
    store, resolver, registry, identity, item = setup_registered()
    decision, evidence, _, _ = bind_registration(resolver, identity.strategy_id)
    with pytest.raises(StrategyRegistryError, match="duplicate"):
        asyncio.run(
            registry.register_strategy(
                identity,
                actor="unit-test",
                reason="duplicate",
                decision_reference=decision,
                evidence_references=evidence,
            )
        )
    _, _, decision, evidence = bind_registration(resolver, identity.strategy_id, item)
    with pytest.raises(StrategyRegistryError, match="duplicate"):
        asyncio.run(
            registry.register_version(
                item,
                actor="unit-test",
                reason="duplicate",
                decision_reference=decision,
                evidence_references=evidence,
            )
        )
    changed = replace(item, content_sha256="b" * 64)
    _, _, decision, evidence = bind_registration(
        resolver, identity.strategy_id, changed
    )
    with pytest.raises(StrategyRegistryError, match="content_sha256"):
        asyncio.run(
            registry.register_version(
                changed,
                actor="unit-test",
                reason="conflict",
                decision_reference=decision,
                evidence_references=evidence,
            )
        )
    assert store.versions[item.strategy_version_id] == item
    same_semver_new_id = version(identity.strategy_id)
    decision = ref("C-057")
    evidence = same_semver_new_id.provenance[0]
    resolver.bind(decision, same_semver_new_id.strategy_version_id)
    resolver.bind(evidence, uuid4(), "AVAILABLE")
    with pytest.raises(StrategyRegistryError, match="semantic version"):
        asyncio.run(
            registry.register_version(
                same_semver_new_id,
                actor="unit-test",
                reason="duplicate semantic version",
                decision_reference=decision,
                evidence_references=(evidence,),
            )
        )


def test_parent_must_exist_belong_to_identity_and_have_lower_semver():
    store, resolver, registry, identity, parent = setup_registered()
    child = version(
        identity.strategy_id,
        semantic_version="1.1.0",
        parent_version_id=parent.strategy_version_id,
    )
    decision = ref("C-057")
    evidence = child.provenance[0]
    resolver.bind(decision, child.strategy_version_id)
    resolver.bind(evidence, uuid4(), "AVAILABLE")
    asyncio.run(
        registry.register_version(
            child,
            actor="unit-test",
            reason="child",
            decision_reference=decision,
            evidence_references=(evidence,),
        )
    )
    assert (
        asyncio.run(
            registry.resolve_version(
                strategy_id=identity.strategy_id,
                strategy_version_id=parent.strategy_version_id,
            )
        ).version
        == parent
    )
    other_strategy_id = uuid4()
    unknown_parent = version(
        identity.strategy_id, semantic_version="1.2.0", parent_version_id=uuid4()
    )
    with pytest.raises(StrategyRegistryError, match="parent"):
        asyncio.run(
            registry.register_version(
                unknown_parent,
                actor="unit-test",
                reason="bad parent",
                decision_reference=decision,
                evidence_references=(evidence,),
            )
        )
    with pytest.raises(StrategyRegistryError, match="exceed"):
        same_version = version(
            identity.strategy_id,
            semantic_version="1.0.0",
            parent_version_id=parent.strategy_version_id,
        )
        decision_same = ref("C-057")
        evidence_same = same_version.provenance[0]
        resolver.bind(decision_same, same_version.strategy_version_id)
        resolver.bind(evidence_same, uuid4(), "AVAILABLE")
        asyncio.run(
            registry.register_version(
                same_version,
                actor="unit-test",
                reason="bad semver",
                decision_reference=decision_same,
                evidence_references=(evidence_same,),
            )
        )
    assert other_strategy_id not in store.strategies


def test_identity_availability_transitions_are_independent_and_audited():
    store, resolver, registry, identity, item = setup_registered()
    decision, evidence = bind_transition(resolver, identity.strategy_id)
    result = asyncio.run(
        registry.transition(
            axis=LifecycleAxis.STRATEGY_AVAILABILITY,
            strategy_id=identity.strategy_id,
            strategy_version_id=None,
            to_status="ACTIVE",
            actor="owner",
            reason="research selection enabled",
            decision_reference=decision,
            evidence_references=evidence,
        )
    )
    assert result.accepted and result.event is not None
    initial_effective_at = max(
        event.effective_at for event in store.events if event.from_status is None
    )
    historical = asyncio.run(
        registry.resolve_version(
            strategy_id=identity.strategy_id,
            strategy_version_id=item.strategy_version_id,
            as_of=initial_effective_at,
        )
    )
    assert historical.availability is StrategyAvailability.EXPERIMENTAL
    resolved = asyncio.run(
        registry.resolve_version(
            strategy_id=identity.strategy_id, semantic_version=item.semantic_version
        )
    )
    assert resolved.availability is StrategyAvailability.ACTIVE
    assert resolved.c021_lifecycle is StrategyLifecycle.RESEARCH
    assert resolved.artifact_lifecycle is ArtifactVersionLifecycle.DRAFT
    assert resolved.selectable_for_research
    decision, evidence = bind_transition(resolver, identity.strategy_id)
    suspended = asyncio.run(
        registry.transition(
            axis=LifecycleAxis.STRATEGY_AVAILABILITY,
            strategy_id=identity.strategy_id,
            strategy_version_id=None,
            to_status="SUSPENDED",
            actor="owner",
            reason="suspend",
            decision_reference=decision,
            evidence_references=evidence,
        )
    )
    assert suspended.accepted
    assert not asyncio.run(
        registry.resolve_version(
            strategy_id=identity.strategy_id, semantic_version=item.semantic_version
        )
    ).selectable_for_research
    decision, evidence = bind_transition(resolver, identity.strategy_id)
    deprecated = asyncio.run(
        registry.transition(
            axis=LifecycleAxis.STRATEGY_AVAILABILITY,
            strategy_id=identity.strategy_id,
            strategy_version_id=None,
            to_status="DEPRECATED",
            actor="owner",
            reason="retire identity",
            decision_reference=decision,
            evidence_references=evidence,
        )
    )
    assert deprecated.accepted
    before = len(store.events)
    decision, evidence = bind_transition(resolver, identity.strategy_id)
    terminal = asyncio.run(
        registry.transition(
            axis=LifecycleAxis.STRATEGY_AVAILABILITY,
            strategy_id=identity.strategy_id,
            strategy_version_id=None,
            to_status="ACTIVE",
            actor="owner",
            reason="illegal reactivation",
            decision_reference=decision,
            evidence_references=evidence,
        )
    )
    assert not terminal.accepted and terminal.reason_code == "ILLEGAL_TRANSITION"
    assert len(store.events) == before and len(store.audits) == len(store.events) + 1


def test_strategy_availability_experimental_can_suspend_then_reactivate():
    store, resolver, registry, identity, _ = setup_registered()

    async def transition(target: str):
        decision, evidence = bind_transition(resolver, identity.strategy_id)
        return await registry.transition(
            axis=LifecycleAxis.STRATEGY_AVAILABILITY,
            strategy_id=identity.strategy_id,
            strategy_version_id=None,
            to_status=target,
            actor="owner",
            reason=f"set strategy availability to {target}",
            decision_reference=decision,
            evidence_references=evidence,
        )

    async def check():
        suspended = await transition("SUSPENDED")
        assert suspended.accepted and suspended.event is not None
        reactivated = await transition("ACTIVE")
        assert reactivated.accepted and reactivated.event is not None
        assert (
            reactivated.event.resolves_suspension_event_id == suspended.event.event_id
        )
        assert (await transition("DEPRECATED")).accepted

    asyncio.run(check())
    assert (
        awaitable_status(
            store, LifecycleAxis.STRATEGY_AVAILABILITY, identity.strategy_id, None
        )
        == StrategyAvailability.DEPRECATED.value
    )


def test_version_lifecycle_requires_passed_validation_and_keeps_axes_separate():
    store, resolver, registry, identity, item = setup_registered()
    decision, evidence = bind_transition(
        resolver,
        item.strategy_version_id,
        evidence_type="C-020",
        evidence_status="AVAILABLE",
    )
    blocked = asyncio.run(
        registry.transition(
            axis=LifecycleAxis.C021_VERSION,
            strategy_id=identity.strategy_id,
            strategy_version_id=item.strategy_version_id,
            to_status="VALIDATED",
            actor="owner",
            reason="missing passed validation",
            decision_reference=decision,
            evidence_references=evidence,
            environment=DeploymentEnvironment.DEV,
            operating_mode=OperatingMode.RESEARCH,
        )
    )
    assert (
        not blocked.accepted
        and blocked.reason_code == "PASSED_VALIDATION_EVIDENCE_REQUIRED"
    )
    decision, evidence = bind_transition(
        resolver,
        item.strategy_version_id,
        evidence_type="C-028",
        evidence_status="PASSED",
    )
    accepted = asyncio.run(
        registry.transition(
            axis=LifecycleAxis.C021_VERSION,
            strategy_id=identity.strategy_id,
            strategy_version_id=item.strategy_version_id,
            to_status="VALIDATED",
            actor="owner",
            reason="validated",
            decision_reference=decision,
            evidence_references=evidence,
            environment=DeploymentEnvironment.DEV,
            operating_mode=OperatingMode.RESEARCH,
        )
    )
    assert accepted.accepted and accepted.event is not None
    assert accepted.event.environment is DeploymentEnvironment.DEV
    assert accepted.event.operating_mode is OperatingMode.RESEARCH
    resolved = asyncio.run(
        registry.resolve_version(
            strategy_id=identity.strategy_id, semantic_version=item.semantic_version
        )
    )
    assert resolved.c021_lifecycle is StrategyLifecycle.VALIDATED
    assert resolved.artifact_lifecycle is ArtifactVersionLifecycle.DRAFT
    assert resolved.availability is StrategyAvailability.EXPERIMENTAL
    assert resolved.selectable_for_research


def test_environment_mode_mismatch_and_wrong_exact_references_fail_closed():
    store, resolver, registry, identity, item = setup_registered()
    decision, evidence = bind_transition(
        resolver,
        item.strategy_version_id,
        evidence_type="C-028",
        evidence_status="PASSED",
    )
    wrong_scope = asyncio.run(
        registry.transition(
            axis=LifecycleAxis.C021_VERSION,
            strategy_id=identity.strategy_id,
            strategy_version_id=item.strategy_version_id,
            to_status="VALIDATED",
            actor="owner",
            reason="wrong mode",
            decision_reference=decision,
            evidence_references=evidence,
            environment=DeploymentEnvironment.PROD,
            operating_mode=OperatingMode.LIVE_SUPERVISED,
        )
    )
    assert (
        not wrong_scope.accepted
        and wrong_scope.reason_code == "INCOMPATIBLE_ENVIRONMENT_MODE"
    )
    wrong_reference = ref("C-057")
    resolver2 = LyingResolver(wrong_reference, ref("C-057"), identity.strategy_id)
    other_registry = StrategyRegistry(
        store, reference_resolver=resolver2, clock=lambda: NOW
    )
    with pytest.raises(StrategyRegistryError, match="unresolved or invalid"):
        asyncio.run(
            other_registry.register_strategy(
                strategy(),
                actor="owner",
                reason="wrong resolver",
                decision_reference=wrong_reference,
                evidence_references=(ref("C-030"),),
            )
        )
    assert store.strategies[identity.strategy_id] == identity


def test_resolver_must_return_the_exact_reference_digest_and_version():
    store = MemoryStore()
    identity = strategy()
    requested = ref("C-057")
    substituted = ref("C-057", digest="b" * 64)
    evidence = ref("C-030")
    resolver = LyingResolver(requested, substituted, identity.strategy_id)
    registry = StrategyRegistry(store, reference_resolver=resolver, clock=lambda: NOW)
    resolver.items[evidence] = ResolvedLifecycleReference(
        evidence, "AVAILABLE", uuid4()
    )
    with pytest.raises(StrategyRegistryError, match="unresolved or invalid"):
        asyncio.run(
            registry.register_strategy(
                identity,
                actor="owner",
                reason="resolver returned a substituted digest",
                decision_reference=requested,
                evidence_references=(evidence,),
            )
        )
    assert not store.strategies and not store.events


def test_expired_and_missing_governance_references_reject_registration():
    store, resolver, registry = configured_registry()
    identity = strategy()
    decision = ref("C-057")
    evidence = ref("C-030")
    resolver.bind(decision, identity.strategy_id, expires_at=NOW)
    resolver.bind(evidence, uuid4(), "AVAILABLE")
    with pytest.raises(StrategyRegistryError, match="unresolved or invalid"):
        asyncio.run(
            registry.register_strategy(
                identity,
                actor="owner",
                reason="expired",
                decision_reference=decision,
                evidence_references=(evidence,),
            )
        )
    with pytest.raises(StrategyRegistryError, match="unresolved or invalid"):
        asyncio.run(
            registry.register_strategy(
                identity,
                actor="owner",
                reason="missing",
                decision_reference=ref("C-057"),
                evidence_references=(evidence,),
            )
        )
    assert not store.strategies


def awaitable_status(
    store: MemoryStore, axis: LifecycleAxis, strategy_id: UUID, version_id: UUID | None
) -> str | None:
    return asyncio.run(store.current_status(axis, strategy_id, version_id))


def test_stale_or_invalid_evidence_is_rejected_even_when_reference_resolves():
    store, resolver, registry = configured_registry()
    identity = strategy()
    decision = ref("C-057")
    stale_evidence = ref("C-030")
    resolver.bind(decision, identity.strategy_id)
    resolver.bind(stale_evidence, uuid4(), "STALE")
    with pytest.raises(StrategyRegistryError, match="unresolved or expired"):
        asyncio.run(
            registry.register_strategy(
                identity,
                actor="owner",
                reason="stale evidence must not register",
                decision_reference=decision,
                evidence_references=(stale_evidence,),
            )
        )
    assert not store.strategies


def test_same_effective_timestamp_is_rejected_to_keep_history_order_unambiguous():
    store, resolver, registry, identity, _ = setup_registered()
    decision, evidence = bind_transition(resolver, identity.strategy_id)
    result = asyncio.run(
        registry.transition(
            axis=LifecycleAxis.STRATEGY_AVAILABILITY,
            strategy_id=identity.strategy_id,
            strategy_version_id=None,
            to_status="ACTIVE",
            actor="owner",
            reason="same time",
            decision_reference=decision,
            evidence_references=evidence,
            effective_at=NOW,
        )
    )
    assert not result.accepted and result.reason_code == "OUT_OF_ORDER_EFFECTIVE_TIME"
    assert (
        awaitable_status(
            store, LifecycleAxis.STRATEGY_AVAILABILITY, identity.strategy_id, None
        )
        == StrategyAvailability.EXPERIMENTAL.value
    )


def test_lifecycle_evidence_scope_must_match_immutable_version_scope():
    store, resolver, registry, identity, item = setup_registered()
    decision = ref("C-057")
    evidence = ref("C-028")
    resolver.bind(decision, item.strategy_version_id)
    resolver.bind(
        evidence,
        item.strategy_version_id,
        "PASSED",
        environment=DeploymentEnvironment.PROD,
        operating_mode=OperatingMode.LIVE_SUPERVISED,
    )
    result = asyncio.run(
        registry.transition(
            axis=LifecycleAxis.C021_VERSION,
            strategy_id=identity.strategy_id,
            strategy_version_id=item.strategy_version_id,
            to_status="VALIDATED",
            actor="owner",
            reason="mis-scoped validation evidence",
            decision_reference=decision,
            evidence_references=(evidence,),
            environment=DeploymentEnvironment.DEV,
            operating_mode=OperatingMode.RESEARCH,
        )
    )
    assert not result.accepted and result.reason_code == "INCOMPATIBLE_REFERENCE_SCOPE"
    assert (
        awaitable_status(
            store,
            LifecycleAxis.C021_VERSION,
            identity.strategy_id,
            item.strategy_version_id,
        )
        == "RESEARCH"
    )


def test_future_effective_time_fails_closed_and_is_audited():
    store, resolver, registry, identity, _ = setup_registered()
    decision, evidence = bind_transition(resolver, identity.strategy_id)
    result = asyncio.run(
        registry.transition(
            axis=LifecycleAxis.STRATEGY_AVAILABILITY,
            strategy_id=identity.strategy_id,
            strategy_version_id=None,
            to_status="ACTIVE",
            actor="owner",
            reason="future activation is invalid",
            decision_reference=decision,
            evidence_references=evidence,
            effective_at=NOW + timedelta(seconds=1),
        )
    )
    assert not result.accepted and result.reason_code == "FUTURE_EFFECTIVE_TIME"
    assert result.audit_event.recorded_at == NOW + timedelta(microseconds=2)
    assert (
        awaitable_status(
            store, LifecycleAxis.STRATEGY_AVAILABILITY, identity.strategy_id, None
        )
        == StrategyAvailability.EXPERIMENTAL.value
    )


def test_contract_codec_round_trips_exact_shapes_and_rejects_tampering():
    identity = strategy()
    item = version(identity.strategy_id)
    identity_document = serialize_contract(identity, payload_version="wire-1")
    version_document = serialize_contract(item, payload_version="wire-1")
    assert _decode_contract(identity_document, "C-020") == identity
    assert _decode_contract(version_document, "C-021") == item
    with pytest.raises(StrategyRegistryError, match="invalid or noncanonical"):
        _decode_contract(version_document.replace('"lookback"', '"lookback" '), "C-021")
    assert strategy_version_content_sha256(item) == item.content_sha256
    assert (
        strategy_version_content_sha256(
            replace(item, parameters=(StrategyParameter("lookback", "21", "bars"),))
        )
        != item.content_sha256
    )


def test_c021_terminal_lifecycle_states_are_not_research_selectable():
    identity = strategy()
    item = version(identity.strategy_id)
    from trading_platform_api.strategy.registry import ResolvedStrategyVersion

    for status in (
        StrategyLifecycle.REJECTED,
        StrategyLifecycle.RETIRED,
        StrategyLifecycle.ROLLED_BACK,
    ):
        resolved = ResolvedStrategyVersion(
            identity,
            item,
            StrategyAvailability.ACTIVE,
            status,
            ArtifactVersionLifecycle.DRAFT,
        )
        assert not resolved.selectable_for_research
    for status in (
        ArtifactVersionLifecycle.REJECTED,
        ArtifactVersionLifecycle.RETIRED,
        ArtifactVersionLifecycle.ROLLED_BACK,
    ):
        resolved = ResolvedStrategyVersion(
            identity,
            item,
            StrategyAvailability.EXPERIMENTAL,
            StrategyLifecycle.RESEARCH,
            status,
        )
        assert not resolved.selectable_for_research


def test_each_version_lifecycle_axis_runs_its_own_governed_path():
    store, resolver, registry, identity, item = setup_registered()
    rollback_target = version(identity.strategy_id, semantic_version="2.0.0")
    target_decision = ref("C-057")
    target_evidence = rollback_target.provenance[0]
    resolver.bind(target_decision, rollback_target.strategy_version_id)
    resolver.bind(target_evidence, uuid4(), "AVAILABLE")
    asyncio.run(
        registry.register_version(
            rollback_target,
            actor="owner",
            reason="register governed rollback target",
            decision_reference=target_decision,
            evidence_references=(target_evidence,),
        )
    )

    async def apply(
        axis: LifecycleAxis,
        version_id: UUID,
        status: str,
        *,
        validation: bool = False,
        decision_status: str = "APPROVED",
        rollback_target_version_id: UUID | None = None,
    ):
        evidence_kind = "C-028" if validation else "C-030"
        evidence_status = "PASSED" if validation else "AVAILABLE"
        decision, evidence = bind_transition(
            resolver,
            version_id,
            decision_status=decision_status,
            evidence_type=evidence_kind,
            evidence_status=evidence_status,
        )
        return await registry.transition(
            axis=axis,
            strategy_id=identity.strategy_id,
            strategy_version_id=version_id,
            to_status=status,
            actor="owner",
            reason=f"governed {status}",
            decision_reference=decision,
            evidence_references=evidence,
            environment=DeploymentEnvironment.DEV,
            operating_mode=OperatingMode.RESEARCH,
            rollback_target_version_id=rollback_target_version_id,
        )

    async def reach_approved_target(axis: LifecycleAxis) -> None:
        states = (
            ("VALIDATED", True),
            ("APPROVED_FOR_SHADOW", True),
            ("APPROVED_FOR_PAPER", True),
            ("APPROVED_FOR_PRODUCTION", True),
        )
        if axis is LifecycleAxis.ARTIFACT_VERSION:
            result = await apply(axis, rollback_target.strategy_version_id, "CANDIDATE")
            assert result.accepted
        for status, needs_validation in states:
            result = await apply(
                axis,
                rollback_target.strategy_version_id,
                status,
                validation=needs_validation,
            )
            assert result.accepted, (status, result.reason_code)

    async def rollback_active_source(axis: LifecycleAxis) -> None:
        states = (
            ("VALIDATED", True),
            ("APPROVED_FOR_SHADOW", True),
            ("APPROVED_FOR_PAPER", True),
            ("APPROVED_FOR_PRODUCTION", True),
            ("ACTIVE", True),
        )
        if axis is LifecycleAxis.ARTIFACT_VERSION:
            result = await apply(axis, item.strategy_version_id, "CANDIDATE")
            assert result.accepted
        for status, needs_validation in states:
            result = await apply(
                axis, item.strategy_version_id, status, validation=needs_validation
            )
            assert result.accepted, (status, result.reason_code)
        missing_target = await apply(axis, item.strategy_version_id, "ROLLED_BACK")
        assert not missing_target.accepted
        assert missing_target.reason_code == "ROLLBACK_TARGET_REQUIRED"
        self_target = await apply(
            axis,
            item.strategy_version_id,
            "ROLLED_BACK",
            rollback_target_version_id=item.strategy_version_id,
        )
        assert not self_target.accepted
        assert self_target.reason_code == "UNKNOWN_OR_INCOMPATIBLE_ROLLBACK_TARGET"
        result = await apply(
            axis,
            item.strategy_version_id,
            "ROLLED_BACK",
            rollback_target_version_id=rollback_target.strategy_version_id,
        )
        assert result.accepted, result.reason_code
        assert result.event is not None
        assert (
            result.event.rollback_target_version_id
            == rollback_target.strategy_version_id
        )

    async def check():
        for axis in (LifecycleAxis.C021_VERSION, LifecycleAxis.ARTIFACT_VERSION):
            await reach_approved_target(axis)
            await rollback_active_source(axis)

    asyncio.run(check())
    resolved = asyncio.run(
        registry.resolve_version(
            strategy_id=identity.strategy_id, semantic_version=item.semantic_version
        )
    )
    target = asyncio.run(
        registry.resolve_version(
            strategy_id=identity.strategy_id,
            strategy_version_id=rollback_target.strategy_version_id,
        )
    )
    assert resolved.c021_lifecycle is StrategyLifecycle.ROLLED_BACK
    assert resolved.artifact_lifecycle is ArtifactVersionLifecycle.ROLLED_BACK
    assert not resolved.selectable_for_research
    assert target.c021_lifecycle is StrategyLifecycle.APPROVED_FOR_PRODUCTION
    assert target.artifact_lifecycle is ArtifactVersionLifecycle.APPROVED_FOR_PRODUCTION
    for axis in (LifecycleAxis.C021_VERSION, LifecycleAxis.ARTIFACT_VERSION):
        history = asyncio.run(
            store.history(axis, identity.strategy_id, item.strategy_version_id)
        )
        assert history[-1].to_status == "ROLLED_BACK"
        assert (
            history[-1].rollback_target_version_id
            == rollback_target.strategy_version_id
        )


def test_version_rejection_is_terminal_and_has_append_only_history():
    store, resolver, registry, identity, item = setup_registered()
    decision, evidence = bind_transition(resolver, item.strategy_version_id)
    invalid = asyncio.run(
        registry.transition(
            axis=LifecycleAxis.C021_VERSION,
            strategy_id=identity.strategy_id,
            strategy_version_id=item.strategy_version_id,
            to_status="ACTIVE",
            actor="owner",
            reason="skip validation and approvals",
            decision_reference=decision,
            evidence_references=evidence,
            environment=DeploymentEnvironment.DEV,
            operating_mode=OperatingMode.RESEARCH,
        )
    )
    assert not invalid.accepted and invalid.reason_code == "ILLEGAL_TRANSITION"
    assert (
        awaitable_status(
            store,
            LifecycleAxis.C021_VERSION,
            identity.strategy_id,
            item.strategy_version_id,
        )
        == "RESEARCH"
    )
    decision, evidence = bind_transition(
        resolver,
        item.strategy_version_id,
        evidence_type="C-028",
        evidence_status="PASSED",
    )
    validated = asyncio.run(
        registry.transition(
            axis=LifecycleAxis.C021_VERSION,
            strategy_id=identity.strategy_id,
            strategy_version_id=item.strategy_version_id,
            to_status="VALIDATED",
            actor="owner",
            reason="validation passed",
            decision_reference=decision,
            evidence_references=evidence,
            environment=DeploymentEnvironment.DEV,
            operating_mode=OperatingMode.RESEARCH,
        )
    )
    assert validated.accepted
    decision, evidence = bind_transition(
        resolver, item.strategy_version_id, decision_status="REJECTED"
    )
    rejected = asyncio.run(
        registry.transition(
            axis=LifecycleAxis.C021_VERSION,
            strategy_id=identity.strategy_id,
            strategy_version_id=item.strategy_version_id,
            to_status="REJECTED",
            actor="owner",
            reason="governance rejected version",
            decision_reference=decision,
            evidence_references=evidence,
            environment=DeploymentEnvironment.DEV,
            operating_mode=OperatingMode.RESEARCH,
        )
    )
    assert rejected.accepted
    assert not asyncio.run(
        registry.resolve_version(
            strategy_id=identity.strategy_id,
            strategy_version_id=item.strategy_version_id,
        )
    ).selectable_for_research
    assert (
        len(
            asyncio.run(
                store.history(
                    LifecycleAxis.C021_VERSION,
                    identity.strategy_id,
                    item.strategy_version_id,
                )
            )
        )
        == 3
    )


@pytest.fixture(scope="module")
def registry_database_url():
    value = os.environ.get("LINEAGE_TEST_DATABASE_URL")
    if not value:
        pytest.skip(
            "PostgreSQL registry integration requires LINEAGE_TEST_DATABASE_URL."
        )
    url = make_url(value)
    if (
        url.drivername != "postgresql+asyncpg"
        or url.host not in {"localhost", "127.0.0.1"}
        or url.database != "lineage_test"
    ):
        pytest.skip(
            "Registry integration is restricted to the disposable local lineage_test database."
        )
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = value
    try:
        command.upgrade(Config("apps/api/alembic.ini"), "head")
        yield value
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def test_postgresql_roundtrip_and_immutable_registry_tables(registry_database_url):
    async def check():
        engine = create_async_engine(registry_database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        resolver = Resolver()
        identity = strategy()
        item = version(identity.strategy_id)
        identity_decision, identity_evidence, version_decision, version_evidence = (
            bind_registration(resolver, identity.strategy_id, item)
        )
        clock_tick = [0]

        def clock():
            clock_tick[0] += 1
            return NOW + timedelta(seconds=clock_tick[0])

        try:
            async with sessions.begin() as session:
                registry = StrategyRegistry(
                    SqlAlchemyStrategyRegistryStore(session),
                    reference_resolver=resolver,
                    clock=clock,
                )
                await registry.register_strategy(
                    identity,
                    actor="integration-test",
                    reason="synthetic identity",
                    decision_reference=identity_decision,
                    evidence_references=identity_evidence,
                )
                await registry.register_version(
                    item,
                    actor="integration-test",
                    reason="synthetic version",
                    decision_reference=version_decision,
                    evidence_references=version_evidence,
                )
                suspension_decision, suspension_evidence = bind_transition(
                    resolver, identity.strategy_id
                )
                suspended = await registry.transition(
                    axis=LifecycleAxis.STRATEGY_AVAILABILITY,
                    strategy_id=identity.strategy_id,
                    strategy_version_id=None,
                    to_status="SUSPENDED",
                    actor="integration-test",
                    reason="synthetic suspension",
                    decision_reference=suspension_decision,
                    evidence_references=suspension_evidence,
                )
                assert suspended.accepted and suspended.event is not None
                reactivation_decision, reactivation_evidence = bind_transition(
                    resolver, identity.strategy_id
                )
                reactivated = await registry.transition(
                    axis=LifecycleAxis.STRATEGY_AVAILABILITY,
                    strategy_id=identity.strategy_id,
                    strategy_version_id=None,
                    to_status="ACTIVE",
                    actor="integration-test",
                    reason="synthetic cause resolution",
                    decision_reference=reactivation_decision,
                    evidence_references=reactivation_evidence,
                )
                assert reactivated.accepted and reactivated.event is not None
                assert (
                    reactivated.event.resolves_suspension_event_id
                    == suspended.event.event_id
                )
            async with sessions() as session:
                registry = StrategyRegistry(
                    SqlAlchemyStrategyRegistryStore(session),
                    reference_resolver=resolver,
                    clock=lambda: NOW + timedelta(seconds=10),
                )
                resolved = await registry.resolve_version(
                    strategy_id=identity.strategy_id,
                    strategy_version_id=item.strategy_version_id,
                )
                assert resolved.strategy == identity
                assert resolved.version == item
                assert (
                    len(
                        await SqlAlchemyStrategyRegistryStore(session).history(
                            LifecycleAxis.C021_VERSION,
                            identity.strategy_id,
                            item.strategy_version_id,
                        )
                    )
                    == 1
                )
                availability_history = await SqlAlchemyStrategyRegistryStore(
                    session
                ).history(
                    LifecycleAxis.STRATEGY_AVAILABILITY,
                    identity.strategy_id,
                    None,
                )
                assert len(availability_history) == 3
                assert (
                    availability_history[-1].resolves_suspension_event_id
                    == availability_history[-2].event_id
                )
            for statement in (
                "UPDATE strategy_registry_versions SET semantic_version='9.9.9' "
                f"WHERE strategy_version_id='{item.strategy_version_id}'",
                "DELETE FROM strategy_registry_identities "
                f"WHERE strategy_id='{identity.strategy_id}'",
                "TRUNCATE strategy_registry_lifecycle_events",
            ):
                async with sessions() as session:
                    with pytest.raises(DBAPIError):
                        await session.execute(text(statement))
                    await session.rollback()
            async with sessions() as session:
                counts = await session.execute(
                    text(
                        "SELECT (SELECT count(*) FROM strategy_registry_identities), "
                        "(SELECT count(*) FROM strategy_registry_versions), "
                        "(SELECT count(*) FROM strategy_registry_lifecycle_events)"
                    )
                )
                assert counts.one() == (1, 1, 5)
        finally:
            await engine.dispose()

    asyncio.run(check())


def test_alembic_head_includes_registry_ddl_and_immutable_guards(monkeypatch):
    output = io.StringIO()
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://placeholder_user@localhost:5432/placeholder_db",
    )
    config = Config(str(REPO_ROOT / "apps/api/alembic.ini"), output_buffer=output)
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["0007_strategy_registry"]
    command.upgrade(config, "head", sql=True)
    sql = output.getvalue().upper()
    for table in (
        "STRATEGY_REGISTRY_IDENTITIES",
        "STRATEGY_REGISTRY_VERSIONS",
        "STRATEGY_REGISTRY_LIFECYCLE_EVENTS",
    ):
        assert f"CREATE TABLE {table}" in sql
        assert f"{table}_IMMUTABLE" in sql
    assert "FK_STRATEGY_REGISTRY_EVENT_AUDIT" in sql
    assert "FK_STRATEGY_REGISTRY_EVENT_RESOLVED_SUSPENSION" in sql
    assert "CK_STRATEGY_REGISTRY_EVENT_SUSPENSION_RESOLUTION" in sql
    assert "CK_STRATEGY_REGISTRY_EVENT_TARGET_STATUS" in sql
    assert "CK_STRATEGY_REGISTRY_EVENT_ROLLBACK_TARGET" in sql
    assert "FK_STRATEGY_REGISTRY_EVENT_ROLLBACK_TARGET" in sql
    assert "CK_STRATEGY_REGISTRY_EVENT_ENVIRONMENT_MODE_SCOPE" in sql
    assert "environment" in sql.lower()
    assert "operating_mode" in sql.lower()


def test_strategy_registry_migration_refuses_destructive_downgrade():
    import importlib.util

    migration_path = (
        REPO_ROOT / "apps/api/migrations/versions/0007_strategy_registry.py"
    )
    spec = importlib.util.spec_from_file_location(
        "strategy_registry_migration", migration_path
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with pytest.raises(RuntimeError, match="Destructive downgrade is prohibited"):
        migration.downgrade()
