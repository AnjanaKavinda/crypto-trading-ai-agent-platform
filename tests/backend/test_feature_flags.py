from dataclasses import FrozenInstanceError

import pytest

from trading_platform_api.config import AppSettings, DeploymentEnvironment, OperatingMode
from trading_platform_api.feature_flags import FeatureFlags, FeatureFlagsError, load_feature_flags


def test_direct_feature_flags_construction_uses_all_false_defaults() -> None:
    assert FeatureFlags() == FeatureFlags(
        enable_live_trading=False,
        enable_auto_execution=False,
        enable_adaptive_strategies=False,
        enable_learning=False,
        enable_experiments=False,
    )


def test_empty_mapping_loads_all_feature_flags_as_false() -> None:
    assert load_feature_flags({}) == FeatureFlags()


@pytest.mark.parametrize(
    "variable_name, field_name",
    [
        ("ENABLE_LIVE_TRADING", "enable_live_trading"),
        ("ENABLE_AUTO_EXECUTION", "enable_auto_execution"),
        ("ENABLE_ADAPTIVE_STRATEGIES", "enable_adaptive_strategies"),
        ("ENABLE_LEARNING", "enable_learning"),
        ("ENABLE_EXPERIMENTS", "enable_experiments"),
    ],
)
def test_exact_true_and_false_are_accepted_for_every_authorized_flag(
    variable_name: str, field_name: str
) -> None:
    true_flags = load_feature_flags({variable_name: "true"})
    false_flags = load_feature_flags({variable_name: "false"})

    assert getattr(true_flags, field_name) is True
    assert getattr(false_flags, field_name) is False


def test_flags_parse_independently_with_mixed_mapping() -> None:
    flags = load_feature_flags(
        {
            "ENABLE_LIVE_TRADING": "true",
            "ENABLE_AUTO_EXECUTION": "false",
            "ENABLE_ADAPTIVE_STRATEGIES": "true",
            "ENABLE_LEARNING": "false",
            "ENABLE_EXPERIMENTS": "true",
        }
    )

    assert flags == FeatureFlags(
        enable_live_trading=True,
        enable_auto_execution=False,
        enable_adaptive_strategies=True,
        enable_learning=False,
        enable_experiments=True,
    )


@pytest.mark.parametrize("invalid_value", ["", " ", "\t", "\n", "   "])
def test_blank_and_whitespace_only_values_fail_closed(invalid_value: str) -> None:
    with pytest.raises(FeatureFlagsError):
        load_feature_flags({"ENABLE_LIVE_TRADING": invalid_value})


@pytest.mark.parametrize("invalid_value", [" true", "true ", "\tfalse", "false\n"])
def test_leading_or_trailing_whitespace_fails_closed(invalid_value: str) -> None:
    with pytest.raises(FeatureFlagsError):
        load_feature_flags({"ENABLE_AUTO_EXECUTION": invalid_value})


@pytest.mark.parametrize("invalid_value", ["TRUE", "True", "FALSE", "False"])
def test_case_variants_fail_closed(invalid_value: str) -> None:
    with pytest.raises(FeatureFlagsError):
        load_feature_flags({"ENABLE_ADAPTIVE_STRATEGIES": invalid_value})


@pytest.mark.parametrize("invalid_value", ["1", "0", "yes", "no", "on", "off"])
def test_numeric_and_alias_values_fail_closed(invalid_value: str) -> None:
    with pytest.raises(FeatureFlagsError):
        load_feature_flags({"ENABLE_LEARNING": invalid_value})


def test_invalid_value_error_identifies_variable_without_exposing_mapping() -> None:
    with pytest.raises(FeatureFlagsError) as exc_info:
        load_feature_flags(
            {
                "ENABLE_EXPERIMENTS": "unexpected",
                "UNRELATED_SECRET": "top-secret-token",
            }
        )

    error_message = str(exc_info.value)
    assert "ENABLE_EXPERIMENTS" in error_message
    assert "UNRELATED_SECRET" not in error_message
    assert "top-secret-token" not in error_message


def test_feature_flags_and_app_settings_are_immutable() -> None:
    flags = FeatureFlags()
    settings = AppSettings(environment=DeploymentEnvironment.DEV, mode=OperatingMode.RESEARCH)

    with pytest.raises(FrozenInstanceError):
        flags.enable_live_trading = True

    with pytest.raises(FrozenInstanceError):
        settings.feature_flags = FeatureFlags(enable_live_trading=True)
