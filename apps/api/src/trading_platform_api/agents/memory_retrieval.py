"""Provider-neutral, request-scoped retrieval of untrusted agent context.

This module defines an orchestration boundary only. It has no persistence,
embedding, ranking-provider, model, or tool-execution dependency. A future source
must provide exact evidence/provenance records and a current C-089 assessment;
retrieved text remains untrusted context and never acquires trading authority.
"""

from __future__ import annotations

import hashlib
import inspect
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from trading_platform_api.agents.registry import resolve_agent_definition
from trading_platform_api.risk import ContractReference
from trading_platform_api.safety import (
    EvidenceReference,
    PromptInjectionAssessment,
    PromptInjectionVerdict,
)

MAX_MEMORY_CONTEXT_ITEMS = 8


class MemoryRetrievalError(ValueError):
    """Raised when trusted retrieval request identity or bounds are invalid."""


class MemoryItemState(StrEnum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    INVALID = "INVALID"


class MemoryRetrievalStatus(StrEnum):
    FOUND = "FOUND"
    EMPTY = "EMPTY"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class MemoryRetrievalScope:
    """Exact Spot profile scope supplied by trusted orchestration code."""

    market: str
    instrument: str
    timeframe: str
    environment: str
    mode: str

    def __post_init__(self) -> None:
        for name in ("market", "instrument", "timeframe", "environment", "mode"):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value.strip()
                or value != value.strip()
            ):
                raise MemoryRetrievalError(f"{name} is invalid.")
        if self.market != "SPOT":
            raise MemoryRetrievalError("only the bounded Spot retrieval path exists.")


@dataclass(frozen=True, slots=True)
class MemoryRetrievalRequest:
    """Trusted task and route binding for one bounded retrieval operation."""

    task_id: UUID
    context_id: UUID
    correlation_id: UUID
    trace_id: UUID
    agent_id: str
    agent_version: str
    actor_ref: str
    model_ref: str
    prompt_ref: str
    tool_context_ref: str
    scope: MemoryRetrievalScope
    as_of: datetime
    max_results: int = MAX_MEMORY_CONTEXT_ITEMS

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, UUID)
            for value in (
                self.task_id,
                self.context_id,
                self.correlation_id,
                self.trace_id,
            )
        ):
            raise MemoryRetrievalError(
                "task, context, correlation, and trace IDs must be UUIDs."
            )
        for name in (
            "agent_id",
            "agent_version",
            "actor_ref",
            "model_ref",
            "prompt_ref",
            "tool_context_ref",
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value.strip()
                or value != value.strip()
            ):
                raise MemoryRetrievalError(f"{name} is invalid.")
        if type(self.scope) is not MemoryRetrievalScope:
            raise MemoryRetrievalError("an exact retrieval scope is required.")
        if not isinstance(self.as_of, datetime) or self.as_of.tzinfo is None:
            raise MemoryRetrievalError("as_of must be timezone-aware.")
        object.__setattr__(self, "as_of", self.as_of.astimezone(UTC))
        if (
            not isinstance(self.max_results, int)
            or isinstance(self.max_results, bool)
            or not 1 <= self.max_results <= MAX_MEMORY_CONTEXT_ITEMS
        ):
            raise MemoryRetrievalError(
                f"max_results must be between 1 and {MAX_MEMORY_CONTEXT_ITEMS}."
            )


@dataclass(frozen=True, slots=True)
class MemoryContextCandidate:
    """One untrusted source item with exact evidence and lineage identities."""

    evidence: EvidenceReference
    source_ref: ContractReference
    content: str
    state: MemoryItemState
    market: str
    instrument: str
    timeframe: str
    environment: str
    mode: str
    created_at: datetime
    expires_at: datetime
    injection_assessment: PromptInjectionAssessment

    def __post_init__(self) -> None:
        if type(self.evidence) is not EvidenceReference:
            raise MemoryRetrievalError("candidate evidence reference is invalid.")
        if type(self.source_ref) is not ContractReference:
            raise MemoryRetrievalError("candidate source reference is invalid.")
        if not isinstance(self.content, str) or not self.content.strip():
            raise MemoryRetrievalError("candidate content is invalid.")
        if type(self.state) is not MemoryItemState:
            raise MemoryRetrievalError("candidate state is invalid.")
        for name in (
            "market",
            "instrument",
            "timeframe",
            "environment",
            "mode",
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value.strip()
                or value != value.strip()
            ):
                raise MemoryRetrievalError(f"candidate {name} is invalid.")
        if not isinstance(self.created_at, datetime) or self.created_at.tzinfo is None:
            raise MemoryRetrievalError("created_at must be timezone-aware.")
        if not isinstance(self.expires_at, datetime) or self.expires_at.tzinfo is None:
            raise MemoryRetrievalError("expires_at must be timezone-aware.")
        created = self.created_at.astimezone(UTC)
        expires = self.expires_at.astimezone(UTC)
        if created >= expires:
            raise MemoryRetrievalError("candidate validity window must be positive.")
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "expires_at", expires)
        if type(self.injection_assessment) is not PromptInjectionAssessment:
            raise MemoryRetrievalError("a typed C-089 assessment is required.")


@dataclass(frozen=True, slots=True)
class RetrievedMemoryContext:
    """Bounded untrusted context; contains no permission or decision authority."""

    evidence: EvidenceReference
    source_ref: ContractReference
    injection_assessment: PromptInjectionAssessment
    content: str
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class MemoryRetrievalResult:
    task_id: UUID
    context_id: UUID
    correlation_id: UUID
    trace_id: UUID
    status: MemoryRetrievalStatus
    items: tuple[RetrievedMemoryContext, ...]
    reason_code: str | None = None


