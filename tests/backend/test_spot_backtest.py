"""Focused point-in-time and fail-closed boundary tests for Spot backtest."""

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest
from test_agent_evaluation import NOW, _result, _run
from trading_platform_api.validation.spot_backtest import (
    SpotBacktestOutcome,
    _evaluation_is_point_in_time,
    run_spot_backtest,
)


def test_archived_evaluation_is_usable_at_its_decision_time():
    evaluation = _run(_result())

    assert _evaluation_is_point_in_time(evaluation, evaluation.evaluated_at)


@pytest.mark.parametrize("timestamp", ["started_at", "ended_at", "evaluated_at"])
def test_each_archived_evaluation_timestamp_must_not_follow_the_decision(timestamp):
    evaluation = _run(_result())
    baseline = replace(
        evaluation,
        started_at=evaluation.started_at - timedelta(hours=1),
        ended_at=evaluation.ended_at - timedelta(hours=1),
        evaluated_at=evaluation.evaluated_at - timedelta(hours=1),
    )
    decision_time = baseline.evaluated_at + timedelta(microseconds=1)
    names = ("started_at", "ended_at", "evaluated_at")
    first_late = names.index(timestamp)
    late_values = {
        name: getattr(baseline, name) + timedelta(seconds=1)
        for name in names[first_late:]
    }
    late_evaluation = replace(baseline, duration_ms=None, **late_values)

    assert not _evaluation_is_point_in_time(late_evaluation, decision_time)


def test_later_timestamp_on_any_archived_evaluation_edge_is_rejected():
    evaluation = _run(_result())

    assert not _evaluation_is_point_in_time(
        evaluation, evaluation.ended_at - timedelta(microseconds=1)
    )
    assert not _evaluation_is_point_in_time(
        evaluation, NOW - timedelta(seconds=2)
    )


def test_public_backtest_entry_fails_closed_without_trusted_offline_resolvers():
    class MustNotResolve:
        async def resolve_version(self, **_kwargs):
            pytest.fail("untrusted/incomplete replay reached strategy resolution")

    async def run():
        return await run_spot_backtest(
            request=object(),
            session=object(),
            strategy_registry=MustNotResolve(),
            lineage_store=object(),
        )

    result = asyncio.run(run())

    assert result.outcome is SpotBacktestOutcome.INCONCLUSIVE
    assert result.reason_codes == ("TRUSTED_OFFLINE_RESOLVER_UNAVAILABLE",)
    assert result.trace is None
    assert result.result is None
