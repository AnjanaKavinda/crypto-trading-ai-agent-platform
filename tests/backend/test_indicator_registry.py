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
    assert "maximum_climactic_close_fraction" in wyckoff.output_schema
    assert "maximum_output_records" in {item.name for item in wyckoff.parameters}
    with pytest.raises(IndicatorMetadataError, match="exact"):
        SPOT_RESEARCH_INDICATORS.get("spot-market-structure", "2")
    with pytest.raises(IndicatorMetadataError, match="exact"):
        SPOT_RESEARCH_INDICATORS.get("spot-smart-money-concepts", "2")
    with pytest.raises(IndicatorMetadataError, match="exact"):
        SPOT_RESEARCH_INDICATORS.get("spot-wyckoff-analysis", "2")
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
