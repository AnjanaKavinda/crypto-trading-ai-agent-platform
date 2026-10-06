import json
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal

import pytest
from test_moving_averages import evidence
from trading_platform_api.analysis import (
    SPOT_WYCKOFF_METHOD_VERSION,
    SpotWyckoffError,
    SpotWyckoffPolicy,
    calculate_spot_wyckoff,
)
from trading_platform_api.market_data.contracts import DataQualityStatus


def _policy(**changes: object) -> SpotWyckoffPolicy:
    values: dict[str, object] = {
        "policy_id": "wyckoff-test",
        "version": "test-v1",
        "range_window": 2,
        "volume_window": 2,
        "breakout_confirmation": 2,
        "maximum_range_fraction": Decimal("0.5"),
        "phase_close_fraction": Decimal("0.25"),
        "minimum_phase_volume_ratio": Decimal("1"),
        "event_volume_ratio": Decimal("1.5"),
        "high_volume_ratio": Decimal("1.5"),
        "low_volume_ratio": Decimal("0.5"),
        "wide_spread_ratio": Decimal("1.5"),
        "narrow_spread_ratio": Decimal("1"),
        "absorption_volume_ratio": Decimal("1.5"),
        "climactic_volume_ratio": Decimal("1.5"),
        "maximum_climactic_close_fraction": Decimal("0.2"),
        "maximum_output_records": 1000,
    }
    values.update(changes)
    return SpotWyckoffPolicy(**values)  # type: ignore[arg-type]


def _input(
    bars: tuple[tuple[str, str, str, str, str], ...],
    *,
    quality_status: DataQualityStatus = DataQualityStatus.VALID,
):
    snapshot, originals, quality = evidence(tuple("10" for _ in bars))
    observations = tuple(
        replace(
            candle,
            metrics=tuple(
                replace(
                    metric,
                    value=Decimal(
                        dict(
                            zip(
                                ("open", "high", "low", "close", "volume"),
                                bar,
                                strict=True,
                            )
                        )[metric.metric_name]
                    ),
                )
                if metric.metric_name
                in {"open", "high", "low", "close", "volume"}
                else metric
                for metric in candle.metrics
            ),
        )
        for candle, bar in zip(originals, bars, strict=True)
    )
    if quality_status is not DataQualityStatus.VALID:
        quality = replace(quality, status=quality_status)
    return snapshot, observations, quality


def _bars(
    count: int = 8,
    *,
    opening: str = "10",
    high: str = "12",
    low: str = "8",
    close: str = "10",
    volume: str = "10",
) -> tuple[tuple[str, str, str, str, str], ...]:
    return ((opening, high, low, close, volume),) * count


def _calculate(bars, *, policy: SpotWyckoffPolicy | None = None):
    snapshot, observations, quality = _input(bars)
    result = calculate_spot_wyckoff(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        timeframe="1m",
        policy=policy or _policy(),
    )
    return snapshot, observations, quality, result


def _phase(result) -> str:
    return next(item.label for item in result.observations if item.category == "phase")


@pytest.mark.parametrize(
    ("bars", "expected"),
    (
        (_bars(close="8.5", volume="20"), "accumulation-hypothesis"),
        (_bars(close="11.5", volume="20"), "distribution-hypothesis"),
        (_bars(close="10"), "trading-range"),
        (
            _bars()[:-2]
            + (("11.5", "13", "11", "12", "10"),) * 2,
            "markup",
        ),
        (
            _bars()[:-2]
            + (("8.5", "9", "7", "8", "10"),) * 2,
            "markdown",
        ),
    ),
)
def test_deterministic_phase_hypotheses_and_as_of(
    bars: tuple[tuple[str, str, str, str, str], ...], expected: str
) -> None:
    snapshot, observations, quality, result = _calculate(bars)
    assert _phase(result) == expected
    assert result.method_version == SPOT_WYCKOFF_METHOD_VERSION
    assert result.assessment.status.value == "available"
    assert result.assessment.analytical_confidence == 0
    assert result.as_of == snapshot.as_of
    assert result.input_market_data_ids == tuple(
        candle.market_data_id for candle in observations
    )
    assert all(item.as_of <= snapshot.as_of for item in result.observations)
    assert all(item.quality_status is DataQualityStatus.VALID for item in result.evidence)
    assert all(item.data_quality_report_id == quality.report_id for item in result.evidence)


