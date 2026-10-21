from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

import pytest
from trading_platform_api.analysis import (
    AnalysisSnapshotV4,
    AnalyticalDirection,
    ConflictMaterialityV2,
    ConfluenceEvidenceStrengthV2,
    EvidenceRelation,
    FindingReadiness,
    SpotMetaFinding,
    VersionReference,
)
from trading_platform_api.analysis.versioned_contracts import EvidenceItemV2
from trading_platform_api.analysis.versioned_contracts_v4 import (
    ResolvedSpotOHLCVBindingV4,
)
from trading_platform_api.orchestration import spot_analysis_fanout as fanout_module
from trading_platform_api.orchestration.spot_analysis_fanout import (
    SpotAnalysisFanoutError,
    SpotAnalysisTask,
    SpotAnalysisTaskReason,
    SpotAnalysisTaskStatus,
    SpotAnalysisUnavailable,
    run_spot_analysis_fanout,
    run_spot_analysis_fanout_with_independence,
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
    assert all(
        item.status is SpotAnalysisTaskStatus.COMPLETE for item in result.outcomes
    )
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
    assert result.outcomes[1].reason_code is SpotAnalysisTaskReason.ANALYSIS_FAILED


def test_fanout_preserves_unavailable_reason_and_successful_findings() -> None:
    async def unavailable() -> SpotAnalysisUnavailable:
        return SpotAnalysisUnavailable(SpotAnalysisTaskReason.POLICY_REQUIRED)

    async def succeed() -> SpotMetaFinding:
        return _finding("spot-trend")

    result = asyncio.run(
        run_spot_analysis_fanout(
            (
                _task("spot-trend", succeed),
                _task("spot-momentum", unavailable),
            ),
            correlation_id=uuid4(),
        )
    )

    unavailable_outcome = result.outcomes[1]
    assert result.is_partial
    assert len(result.findings) == 1
    assert unavailable_outcome.status is SpotAnalysisTaskStatus.UNAVAILABLE
    assert unavailable_outcome.finding is None
    assert unavailable_outcome.reason_code is SpotAnalysisTaskReason.POLICY_REQUIRED


def test_composed_fanout_assesses_only_successful_findings_with_c093(monkeypatch) -> None:
    finding = _finding("spot-trend")
    unavailable_reason = SpotAnalysisTaskReason.POLICY_REQUIRED
    report = object()
    observed = {}

    async def succeed() -> SpotMetaFinding:
        return finding

    async def unavailable() -> SpotAnalysisUnavailable:
        return SpotAnalysisUnavailable(unavailable_reason)

    def assess_agent_independence(**kwargs):
        observed.update(kwargs)
        return report

    monkeypatch.setattr(
        fanout_module, "assess_agent_independence", assess_agent_independence
    )
    correlation_id = uuid4()
    manifest = cast(AnalysisSnapshotV4, object())
    bindings = cast(tuple[ResolvedSpotOHLCVBindingV4, ...], (object(),))
    evidence: Mapping[UUID, EvidenceItemV2] = {}
    result = asyncio.run(
        run_spot_analysis_fanout_with_independence(
            (
                _task("spot-trend", succeed),
                _task("spot-momentum", unavailable),
            ),
            correlation_id=correlation_id,
            manifest=manifest,
            resolved_bindings=bindings,
            evidence=evidence,
            now=cast(datetime, object()),
        )
    )

    assert result.fanout.correlation_id == correlation_id
    assert result.fanout.is_partial
    assert result.independence_report is report
    assert observed["findings"] == (finding,)
    assert observed["manifest"] is manifest
    assert observed["resolved_bindings"] is bindings
    assert observed["evidence"] is evidence


def test_unavailable_reason_must_use_bounded_enum() -> None:
    with pytest.raises(SpotAnalysisFanoutError, match="bounded"):
        SpotAnalysisUnavailable("caller supplied free-form explanation")  # type: ignore[arg-type]


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
    assert result.outcomes[0].reason_code is SpotAnalysisTaskReason.ANALYSIS_TIMEOUT
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
