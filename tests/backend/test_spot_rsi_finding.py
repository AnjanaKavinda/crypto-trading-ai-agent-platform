from decimal import Decimal

import pytest
from test_moving_averages import evidence
from trading_platform_api.analysis.contracts import (
    AnalyticalDirection,
    EvidenceRelation,
)
from trading_platform_api.analysis.momentum import calculate_rsi
from trading_platform_api.orchestration.spot_analysis_fanout import (
    SpotAnalysisTaskReason,
)
from trading_platform_api.orchestration.spot_rsi_finding import (
    _direction_and_relation,
    adapt_rsi14_finding,
)


@pytest.mark.parametrize(
    ("value", "regime", "direction", "relation"),
    [
        (
            "50.01",
            AnalyticalDirection.BULLISH,
            AnalyticalDirection.BULLISH,
            EvidenceRelation.SUPPORTING,
        ),
        (
            "49.99",
            AnalyticalDirection.BULLISH,
            AnalyticalDirection.BEARISH,
            EvidenceRelation.CONTRADICTING,
        ),
        (
            "50",
            AnalyticalDirection.BEARISH,
            AnalyticalDirection.NEUTRAL,
            EvidenceRelation.NEUTRAL,
        ),
        (
            "50.01",
            AnalyticalDirection.MIXED,
            AnalyticalDirection.BULLISH,
            EvidenceRelation.NEUTRAL,
        ),
        (
            "49.99",
            AnalyticalDirection.UNKNOWN,
            AnalyticalDirection.BEARISH,
            EvidenceRelation.NEUTRAL,
        ),
    ],
)
def test_rsi_direction_and_relation_follow_approved_threshold(
    value: str,
    regime: AnalyticalDirection,
    direction: AnalyticalDirection,
    relation: EvidenceRelation,
) -> None:
    assert _direction_and_relation(Decimal(value), regime) == (direction, relation)


def test_rsi_adapter_reports_warmup_without_creating_a_finding() -> None:
    snapshot, observations, quality = evidence(("10", "11", "12"))
    series = calculate_rsi(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        period=14,
    )

    outcome = adapt_rsi14_finding(
        series=series,
        evidence_ids=(),
        evidence_by_id={},
        manifest=None,  # type: ignore[arg-type]
        resolved_binding=None,  # type: ignore[arg-type]
        now=series.as_of,
    )

    assert outcome.reason_code is SpotAnalysisTaskReason.INSUFFICIENT_WARMUP


def test_rsi_adapter_returns_unavailable_when_c008_evidence_is_missing() -> None:
    snapshot, observations, quality = evidence(
        tuple(str(10 + index % 2) for index in range(20))
    )
    series = calculate_rsi(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        period=14,
    )

    outcome = adapt_rsi14_finding(
        series=series,
        evidence_ids=(),
        evidence_by_id={},
        manifest=None,  # type: ignore[arg-type]
        resolved_binding=None,  # type: ignore[arg-type]
        now=series.as_of,
    )

    assert outcome.reason_code is SpotAnalysisTaskReason.INPUT_UNAVAILABLE
