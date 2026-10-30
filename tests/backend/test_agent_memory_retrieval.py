from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from trading_platform_api.agents.memory_retrieval import (
    MAX_MEMORY_CONTEXT_ITEMS,
    MemoryContextCandidate,
    MemoryItemState,
    MemoryRetrievalError,
    MemoryRetrievalRequest,
    MemoryRetrievalScope,
    MemoryRetrievalStatus,
    retrieve_memory_context,
)
from trading_platform_api.risk import ContractReference, VersionReference
from trading_platform_api.safety import (
    EvidenceReference,
    PromptInjectionAssessment,
    PromptInjectionVerdict,
    SecuritySeverity,
)

NOW = datetime(2026, 10, 30, 8, tzinfo=UTC)
CONTENT = "Earlier Spot evidence summary; historical context only."


def _assessment(
    evidence: EvidenceReference,
    *,
    verdict: PromptInjectionVerdict = PromptInjectionVerdict.CLEAR,
    **overrides: object,
) -> PromptInjectionAssessment:
    values: dict[str, object] = {
        "assessment_id": uuid4(),
        "untrusted_content_ref": evidence,
        "actor_ref": "owner:personal-spot",
        "agent_ref": "personal-spot-research@1",
        "model_ref": "route:research-model-v1",
        "prompt_ref": "prompt:spot-analyst-v1",
        "tool_context_ref": "context:current-analysis",
        "verdict": verdict,
        "severity": SecuritySeverity.LOW,
        "indicators": (),
        "requested_effects": (),
        "required_responses": (),
        "blocks_tool_escalation": False,
        "assessed_at": NOW - timedelta(seconds=5),
        "as_of": NOW - timedelta(seconds=10),
        "valid_until": NOW + timedelta(minutes=1),
        "detector_version": VersionReference("injection-detector", "1", "a" * 64),
        "model_version": VersionReference("research-model", "1", "b" * 64),
        "prompt_version": VersionReference("spot-prompt", "1", "c" * 64),
        "policy_version": VersionReference("injection-policy", "1", "d" * 64),
        "content_sha256": evidence.content_sha256,
    }
    if verdict is not PromptInjectionVerdict.CLEAR:
        values.update(
            severity=SecuritySeverity.HIGH,
            indicators=("UNTRUSTED_INSTRUCTION",),
            required_responses=("BLOCK_TOOL_ESCALATION",),
            blocks_tool_escalation=True,
        )
    values.update(overrides)
    return PromptInjectionAssessment(**values)  # type: ignore[arg-type]


def _candidate(
    *,
    content: str = CONTENT,
    state: MemoryItemState = MemoryItemState.ACTIVE,
    instrument: str = "BTC-USDT-SPOT",
    timeframe: str = "1m",
    environment: str = "local",
    mode: str = "PERSONAL_SPOT_RESEARCH",
    created_at: datetime = NOW - timedelta(minutes=2),
    expires_at: datetime = NOW + timedelta(minutes=2),
    assessment: PromptInjectionAssessment | None = None,
    assessment_verdict: PromptInjectionVerdict = PromptInjectionVerdict.CLEAR,
    assessment_overrides: dict[str, object] | None = None,
    source_ref: ContractReference | None = None,
) -> MemoryContextCandidate:
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    evidence = EvidenceReference(
        "HISTORICAL_ANALYSIS_SUMMARY",
        uuid4(),
        "spot-analysis-lineage",
        "1",
        digest,
    )
    return MemoryContextCandidate(
        evidence=evidence,
        source_ref=source_ref
        or ContractReference(
            "C-005", uuid4(), "1", valid_until=NOW + timedelta(days=1)
        ),
        content=content,
        state=state,
        market="SPOT",
        instrument=instrument,
        timeframe=timeframe,
        environment=environment,
        mode=mode,
        created_at=created_at,
        expires_at=expires_at,
        injection_assessment=assessment
        or _assessment(
            evidence, verdict=assessment_verdict, **(assessment_overrides or {})
        ),
    )


def _request(*, max_results: int = MAX_MEMORY_CONTEXT_ITEMS) -> MemoryRetrievalRequest:
    return MemoryRetrievalRequest(
        task_id=uuid4(),
        context_id=uuid4(),
        correlation_id=uuid4(),
        trace_id=uuid4(),
        agent_id="personal-spot-research",
        agent_version="1",
        actor_ref="owner:personal-spot",
        model_ref="route:research-model-v1",
        prompt_ref="prompt:spot-analyst-v1",
        tool_context_ref="context:current-analysis",
        scope=MemoryRetrievalScope(
            market="SPOT",
            instrument="BTC-USDT-SPOT",
            timeframe="1m",
            environment="local",
            mode="PERSONAL_SPOT_RESEARCH",
        ),
        as_of=NOW,
        max_results=max_results,
    )


class _Source:
    def __init__(self, items: tuple[MemoryContextCandidate, ...]) -> None:
        self.items = items

    async def retrieve_candidates(
        self, request: MemoryRetrievalRequest
    ) -> tuple[MemoryContextCandidate, ...]:
        return self.items


