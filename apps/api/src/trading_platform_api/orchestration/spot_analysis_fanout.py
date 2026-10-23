"""Bounded fan-out for validated, deterministic Spot analytical findings.

This runner coordinates local, side-effect-free analytical operations only. It
does not invoke models, tools, providers, risk, approval, or execution systems.
Its fan-in preserves each typed finding and task identity; C-093 remains the
authority for observed dependence analysis and never establishes statistical
independence for this Spot profile.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from trading_platform_api.analysis.spot_meta_analysis import (
    SUPPORTED_SPOT_FINDING_DOMAINS,
    AgentIndependenceReport,
    SpotMetaFinding,
    assess_agent_independence,
)
from trading_platform_api.analysis.versioned_contracts import EvidenceItemV2
from trading_platform_api.analysis.versioned_contracts_v4 import (
    AnalysisSnapshotV4,
    ResolvedSpotOHLCVBindingV4,
)


class SpotAnalysisFanoutError(ValueError):
    """Raised when a fan-out request exceeds its trusted bounds."""


_DETACHED_ANALYSIS_TASKS: set[asyncio.Task[Any]] = set()


def _retain_detached_analysis_task(task: asyncio.Task[Any]) -> None:
    """Retain cancellation-resistant cleanup and consume any late exception."""

    _DETACHED_ANALYSIS_TASKS.add(task)

    def discard(completed: asyncio.Task[Any]) -> None:
        _DETACHED_ANALYSIS_TASKS.discard(completed)
        if not completed.cancelled():
            completed.exception()

    task.add_done_callback(discard)


class SpotAnalysisTaskStatus(StrEnum):
    COMPLETE = "COMPLETE"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"


class SpotAnalysisTaskReason(StrEnum):
    """Bounded task outcome reasons; arbitrary callback text is never retained."""

    ANALYSIS_FAILED = "ANALYSIS_FAILED"
    ANALYSIS_TIMEOUT = "ANALYSIS_TIMEOUT"
    INPUT_UNAVAILABLE = "INPUT_UNAVAILABLE"
    INSUFFICIENT_WARMUP = "INSUFFICIENT_WARMUP"
    INVALID_FINDING = "INVALID_FINDING"
    INVALID_INPUT = "INVALID_INPUT"
    POLICY_REQUIRED = "POLICY_REQUIRED"
    STALE_INPUT = "STALE_INPUT"


@dataclass(frozen=True, slots=True)
class SpotAnalysisUnavailable:
    """Expected unavailable state from a domain operation, with a safe reason."""

    reason_code: SpotAnalysisTaskReason

    def __post_init__(self) -> None:
        if type(self.reason_code) is not SpotAnalysisTaskReason:
            raise SpotAnalysisFanoutError(
                "unavailable results require a bounded SpotAnalysisTaskReason."
            )


@dataclass(frozen=True, slots=True)
class SpotAnalysisTask:
    """One trusted domain-specific local analysis operation."""

    task_id: UUID
    domain: str
    run: Callable[[], Awaitable[SpotMetaFinding | SpotAnalysisUnavailable]]

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, UUID):
            raise SpotAnalysisFanoutError("task_id must be a UUID.")
        if (
            not isinstance(self.domain, str)
            or self.domain not in SUPPORTED_SPOT_FINDING_DOMAINS
        ):
            raise SpotAnalysisFanoutError(
                "domain is outside the approved Spot profile."
            )
        if not callable(self.run):
            raise SpotAnalysisFanoutError("run must be a trusted analysis operation.")


@dataclass(frozen=True, slots=True)
class SpotAnalysisTaskOutcome:
    """One task result with shared correlation and a bounded reason code."""

    correlation_id: UUID
    task_id: UUID
    domain: str
    status: SpotAnalysisTaskStatus
    finding: SpotMetaFinding | None
    reason_code: SpotAnalysisTaskReason | None

    def __post_init__(self) -> None:
        if not isinstance(self.correlation_id, UUID) or not isinstance(
            self.task_id, UUID
        ):
            raise SpotAnalysisFanoutError("outcome IDs must be UUID values.")
        if type(self.status) is not SpotAnalysisTaskStatus:
            raise SpotAnalysisFanoutError("outcome status has an invalid type.")
        if (
            self.reason_code is not None
            and type(self.reason_code) is not SpotAnalysisTaskReason
        ):
            raise SpotAnalysisFanoutError("outcome reason must use the bounded enum.")
        if self.status is SpotAnalysisTaskStatus.COMPLETE:
            if (
                type(self.finding) is not SpotMetaFinding
                or self.reason_code is not None
            ):
                raise SpotAnalysisFanoutError(
                    "complete outcomes require one finding and no reason code."
                )
        elif self.finding is not None or self.reason_code is None:
            raise SpotAnalysisFanoutError(
                "non-complete outcomes require a reason code and no finding."
            )


@dataclass(frozen=True, slots=True)
class SpotAnalysisFanoutResult:
    """Ordered fan-in result; partial outcomes remain explicit."""

    correlation_id: UUID
    outcomes: tuple[SpotAnalysisTaskOutcome, ...]

    @property
    def findings(self) -> tuple[SpotMetaFinding, ...]:
        """Return only successful findings for downstream validation."""

        return tuple(
            item.finding
            for item in self.outcomes
            if item.status is SpotAnalysisTaskStatus.COMPLETE
            and item.finding is not None
        )

    @property
    def is_partial(self) -> bool:
        return any(
            item.status is not SpotAnalysisTaskStatus.COMPLETE for item in self.outcomes
        )


@dataclass(frozen=True, slots=True)
class SpotAnalysisFanoutAssessment:
    """Fan-out outcomes paired with C-093's bounded dependence assessment."""

    fanout: SpotAnalysisFanoutResult
    independence_report: AgentIndependenceReport


