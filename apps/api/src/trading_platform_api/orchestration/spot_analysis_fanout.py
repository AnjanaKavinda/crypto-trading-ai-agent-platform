"""Bounded fan-out for validated, deterministic Spot analytical findings.

This runner coordinates local, side-effect-free analytical operations only. It
does not invoke models, tools, providers, risk, approval, or execution systems.
Its fan-in preserves each typed finding and task identity; C-093 remains the
authority for observed dependence analysis and never establishes statistical
independence for this Spot profile.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from trading_platform_api.analysis.spot_meta_analysis import (
    SUPPORTED_SPOT_FINDING_DOMAINS,
    SpotMetaFinding,
)


class SpotAnalysisFanoutError(ValueError):
    """Raised when a fan-out request exceeds its trusted bounds."""


class SpotAnalysisTaskStatus(StrEnum):
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"


@dataclass(frozen=True, slots=True)
class SpotAnalysisTask:
    """One trusted domain-specific local analysis operation."""

    task_id: UUID
    domain: str
    run: Callable[[], Awaitable[SpotMetaFinding]]

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, UUID):
            raise SpotAnalysisFanoutError("task_id must be a UUID.")
        if not isinstance(self.domain, str) or self.domain not in SUPPORTED_SPOT_FINDING_DOMAINS:
            raise SpotAnalysisFanoutError("domain is outside the approved Spot profile.")
        if not callable(self.run):
            raise SpotAnalysisFanoutError("run must be a trusted analysis operation.")


@dataclass(frozen=True, slots=True)
class SpotAnalysisTaskOutcome:
    """One task result with shared correlation and a bounded failure code."""

    correlation_id: UUID
    task_id: UUID
    domain: str
    status: SpotAnalysisTaskStatus
    finding: SpotMetaFinding | None
    failure_code: str | None


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
        raise SpotAnalysisFanoutError("all tasks must be validated SpotAnalysisTask values.")
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
        try:
            async with asyncio.timeout(timeout_seconds):
                async with semaphore:
                    finding = await task.run()
            if type(finding) is not SpotMetaFinding or finding.domain != task.domain:
                return SpotAnalysisTaskOutcome(
                    correlation_id,
                    task.task_id,
                    task.domain,
                    SpotAnalysisTaskStatus.FAILED,
                    None,
                    "INVALID_FINDING",
                )
            return SpotAnalysisTaskOutcome(
                correlation_id,
                task.task_id,
                task.domain,
                SpotAnalysisTaskStatus.COMPLETE,
                finding,
                None,
            )
        except TimeoutError:
            return SpotAnalysisTaskOutcome(
                correlation_id,
                task.task_id,
                task.domain,
                SpotAnalysisTaskStatus.TIMED_OUT,
                None,
                "ANALYSIS_TIMEOUT",
            )
        except Exception:
            # Never expose arbitrary callback exception text to logs or callers.
            return SpotAnalysisTaskOutcome(
                correlation_id,
                task.task_id,
                task.domain,
                SpotAnalysisTaskStatus.FAILED,
                None,
                "ANALYSIS_FAILED",
            )

    outcomes = await asyncio.gather(*(execute(task) for task in tasks))
    return SpotAnalysisFanoutResult(correlation_id, tuple(outcomes))
