"""Focused point-in-time regression coverage for Spot strategy replay."""

from datetime import timedelta

from test_agent_evaluation import NOW, _result, _run
from trading_platform_api.validation.spot_backtest import (
    _evaluation_is_point_in_time,
)


def test_archived_evaluation_must_be_available_by_the_decision_time():
    evaluation = _run(_result())

    assert _evaluation_is_point_in_time(evaluation, evaluation.evaluated_at)
    assert not _evaluation_is_point_in_time(
        evaluation, evaluation.ended_at - timedelta(microseconds=1)
    )
    assert not _evaluation_is_point_in_time(
        evaluation, NOW - timedelta(seconds=2)
    )