def test_spring_upthrust_strict_boundaries_and_confirmed_events() -> None:
    base = _bars()
    spring_bars = base[:-1] + (("9", "11", "7", "9.5", "20"),)
    _, _, _, spring = _calculate(spring_bars)
    assert any(item.label == "spring-candidate" for item in spring.observations)

    equal_boundary = base[:-1] + (("9", "11", "8", "9.5", "20"),)
    _, _, _, equal = _calculate(equal_boundary)
    assert not any(item.label == "spring-candidate" for item in equal.observations)

    upthrust_bars = base[:-1] + (("10", "13", "9", "10.5", "20"),)
    _, _, _, upthrust = _calculate(upthrust_bars)
    assert any(item.label == "upthrust-candidate" for item in upthrust.observations)

    breakout = _bars()[:4] + (("11.5", "13", "11.2", "12", "20"),) * 2
    _, _, _, strength = _calculate(breakout)
    assert any(item.label == "sign-of-strength-candidate" for item in strength.observations)
    after_strength = breakout + (("12", "13", "11.5", "12.5", "10"),)
    _, _, _, lps = _calculate(after_strength)
    assert any(item.label == "last-point-of-support-candidate" for item in lps.observations)

    breakdown = _bars()[:4] + (("8.5", "9", "7", "8", "20"),) * 2
    _, _, _, weakness = _calculate(breakdown)
    assert any(item.label == "sign-of-weakness-candidate" for item in weakness.observations)
    after_weakness = breakdown + (("8", "8.5", "7", "7.5", "10"),)
    _, _, _, lpsy = _calculate(after_weakness)
    assert any(item.label == "last-point-of-supply-candidate" for item in lpsy.observations)


def test_measurement_evidence_is_exact_stable_and_non_repainting() -> None:
    bars = _bars()[:4] + (("11.5", "13", "11.2", "12", "20"),) * 2
    snapshot, observations, _, first = _calculate(bars)
    _, _, _, second = _calculate(bars)
    assert first == second
    assert len(first.evidence) == len(first.observations)
    evidence_by_id = {item.evidence_id: item for item in first.evidence}
    for output in first.observations:
        item = evidence_by_id[output.evidence_id]
        assert item.contract_id == "C-008"
        assert f"C-002:snapshot:{snapshot.snapshot_id}" in item.feature_ids
        assert {
            f"C-001:market-data:{source_id}"
            for source_id in output.source_market_data_ids
        }.issubset(item.feature_ids)
        assert all(source_id in snapshot.source_record_ids for source_id in item.source_record_ids)
        assert output.source_market_data_ids
        assert output.invalidation_condition
        assert output.alternative_explanation
    assert all(
        set(finding.evidence_ids).issubset(set(first.assessment.evidence_ids))
        for finding in first.assessment.findings
    )
    assert all(
        candle_id in tuple(item.market_data_id for item in observations)
        for record in first.observations
        for candle_id in record.source_market_data_ids
    )
    extended = bars + (("12", "14", "11.5", "13", "10"),)
    _, _, _, extended_result = _calculate(extended)
    prefix = bars
    _, _, _, prefix_result = _calculate(prefix)
    prefix_event = next(
        item
        for item in prefix_result.observations
        if item.label == "sign-of-strength-candidate"
    )
    later_event = next(
        item
        for item in extended_result.observations
        if item.label == "sign-of-strength-candidate"
    )
    assert prefix_event.value == later_event.value
    assert prefix_event.source_market_data_ids == later_event.source_market_data_ids


