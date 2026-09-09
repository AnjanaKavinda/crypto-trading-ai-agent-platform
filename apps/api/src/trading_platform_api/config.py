from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Mapping

ENVIRONMENT_VARIABLE = "TRADING_PLATFORM_ENVIRONMENT"
MODE_VARIABLE = "TRADING_PLATFORM_MODE"


class AppSettingsError(ValueError):
    """Raised when application settings cannot be parsed safely."""


class DeploymentEnvironment(str, Enum):
    DEV = "dev"
    TEST = "test"
    STAGING = "staging"
    PROD = "prod"


class OperatingMode(str, Enum):
    RESEARCH = "research"
    BACKTEST = "backtest"
    PAPER = "paper"
    SHADOW = "shadow"
    TESTNET = "testnet"
    LIVE_SUPERVISED = "live-supervised"


@dataclass(frozen=True, slots=True)
class AppSettings:
    environment: DeploymentEnvironment
    mode: OperatingMode


def _parse_enum_value(
    *,
    variable_name: str,
    raw_value: str | None,
    default_value: str,
    enum_type: type[DeploymentEnvironment] | type[OperatingMode],
) -> DeploymentEnvironment | OperatingMode:
    if raw_value is None:
        value = default_value
    else:
        if raw_value == "":
            raise AppSettingsError(f"{variable_name} must not be blank.")
        if raw_value.strip() == "":
            raise AppSettingsError(f"{variable_name} must not be whitespace-only.")
        if raw_value != raw_value.strip():
            raise AppSettingsError(
                f"{variable_name} must match canonical values exactly with no surrounding whitespace."
            )
        value = raw_value

    try:
        return enum_type(value)
    except ValueError as exc:
        allowed_values = ", ".join(member.value for member in enum_type)
        raise AppSettingsError(
            f"{variable_name} must be one of: {allowed_values}. Received: {value!r}."
        ) from exc


def load_app_settings(environment_mapping: Mapping[str, str] | None = None) -> AppSettings:
    mapping = os.environ if environment_mapping is None else environment_mapping
    environment = _parse_enum_value(
        variable_name=ENVIRONMENT_VARIABLE,
        raw_value=mapping.get(ENVIRONMENT_VARIABLE),
        default_value=DeploymentEnvironment.DEV.value,
        enum_type=DeploymentEnvironment,
    )
    mode = _parse_enum_value(
        variable_name=MODE_VARIABLE,
        raw_value=mapping.get(MODE_VARIABLE),
        default_value=OperatingMode.RESEARCH.value,
        enum_type=OperatingMode,
    )
    return AppSettings(environment=environment, mode=mode)
