from dataclasses import replace

import pytest
from trading_platform_api.analysis.indicator_registry import (
    SPOT_RESEARCH_INDICATORS,
    IndicatorCategory,
    IndicatorMetadataError,
    IndicatorPhase,
    IndicatorRegistry,
    ParameterMetadata,
)


def test_spot_catalog_is_explicitly_planned_and_price_correlated() -> None:
    entries = SPOT_RESEARCH_INDICATORS.list_entries()
    assert {item.indicator_id for item in entries} == {
        "cci",
        "macd",
        "rsi",
        "sma",
        "ema",
        "stochastic",
        "wma",
        "ema-20",
        "ema-50",
        "atr-14",
        "bollinger-bands",
        "bollinger-bandwidth",
        "realized-volatility",
        "vwap",
        "volume-profile",
        "volume-confirmation",
        "price-action-support-resistance",
        "spot-market-structure",
        "spot-smart-money-concepts",
        "spot-wyckoff-analysis",
        "spot-fibonacci",
    }
    for item in entries:
        assert item.output_nullable
        assert not item.evidence_independent
        assert item.evidence_dependencies
        assert "C-003:quality" in item.inputs
        assert item.failure_modes
        assert "5m" in item.timeframes
    assert SPOT_RESEARCH_INDICATORS.get("atr-14", "1").category is (
        IndicatorCategory.VOLATILITY_RISK
    )
    assert SPOT_RESEARCH_INDICATORS.get("atr-14", "1").minimum_warmup_candles == 15
    assert SPOT_RESEARCH_INDICATORS.get("atr-14", "1").phase is IndicatorPhase.PLANNED
    assert SPOT_RESEARCH_INDICATORS.get("atr-14", "2").phase is IndicatorPhase.VALIDATED
    for name in ("bollinger-bands", "bollinger-bandwidth", "realized-volatility"):
        assert SPOT_RESEARCH_INDICATORS.get(name, "1").phase is IndicatorPhase.VALIDATED
    for name in ("vwap", "volume-profile"):
        metadata = SPOT_RESEARCH_INDICATORS.get(name, "1")
        assert metadata.phase is IndicatorPhase.VALIDATED
        assert metadata.category is IndicatorCategory.VOLUME_STRUCTURE
        assert not metadata.evidence_independent
        assert metadata.evidence_dependencies
    volume_confirmation = SPOT_RESEARCH_INDICATORS.get("volume-confirmation", "1")
    assert volume_confirmation.phase is IndicatorPhase.VALIDATED
    assert volume_confirmation.category is IndicatorCategory.VOLUME_CONFIRMATION
    assert (
        volume_confirmation.calculation_version
        == "trailing-prior-volume-mean-explicit-pivot-comparison-v1"
    )
    assert not volume_confirmation.evidence_independent
    assert [
        (item.default, item.minimum, item.maximum)
        for item in volume_confirmation.parameters
    ] == [(20, 2, 500)]
    profile = SPOT_RESEARCH_INDICATORS.get("volume-profile", "1")
    assert [
        (item.default, item.minimum, item.maximum) for item in profile.parameters
    ] == [
        (24, 1, 500),
        (70, 50, 100),
    ]
    market_structure = SPOT_RESEARCH_INDICATORS.get("spot-market-structure", "1")
    assert market_structure.phase is IndicatorPhase.VALIDATED
    assert market_structure.category is IndicatorCategory.MARKET_STRUCTURE
    assert market_structure.calculation_version == "spot-market-structure-v1"
    assert market_structure.minimum_warmup_candles == 7
    assert market_structure.output_nullable
    assert not market_structure.evidence_independent
    assert market_structure.evidence_dependencies
    assert "C-003:quality" in market_structure.inputs
    assert market_structure.failure_modes
    smc = SPOT_RESEARCH_INDICATORS.get("spot-smart-money-concepts", "1")
    assert smc.phase is IndicatorPhase.VALIDATED
    assert smc.category is IndicatorCategory.SMART_MONEY_CONCEPTS
    assert smc.calculation_version == "spot-smc-v1"
    assert smc.minimum_warmup_candles == 3
    assert smc.output_nullable
    assert not smc.evidence_independent
    assert smc.evidence_dependencies
    assert "C-003:quality" in smc.inputs
    assert smc.failure_modes
    wyckoff = SPOT_RESEARCH_INDICATORS.get("spot-wyckoff-analysis", "1")
    assert wyckoff.phase is IndicatorPhase.VALIDATED
    assert wyckoff.calculation_version == "spot-wyckoff-v1"
    assert wyckoff.category is IndicatorCategory.WYCKOFF
    assert wyckoff.minimum_warmup_candles == 3
    assert wyckoff.output_nullable
    assert not wyckoff.evidence_independent
    assert wyckoff.evidence_dependencies == ("spot-ohlcv-price", "spot-ohlcv-volume")
    threshold_fields = {
        "maximum_range_fraction",
        "phase_close_fraction",
        "minimum_phase_volume_ratio",
        "event_volume_ratio",
        "high_volume_ratio",
        "low_volume_ratio",
        "wide_spread_ratio",
        "narrow_spread_ratio",
        "absorption_volume_ratio",
        "climactic_volume_ratio",
        "maximum_climactic_close_fraction",
    }
    assert all(field in wyckoff.purpose for field in threshold_fields)
    assert "maximum-output-records" in {item.name for item in wyckoff.parameters}
    fibonacci = SPOT_RESEARCH_INDICATORS.get("spot-fibonacci", "1")
    assert fibonacci.phase is IndicatorPhase.VALIDATED
    assert fibonacci.category is IndicatorCategory.FIBONACCI
    assert fibonacci.calculation_version == "spot-fibonacci-v1"
    assert fibonacci.minimum_warmup_candles == 3
    assert fibonacci.output_nullable
    assert not fibonacci.evidence_independent
    assert fibonacci.evidence_dependencies == (
        "spot-ohlcv-price",
        "confirmed-price-action-pivots",
    )
    assert "confluence_tolerance" in fibonacci.output_schema
    assert "invalidation_buffer" in fibonacci.output_schema
    assert {item.name for item in fibonacci.parameters} == {
        "maximum-output-records",
        "invalidation-consecutive-close-count",
    }
    with pytest.raises(IndicatorMetadataError, match="exact"):
        SPOT_RESEARCH_INDICATORS.get("spot-market-structure", "2")
    with pytest.raises(IndicatorMetadataError, match="exact"):
        SPOT_RESEARCH_INDICATORS.get("spot-smart-money-concepts", "2")
    with pytest.raises(IndicatorMetadataError, match="exact"):
        SPOT_RESEARCH_INDICATORS.get("spot-wyckoff-analysis", "2")
    with pytest.raises(IndicatorMetadataError, match="exact"):
        SPOT_RESEARCH_INDICATORS.get("spot-fibonacci", "2")
    for name in ("ema-20", "ema-50"):
        assert SPOT_RESEARCH_INDICATORS.get(name, "1").phase is IndicatorPhase.PLANNED
        assert SPOT_RESEARCH_INDICATORS.get(name, "2").phase is IndicatorPhase.VALIDATED
    for name in ("sma", "ema", "wma"):
        assert SPOT_RESEARCH_INDICATORS.get(name, "1").phase is IndicatorPhase.VALIDATED
    for name in ("rsi", "macd", "stochastic", "cci"):
        metadata = SPOT_RESEARCH_INDICATORS.get(name, "1")
        assert metadata.phase is IndicatorPhase.VALIDATED
        assert metadata.category is IndicatorCategory.MOMENTUM