class MemoryContextSource(Protocol):
    """Provider-neutral source interface; implementations own their storage."""

    async def retrieve_candidates(
        self, request: MemoryRetrievalRequest
    ) -> tuple[MemoryContextCandidate, ...]: ...


class MemoryProvenanceResolver(Protocol):
    """Resolve current lineage, revocation, and exact schema compatibility."""

    def is_usable(
        self, source_ref: ContractReference, as_of: datetime
    ) -> bool | Awaitable[bool]: ...


async def _resolve_usable(
    resolver: MemoryProvenanceResolver, source_ref: ContractReference, as_of: datetime
) -> bool:
    result = resolver.is_usable(source_ref, as_of)
    if inspect.isawaitable(result):
        result = await result
    return result is True


def _matches_request(
    candidate: MemoryContextCandidate, request: MemoryRetrievalRequest
) -> bool:
    scope = request.scope
    assessment = candidate.injection_assessment
    if candidate.state is not MemoryItemState.ACTIVE:
        return False
    if (candidate.market, candidate.instrument, candidate.timeframe) != (
        scope.market,
        scope.instrument,
        scope.timeframe,
    ):
        return False
    if (candidate.environment, candidate.mode) != (scope.environment, scope.mode):
        return False
    if candidate.created_at > request.as_of or candidate.expires_at <= request.as_of:
        return False
    if (
        candidate.source_ref.valid_until is not None
        and candidate.source_ref.valid_until <= request.as_of
    ):
        return False
    if hashlib.sha256(candidate.content.encode("utf-8")).hexdigest() != (
        candidate.evidence.content_sha256
    ):
        return False
    if assessment.untrusted_content_ref != candidate.evidence:
        return False
    if assessment.content_sha256 != candidate.evidence.content_sha256:
        return False
    if (
        assessment.actor_ref != request.actor_ref
        or assessment.agent_ref != f"{request.agent_id}@{request.agent_version}"
        or assessment.model_ref != request.model_ref
        or assessment.prompt_ref != request.prompt_ref
        or assessment.tool_context_ref != request.tool_context_ref
    ):
        return False
    if (
        assessment.as_of > request.as_of
        or assessment.assessed_at > request.as_of
        or assessment.valid_until <= request.as_of
        or assessment.verdict is not PromptInjectionVerdict.CLEAR
        or assessment.blocks_tool_escalation
    ):
        return False
    return True


async def retrieve_memory_context(
    request: MemoryRetrievalRequest,
    *,
    source: MemoryContextSource,
    provenance_resolver: MemoryProvenanceResolver,
) -> MemoryRetrievalResult:
    """Return only current, compatible, exact-scope C-089 CLEAR context.

    Source and lineage failures produce an explicit UNAVAILABLE result. Bad,
    stale, revoked, mismatched, or unsafe individual candidates are excluded.
    The result is sorted by creation time (newest first), then stable evidence ID;
    no semantic similarity score is interpreted as authority.
    """

    if type(request) is not MemoryRetrievalRequest:
        raise MemoryRetrievalError("a validated retrieval request is required.")
    try:
        definition = resolve_agent_definition(request.agent_id, request.agent_version)
    except (KeyError, ValueError):
        raise MemoryRetrievalError(
            "exact registered agent version is unavailable."
        ) from None
    if request.scope.mode not in definition.allowed_modes:
        raise MemoryRetrievalError("agent is not registered for the requested mode.")

    try:
        candidates = await source.retrieve_candidates(request)
    except Exception:
        return MemoryRetrievalResult(
            task_id=request.task_id,
            context_id=request.context_id,
            correlation_id=request.correlation_id,
            trace_id=request.trace_id,
            status=MemoryRetrievalStatus.UNAVAILABLE,
            items=(),
            reason_code="SOURCE_UNAVAILABLE",
        )
    if not isinstance(candidates, tuple) or any(
        type(item) is not MemoryContextCandidate for item in candidates
    ):
        return MemoryRetrievalResult(
            task_id=request.task_id,
            context_id=request.context_id,
            correlation_id=request.correlation_id,
            trace_id=request.trace_id,
            status=MemoryRetrievalStatus.UNAVAILABLE,
            items=(),
            reason_code="SOURCE_RESPONSE_INVALID",
        )

    allowed_inputs = set(definition.allowed_inputs)
    eligible: list[MemoryContextCandidate] = []
    try:
        for candidate in candidates:
            if candidate.source_ref.contract_id not in allowed_inputs:
                continue
            if not _matches_request(candidate, request):
                continue
            if not await _resolve_usable(
                provenance_resolver, candidate.source_ref, request.as_of
            ):
                continue
            eligible.append(candidate)
    except Exception:
        return MemoryRetrievalResult(
            task_id=request.task_id,
            context_id=request.context_id,
            correlation_id=request.correlation_id,
            trace_id=request.trace_id,
            status=MemoryRetrievalStatus.UNAVAILABLE,
            items=(),
            reason_code="PROVENANCE_UNAVAILABLE",
        )

    eligible.sort(
        key=lambda item: (item.created_at, str(item.evidence.evidence_id)),
        reverse=True,
    )
    items = tuple(
        RetrievedMemoryContext(
            evidence=item.evidence,
            source_ref=item.source_ref,
            injection_assessment=item.injection_assessment,
            content=item.content,
            created_at=item.created_at,
            expires_at=item.expires_at,
        )
        for item in eligible[: request.max_results]
    )
    return MemoryRetrievalResult(
        task_id=request.task_id,
        context_id=request.context_id,
        correlation_id=request.correlation_id,
        trace_id=request.trace_id,
        status=MemoryRetrievalStatus.FOUND if items else MemoryRetrievalStatus.EMPTY,
        items=items,
    )
