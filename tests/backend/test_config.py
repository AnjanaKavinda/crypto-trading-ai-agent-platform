import pytest

from trading_platform_api.config import (
    AppSettings,
    AppSettingsError,
    DeploymentEnvironment,
    OperatingMode,
    load_app_settings,
)
from trading_platform_api.main import create_app


def test_load_app_settings_uses_safe_defaults_when_variables_are_absent() -> None:
    settings = load_app_settings({})

    assert settings.environment is DeploymentEnvironment.DEV
    assert settings.mode is OperatingMode.RESEARCH
    assert settings.feature_flags.enable_live_trading is False
    assert settings.feature_flags.enable_auto_execution is False
    assert settings.feature_flags.enable_adaptive_strategies is False
    assert settings.feature_flags.enable_learning is False
    assert settings.feature_flags.enable_experiments is False


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


def test_invalid_explicit_feature_flag_prevents_settings_construction() -> None:
    with pytest.raises(AppSettingsError) as exc_info:
        load_app_settings(
            {"ENABLE_AUTO_EXECUTION": "top-secret-token", "UNRELATED_SECRET": "top-secret-token"}
        )

    error_message = str(exc_info.value)
    assert "ENABLE_AUTO_EXECUTION" in error_message
    assert "UNRELATED_SECRET" not in error_message
    assert "top-secret-token" not in error_message


def test_load_app_settings_uses_same_mapping_for_mode_environment_and_flags() -> None:
    settings = load_app_settings(
        {
            "TRADING_PLATFORM_ENVIRONMENT": DeploymentEnvironment.STAGING.value,
            "TRADING_PLATFORM_MODE": OperatingMode.PAPER.value,
            "ENABLE_LIVE_TRADING": "true",
            "ENABLE_AUTO_EXECUTION": "false",
            "ENABLE_ADAPTIVE_STRATEGIES": "true",
            "ENABLE_LEARNING": "false",
            "ENABLE_EXPERIMENTS": "true",
        }
    )

    assert settings.environment is DeploymentEnvironment.STAGING
    assert settings.mode is OperatingMode.PAPER
    assert settings.feature_flags.enable_live_trading is True
    assert settings.feature_flags.enable_auto_execution is False
    assert settings.feature_flags.enable_adaptive_strategies is True
    assert settings.feature_flags.enable_learning is False
    assert settings.feature_flags.enable_experiments is True


def test_direct_app_settings_construction_remains_backward_compatible() -> None:
    settings = AppSettings(
        environment=DeploymentEnvironment.PROD,
        mode=OperatingMode.LIVE_SUPERVISED,
    )

    assert settings.environment is DeploymentEnvironment.PROD
    assert settings.mode is OperatingMode.LIVE_SUPERVISED
    assert settings.feature_flags.enable_live_trading is False
    assert settings.feature_flags.enable_auto_execution is False
    assert settings.feature_flags.enable_adaptive_strategies is False
    assert settings.feature_flags.enable_learning is False
    assert settings.feature_flags.enable_experiments is False


def test_enabling_flag_changes_only_typed_configuration_and_not_routes() -> None:
    settings = load_app_settings({"ENABLE_LIVE_TRADING": "true"})
    created_app = create_app(settings=settings)
    route_paths = {route.path for route in created_app.routes}

    assert created_app.state.settings.feature_flags.enable_live_trading is True
    assert created_app.state.settings.mode is OperatingMode.RESEARCH
    assert not any("trade" in route_path or "execute" in route_path for route_path in route_paths)