def test_exact_version_lookup_does_not_silently_pick_a_newer_definition() -> None:
    original = SPOT_RESEARCH_INDICATORS.get("ema-20", "1")
    new = replace(original, metadata_version="2", purpose="A future reviewed purpose.")
    registry = IndicatorRegistry((new, original))
    assert registry.get("ema-20", "1") is original
    assert registry.get("ema-20", "2") is new
    assert registry.list_entries() == (original, new)
    with pytest.raises(IndicatorMetadataError, match="exact"):
        registry.get("ema-20", "3")
    with pytest.raises(IndicatorMetadataError, match="Duplicate"):
        IndicatorRegistry((original, original))


def test_fibonacci_registry_covers_timeframes_policy_bounds_and_failure_modes() -> None:
    fibonacci = SPOT_RESEARCH_INDICATORS.get("spot-fibonacci", "1")
    assert fibonacci.timeframes == ("1m", "5m", "15m", "1h", "4h", "1d")
    assert fibonacci.minimum_warmup_candles == 3
    assert fibonacci.output_nullable
    assert fibonacci.output_unit == "input-price-unit"
    assert len(fibonacci.output_schema) <= 512
    assert [
        (item.name, item.unit, item.default, item.minimum, item.maximum)
        for item in fibonacci.parameters
    ] == [
        ("maximum-output-records", "records", 32, 1, 10000),
        ("invalidation-consecutive-close-count", "candles", 500, 1, 500),
    ]
    assert (
        "Retracement ratios: {0.236,0.382,0.500,0.618,0.786,1.000}" in fibonacci.purpose
    )
    assert "extensions: {1.272,1.618,2.618}" in fibonacci.purpose
    for bound in (
        "policy_id/version <=128 chars",
        "scale {internal,external}",
        "distinct UUID anchor IDs",
        "nonempty ratio subsets (bounds in purpose)",
        "positive finite Decimal confluence_tolerance/invalidation_buffer",
        "<=64 digits, abs exponent/adjusted <=128",
        "close count [1,500]",
        "output records [1,10000]",
    ):
        assert bound in fibonacci.output_schema
    assert set(fibonacci.failure_modes) == {
        "invalid-quality-or-provenance",
        "stale-or-gapped-market",
        "non-spot-input",
        "mismatched-market-structure-or-evidence",
        "unconfirmed-or-invalid-anchor-selection",
        "unsupported-or-unregistered-method-version",
        "invalid-caller-policy",
        "decimal-precision-or-exponent-limit",
        "expired-point-in-time-evidence",
        "bounded-evidence-output-exceeded",
    }
    assert fibonacci.phase is IndicatorPhase.VALIDATED
    assert not fibonacci.evidence_independent
    assert fibonacci.evidence_dependencies == (
        "spot-ohlcv-price",
        "confirmed-price-action-pivots",
    )


def test_invalid_metadata_cannot_claim_available_analysis_or_independence() -> None:
    original = SPOT_RESEARCH_INDICATORS.get("ema-20", "1")
    invalid = (
        {"phase": IndicatorPhase.VALIDATED},
        {"indicator_id": "EMA 20"},
        {"timeframes": ("5m", "2m")},
        {"inputs": ("C-001.close", "C-001.close")},
        {"evidence_independent": True},
        {"evidence_dependencies": ()},
        {"parameters": (original.parameters[0], original.parameters[0])},
        {"metadata_version": ""},
        {"minimum_warmup_candles": 0},
    )
    for changes in invalid:
        with pytest.raises(IndicatorMetadataError):
            replace(original, **changes)
    with pytest.raises(IndicatorMetadataError):
        ParameterMetadata("period", "candles", 20, 21, 500)
    with pytest.raises(IndicatorMetadataError):
        ParameterMetadata("period", "candles", True, 1, 500)