def test_effort_spread_absorption_climax_no_demand_supply_and_zero_baseline() -> None:
    bars = _bars()[:-3] + (
        ("10", "18", "8", "8.1", "30"),
        ("10", "10.5", "9.5", "10.1", "20"),
        ("10", "10.5", "9.5", "9.9", "1"),
        ("9.9", "10.5", "9.5", "10.1", "1"),
    )
    _, _, _, result = _calculate(bars)
    labels = {item.label for item in result.observations}
    assert "high-effort-low-result-candidate" in labels
    assert "potential-absorption-pattern" in labels
    assert "climactic-action-candidate" in labels
    assert "no-demand" in labels
    assert "no-supply" in labels

    zero_volume = _bars(volume="0")
    _, _, _, zero_result = _calculate(zero_volume)
    measurements = [
        json.loads(item.value)
        for item in zero_result.observations
        if item.category == "volume-spread"
    ]
    assert measurements[-1]["volume_ratio"] == "unavailable:zero-prior-baseline"


def test_preliminary_support_and_supply_require_thresholds() -> None:
    support = _bars()[:-1] + (("10", "11", "7", "8", "20"),)
    _, _, _, support_result = _calculate(support)
    assert any(
        item.label == "preliminary-support-candidate"
        for item in support_result.observations
    )
    supply = _bars()[:-1] + (("10", "13", "9", "12", "20"),)
    _, _, _, supply_result = _calculate(supply)
    assert any(
        item.label == "preliminary-supply-candidate"
        for item in supply_result.observations
    )


def test_validation_fails_closed_for_quality_policy_warmup_volume_and_registry() -> None:
    snapshot, observations, quality = _input(
        _bars(), quality_status=DataQualityStatus.STALE
    )
    with pytest.raises(SpotWyckoffError):
        calculate_spot_wyckoff(
            snapshot=snapshot,
            observations=observations,
            quality=quality,
            timeframe="1m",
            policy=_policy(),
        )

    snapshot, observations, quality = _input(_bars()[:4])
    with pytest.raises(SpotWyckoffError, match="warm-up"):
        calculate_spot_wyckoff(
            snapshot=snapshot,
            observations=observations,
            quality=quality,
            timeframe="1m",
            policy=_policy(),
        )
    with pytest.raises(SpotWyckoffError, match="version"):
        calculate_spot_wyckoff(
            snapshot=snapshot,
            observations=observations,
            quality=quality,
            timeframe="1m",
            policy=_policy(),
            metadata_version="2",
        )
    with pytest.raises(SpotWyckoffError, match="Unsupported"):
        calculate_spot_wyckoff(
            snapshot=snapshot,
            observations=observations,
            quality=quality,
            timeframe="2m",
            policy=_policy(),
        )
    with pytest.raises(SpotWyckoffError):
        _policy(phase_close_fraction=Decimal("0.5"))
    with pytest.raises(SpotWyckoffError):
        _policy(maximum_output_records=0)
    with pytest.raises(FrozenInstanceError):
        _policy().version = "changed"

    snapshot, observations, quality = _input(_bars())
    missing_volume = tuple(
        replace(
            candle,
            metrics=tuple(
                metric for metric in candle.metrics if metric.metric_name != "volume"
            ),
        )
        for candle in observations
    )
    with pytest.raises(SpotWyckoffError):
        calculate_spot_wyckoff(
            snapshot=snapshot,
            observations=missing_volume,
            quality=quality,
            timeframe="1m",
            policy=_policy(),
        )


def test_output_bound_and_candle_order_are_rejected() -> None:
    snapshot, observations, quality = _input(_bars())
    with pytest.raises(SpotWyckoffError, match="output"):
        calculate_spot_wyckoff(
            snapshot=snapshot,
            observations=observations,
            quality=quality,
            timeframe="1m",
            policy=_policy(maximum_output_records=1),
        )
    with pytest.raises(SpotWyckoffError):
        calculate_spot_wyckoff(
            snapshot=snapshot,
            observations=(observations[1], observations[0], *observations[2:]),
            quality=quality,
            timeframe="1m",
            policy=_policy(),
        )
