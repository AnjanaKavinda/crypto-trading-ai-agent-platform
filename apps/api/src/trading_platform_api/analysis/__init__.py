from trading_platform_api.analysis.contracts import *  # noqa: F403
from trading_platform_api.analysis.contracts import __all__ as _contract_exports
from trading_platform_api.analysis.indicator_registry import (
    SPOT_RESEARCH_INDICATORS,
    IndicatorCategory,
    IndicatorMetadata,
    IndicatorMetadataError,
    IndicatorPhase,
    IndicatorRegistry,
    IndicatorTiming,
    ParameterMetadata,
)
from trading_platform_api.analysis.moving_averages import (
    MovingAverageError,
    MovingAverageKind,
    MovingAveragePoint,
    MovingAverageSeries,
    calculate_moving_average,
)

__all__ = [
    *_contract_exports,
    "SPOT_RESEARCH_INDICATORS",
    "IndicatorCategory",
    "IndicatorMetadata",
    "IndicatorMetadataError",
    "IndicatorPhase",
    "IndicatorRegistry",
    "IndicatorTiming",
    "ParameterMetadata",
    "MovingAverageError",
    "MovingAverageKind",
    "MovingAveragePoint",
    "MovingAverageSeries",
    "calculate_moving_average",
]