async def run_spot_analysis_fanout(
    tasks: tuple[SpotAnalysisTask, ...],
    *,
    correlation_id: UUID,
    max_concurrency: int = 4,
    timeout_seconds: float = 5.0,
) -> SpotAnalysisFanoutResult:
    """Run unique approved Spot domains concurrently with per-task deadlines.

    No retries or checkpointing are applied. The operations must be deterministic,
    local, and side-effect free so cancellation or a future restart cannot replay
    an external request. Successful findings retain their original evidence and
    method provenance for the downstream C-093 independence assessment.
    """

    if not isinstance(correlation_id, UUID):
        raise SpotAnalysisFanoutError("correlation_id must be a UUID.")
    if not isinstance(tasks, tuple) or not tasks:
        raise SpotAnalysisFanoutError("at least one immutable task is required.")
    if len(tasks) > len(SUPPORTED_SPOT_FINDING_DOMAINS):
        raise SpotAnalysisFanoutError("task count exceeds the approved Spot domains.")
    if any(type(task) is not SpotAnalysisTask for task in tasks):
        raise SpotAnalysisFanoutError(
            "all tasks must be validated SpotAnalysisTask values."
        )
    if len({task.task_id for task in tasks}) != len(tasks):
        raise SpotAnalysisFanoutError("task IDs must be unique.")
    if len({task.domain for task in tasks}) != len(tasks):
        raise SpotAnalysisFanoutError("each Spot domain may run at most once.")
    if (
        not isinstance(max_concurrency, int)
        or isinstance(max_concurrency, bool)
        or not 1 <= max_concurrency <= 4
    ):
        raise SpotAnalysisFanoutError("max_concurrency must be between 1 and 4.")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not 0 < timeout_seconds <= 60
    ):
        raise SpotAnalysisFanoutError("timeout_seconds must be between 0 and 60.")

    semaphore = asyncio.Semaphore(max_concurrency)

    async def execute(task: SpotAnalysisTask) -> SpotAnalysisTaskOutcome:
        async def run_operation() -> SpotMetaFinding | SpotAnalysisUnavailable:
            # Keep the semaphore inside the child task. If timed-out cleanup
            # resists cancellation, it continues to consume its concurrency slot.
            async with semaphore:
                return await task.run()

        operation = asyncio.create_task(run_operation())
        try:
            done, _ = await asyncio.wait((operation,), timeout=timeout_seconds)
            if not done:
                operation.cancel()
                _retain_detached_analysis_task(operation)
                return SpotAnalysisTaskOutcome(
                    correlation_id,
                    task.task_id,
                    task.domain,
                    SpotAnalysisTaskStatus.TIMED_OUT,
                    None,
                    SpotAnalysisTaskReason.ANALYSIS_TIMEOUT,
                )
            result = operation.result()
            if type(result) is SpotAnalysisUnavailable:
                return SpotAnalysisTaskOutcome(
                    correlation_id,
                    task.task_id,
                    task.domain,
                    SpotAnalysisTaskStatus.UNAVAILABLE,
                    None,
                    result.reason_code,
                )
            if type(result) is not SpotMetaFinding or result.domain != task.domain:
                return SpotAnalysisTaskOutcome(
                    correlation_id,
                    task.task_id,
                    task.domain,
                    SpotAnalysisTaskStatus.FAILED,
                    None,
                    SpotAnalysisTaskReason.INVALID_FINDING,
                )
            return SpotAnalysisTaskOutcome(
                correlation_id,
                task.task_id,
                task.domain,
                SpotAnalysisTaskStatus.COMPLETE,
                result,
                None,
            )
        except asyncio.CancelledError:
            if not operation.done():
                operation.cancel()
                _retain_detached_analysis_task(operation)
            raise
        except Exception:
            if not operation.done():
                operation.cancel()
                _retain_detached_analysis_task(operation)
            # Never expose arbitrary callback exception text to logs or callers.
            return SpotAnalysisTaskOutcome(
                correlation_id,
                task.task_id,
                task.domain,
                SpotAnalysisTaskStatus.FAILED,
                None,
                SpotAnalysisTaskReason.ANALYSIS_FAILED,
            )

    outcomes = await asyncio.gather(*(execute(task) for task in tasks))
    return SpotAnalysisFanoutResult(correlation_id, tuple(outcomes))


async def run_spot_analysis_fanout_with_independence(
    tasks: tuple[SpotAnalysisTask, ...],
    *,
    correlation_id: UUID,
    manifest: AnalysisSnapshotV4,
    resolved_bindings: tuple[ResolvedSpotOHLCVBindingV4, ...],
    evidence: Mapping[UUID, EvidenceItemV2],
    now: datetime,
    max_concurrency: int = 4,
    timeout_seconds: float = 5.0,
) -> SpotAnalysisFanoutAssessment:
    """Run local tasks, then assess only successful findings with C-093.

    C-093 receives the caller's exact validated analysis scope and controls
    whether the findings are usable for dependence assessment. It records
    observed shared inputs and does not establish statistical independence.
    Invalid or mismatched scope raises from C-093 rather than being hidden as a
    task failure.
    """

    fanout = await run_spot_analysis_fanout(
        tasks,
        correlation_id=correlation_id,
        max_concurrency=max_concurrency,
        timeout_seconds=timeout_seconds,
    )
    independence_report = assess_agent_independence(
        manifest=manifest,
        resolved_bindings=resolved_bindings,
        evidence=evidence,
        findings=fanout.findings,
        now=now,
    )
    return SpotAnalysisFanoutAssessment(fanout, independence_report)
