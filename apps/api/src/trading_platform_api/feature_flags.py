from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

ENABLE_LIVE_TRADING_VARIABLE = "ENABLE_LIVE_TRADING"
ENABLE_AUTO_EXECUTION_VARIABLE = "ENABLE_AUTO_EXECUTION"
ENABLE_ADAPTIVE_STRATEGIES_VARIABLE = "ENABLE_ADAPTIVE_STRATEGIES"
ENABLE_LEARNING_VARIABLE = "ENABLE_LEARNING"
ENABLE_EXPERIMENTS_VARIABLE = "ENABLE_EXPERIMENTS"


class FeatureFlagsError(ValueError):
    """Raised when feature flags cannot be parsed safely."""


@dataclass(frozen=True, slots=True)
class FeatureFlags:
    enable_live_trading: bool = False
    enable_auto_execution: bool = False
    enable_adaptive_strategies: bool = False
    enable_learning: bool = False
    enable_experiments: bool = False


def _parse_strict_bool(*, variable_name: str, raw_value: str | None) -> bool:
    if raw_value is None:
        return False
    if raw_value == "":
        raise FeatureFlagsError(f"{variable_name} must not be blank.")
    if raw_value.strip() == "":
        raise FeatureFlagsError(f"{variable_name} must not be whitespace-only.")
    if raw_value != raw_value.strip():
        raise FeatureFlagsError(
            f"{variable_name} must match canonical values exactly with no surrounding whitespace."
        )
    if raw_value == "true":
        return True
    if raw_value == "false":
        return False
    raise FeatureFlagsError(f"{variable_name} must be one of: true, false.")


def load_feature_flags(environment_mapping: Mapping[str, str] | None = None) -> FeatureFlags:
    mapping = os.environ if environment_mapping is None else environment_mapping
    return FeatureFlags(
        enable_live_trading=_parse_strict_bool(
            variable_name=ENABLE_LIVE_TRADING_VARIABLE,
            raw_value=mapping.get(ENABLE_LIVE_TRADING_VARIABLE),
        ),
        enable_auto_execution=_parse_strict_bool(
            variable_name=ENABLE_AUTO_EXECUTION_VARIABLE,
            raw_value=mapping.get(ENABLE_AUTO_EXECUTION_VARIABLE),
        ),
        enable_adaptive_strategies=_parse_strict_bool(
            variable_name=ENABLE_ADAPTIVE_STRATEGIES_VARIABLE,
            raw_value=mapping.get(ENABLE_ADAPTIVE_STRATEGIES_VARIABLE),
        ),
        enable_learning=_parse_strict_bool(
            variable_name=ENABLE_LEARNING_VARIABLE,
            raw_value=mapping.get(ENABLE_LEARNING_VARIABLE),
        ),
        enable_experiments=_parse_strict_bool(
            variable_name=ENABLE_EXPERIMENTS_VARIABLE,
            raw_value=mapping.get(ENABLE_EXPERIMENTS_VARIABLE),
        ),
    )