class _Resolver:
    def __init__(self, usable: bool = True) -> None:
        self.usable = usable
        self.calls: list[ContractReference] = []

    def is_usable(self, source_ref: ContractReference, as_of: datetime) -> bool:
        self.calls.append(source_ref)
        return self.usable


def test_retrieves_provenance_bound_current_context_in_deterministic_order() -> None:
    older = _candidate(created_at=NOW - timedelta(minutes=4))
    newer = _candidate(created_at=NOW - timedelta(minutes=1))
    resolver = _Resolver()
    request = _request()

    result = asyncio.run(
        retrieve_memory_context(
            request, source=_Source((older, newer)), provenance_resolver=resolver
        )
    )

    assert result.status is MemoryRetrievalStatus.FOUND
    assert tuple(item.evidence for item in result.items) == (
        newer.evidence,
        older.evidence,
    )
    assert result.items[0].injection_assessment is newer.injection_assessment
    assert (
        result.task_id,
        result.context_id,
        result.correlation_id,
        result.trace_id,
    ) == (
        request.task_id,
        request.context_id,
        request.correlation_id,
        request.trace_id,
    )
    assert len(resolver.calls) == 2


def test_empty_eligible_set_is_explicit_and_valid() -> None:
    result = asyncio.run(
        retrieve_memory_context(
            _request(), source=_Source(()), provenance_resolver=_Resolver()
        )
    )

    assert result.status is MemoryRetrievalStatus.EMPTY
    assert result.items == ()
    assert result.reason_code is None


@pytest.mark.parametrize(
    "candidate",
    [
        _candidate(state=MemoryItemState.REVOKED),
        _candidate(state=MemoryItemState.INVALID),
        _candidate(expires_at=NOW),
        _candidate(created_at=NOW + timedelta(seconds=1)),
        _candidate(instrument="ETH-USDT-SPOT"),
        _candidate(timeframe="5m"),
        _candidate(environment="docker"),
        _candidate(mode="BACKTEST"),
        _candidate(assessment_verdict=PromptInjectionVerdict.SUSPICIOUS),
        _candidate(assessment_overrides={"valid_until": NOW - timedelta(seconds=1)}),
        _candidate(
            assessment_overrides={"tool_context_ref": "context:another-analysis"}
        ),
        _candidate(source_ref=ContractReference("C-095", uuid4(), "1")),
    ],
)
def test_excludes_stale_wrong_scope_revoked_and_unsafe_candidates(
    candidate: MemoryContextCandidate,
) -> None:
    result = asyncio.run(
        retrieve_memory_context(
            _request(), source=_Source((candidate,)), provenance_resolver=_Resolver()
        )
    )

    assert result.status is MemoryRetrievalStatus.EMPTY
    assert result.items == ()


def test_excludes_unresolved_or_incompatible_provenance() -> None:
    result = asyncio.run(
        retrieve_memory_context(
            _request(),
            source=_Source((_candidate(),)),
            provenance_resolver=_Resolver(False),
        )
    )

    assert result.status is MemoryRetrievalStatus.EMPTY
    assert result.items == ()


def test_source_or_lineage_failure_returns_unavailable_without_context() -> None:
    class FailedSource:
        async def retrieve_candidates(
            self, request: MemoryRetrievalRequest
        ) -> tuple[MemoryContextCandidate, ...]:
            raise RuntimeError("provider error must not escape")

    class FailedResolver:
        def is_usable(self, source_ref: ContractReference, as_of: datetime) -> bool:
            raise RuntimeError("lineage error must not escape")

    source_result = asyncio.run(
        retrieve_memory_context(
            _request(), source=FailedSource(), provenance_resolver=_Resolver()
        )
    )
    lineage_result = asyncio.run(
        retrieve_memory_context(
            _request(),
            source=_Source((_candidate(),)),
            provenance_resolver=FailedResolver(),
        )
    )

    assert source_result.status is MemoryRetrievalStatus.UNAVAILABLE
    assert source_result.items == ()
    assert source_result.reason_code == "SOURCE_UNAVAILABLE"
    assert lineage_result.status is MemoryRetrievalStatus.UNAVAILABLE
    assert lineage_result.items == ()
    assert lineage_result.reason_code == "PROVENANCE_UNAVAILABLE"


def test_applies_result_bound_and_does_not_grant_authority() -> None:
    items = tuple(_candidate() for _ in range(MAX_MEMORY_CONTEXT_ITEMS + 2))
    result = asyncio.run(
        retrieve_memory_context(
            _request(max_results=2),
            source=_Source(items),
            provenance_resolver=_Resolver(),
        )
    )

    assert len(result.items) == 2
    assert not hasattr(result, "permissions")
    assert not hasattr(result, "risk_decision")
    assert not hasattr(result, "approval")
    assert not hasattr(result, "execution_intent")


def test_rejects_unbounded_or_invalid_scope_requests() -> None:
    with pytest.raises(MemoryRetrievalError, match="max_results"):
        _request(max_results=MAX_MEMORY_CONTEXT_ITEMS + 1)
    with pytest.raises(MemoryRetrievalError, match="Spot"):
        MemoryRetrievalScope("FUTURES", "BTCUSDT", "1m", "local", "TEST")
