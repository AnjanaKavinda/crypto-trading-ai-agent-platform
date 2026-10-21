from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from trading_platform_api.analysis import (
    AnalyticalDirection,
    ConfluenceEvidenceStrengthV2,
    ConflictMaterialityV2,
    EvidenceRelation,
    FindingReadiness,
    SpotMetaFinding,
    VersionReference,
)
from trading_platform_api.orchestration.spot_analysis_fanout import (
    SpotAnalysisFanoutError,
    SpotAnalysisTask,
    SpotAnalysisTaskStatus,
    run_spot_analysis_fanout,
)


def _finding(domain: str) -> SpotMetaFinding:
    return SpotMetaFinding(
        finding_id=uuid4(),
        domain=domain,
        direction=next(iter(AnalyticalDirection)),
        relation=next(iter(EvidenceRelation)),
        evidence_strength=next(iter(ConfluenceEvidenceStrengthV2)),
        readiness=FindingReadiness.READY,
        evidence_ids=(uuid4(),),
        input_binding_ids=(uuid4(),),
        method=VersionReference("test-analysis", "1"),
        materiality=ConflictMaterialityV2.UNKNOWN,
    )


def _task(domain: str, run) -> SpotAnalysisTask:
    return SpotAnalysisTask(uuid4(), domain, run)


def test_fanout_bounds_concurrency_and_preserves_correlation_and_order() -> None:
    active = 0
    peak = 0
    correlation_id = uuid4()

    async def operation(domain: str) -> SpotMetaFinding:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return _finding(domain)

    tasks = (
        _task("spot-trend", lambda: operation("spot-trend")),
        _task("spot-momentum", lambda: operation("spot-momentum")),
        _task("spot-volatility", lambda: operation("spot-volatility")),
    )
    result = asyncio.run(
        run_spot_analysis_fanout(
            tasks, correlation_id=correlation_id, max_concurrency=2
        )
    )

    assert peak == 2
    assert result.correlation_id == correlation_id
    assert tuple(item.domain for item in result.outcomes) == (
        "spot-trend",
        "spot-momentum",
        "spot-volatility",
    )
    assert all(item.correlation_id == correlation_id for item in result.outcomes)
    assert all(item.status is SpotAnalysisTaskStatus.COMPLETE for item in result.outcomes)
    assert not result.is_partial


def test_fanout_isolates_failure_without_losing_successful_findings() -> None:
    async def fail() -> SpotMetaFinding:
        raise RuntimeError("sensitive provider detail must not escape")

    async def succeed() -> SpotMetaFinding:
        return _finding("spot-trend")

    result = asyncio.run(
        run_spot_analysis_fanout(
            (
                _task("spot-trend", succeed),
                _task("spot-momentum", fail),
            ),
            correlation_id=uuid4(),
        )
    )

    assert result.is_partial
    assert len(result.findings) == 1
    assert result.outcomes[1].status is SpotAnalysisTaskStatus.FAILED
    assert result.outcomes[1].failure_code == "ANALYSIS_FAILED"


def test_fanout_timeout_is_explicit_and_does_not_retry() -> None:
    calls = 0

    async def slow() -> SpotMetaFinding:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return _finding("spot-trend")

    result = asyncio.run(
        run_spot_analysis_fanout(
            (_task("spot-trend", slow),),
            correlation_id=uuid4(),
            timeout_seconds=0.001,
        )
    )

    assert result.outcomes[0].status is SpotAnalysisTaskStatus.TIMED_OUT
    assert result.outcomes[0].failure_code == "ANALYSIS_TIMEOUT"
    assert calls == 1


def test_fanout_rejects_duplicate_domains_and_unbounded_concurrency() -> None:
    async def operation() -> SpotMetaFinding:
        return _finding("spot-trend")

    tasks = (
        _task("spot-trend", operation),
        _task("spot-trend", operation),
    )
    with pytest.raises(SpotAnalysisFanoutError, match="each Spot domain"):
        asyncio.run(run_spot_analysis_fanout(tasks, correlation_id=uuid4()))

    with pytest.raises(SpotAnalysisFanoutError, match="max_concurrency"):
        asyncio.run(
            run_spot_analysis_fanout(
                (_task("spot-trend", operation),),
                correlation_id=uuid4(),
                max_concurrency=5,
            )
        )
