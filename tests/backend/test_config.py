import pytest

from trading_platform_api.config import (
    AppSettingsError,
    DeploymentEnvironment,
    OperatingMode,
    load_app_settings,
)


def test_load_app_settings_uses_safe_defaults_when_variables_are_absent() -> None:
    settings = load_app_settings({})

    assert settings.environment is DeploymentEnvironment.DEV
    assert settings.mode is OperatingMode.RESEARCH


@pytest.mark.parametrize(
    "environment_value",
    [member.value for member in DeploymentEnvironment],
)
def test_load_app_settings_accepts_every_canonical_environment_value(
    environment_value: str,
) -> None:
    settings = load_app_settings({"TRADING_PLATFORM_ENVIRONMENT": environment_value})

    assert settings.environment.value == environment_value


@pytest.mark.parametrize(
    "mode_value",
    [member.value for member in OperatingMode],
)
def test_load_app_settings_accepts_every_canonical_mode_value(mode_value: str) -> None:
    settings = load_app_settings({"TRADING_PLATFORM_MODE": mode_value})

    assert settings.mode.value == mode_value


def test_environment_and_mode_are_parsed_independently() -> None:
    settings = load_app_settings(
        {
            "TRADING_PLATFORM_ENVIRONMENT": DeploymentEnvironment.PROD.value,
            "TRADING_PLATFORM_MODE": OperatingMode.BACKTEST.value,
        }
    )

    assert settings.environment is DeploymentEnvironment.PROD
    assert settings.mode is OperatingMode.BACKTEST


@pytest.mark.parametrize("blank_value", ["", " ", "\t", "\n", "  \t"])
def test_blank_or_whitespace_values_fail_closed(blank_value: str) -> None:
    with pytest.raises(AppSettingsError):
        load_app_settings({"TRADING_PLATFORM_ENVIRONMENT": blank_value})

    with pytest.raises(AppSettingsError):
        load_app_settings({"TRADING_PLATFORM_MODE": blank_value})


def test_unknown_environment_value_fails_closed() -> None:
    with pytest.raises(AppSettingsError):
        load_app_settings({"TRADING_PLATFORM_ENVIRONMENT": "development"})


def test_unknown_operating_mode_value_fails_closed() -> None:
    with pytest.raises(AppSettingsError):
        load_app_settings({"TRADING_PLATFORM_MODE": "live"})
