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
        "sma",
        "ema",
        "wma",
        "ema-20",
        "ema-50",
        "atr-14",
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
    for name in ("ema-20", "ema-50"):
        assert SPOT_RESEARCH_INDICATORS.get(name, "1").phase is IndicatorPhase.PLANNED
        assert SPOT_RESEARCH_INDICATORS.get(name, "2").phase is IndicatorPhase.VALIDATED
    for name in ("sma", "ema", "wma"):
        assert SPOT_RESEARCH_INDICATORS.get(name, "1").phase is IndicatorPhase.VALIDATED


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
