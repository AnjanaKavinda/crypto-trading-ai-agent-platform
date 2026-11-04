from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from trading_platform_api.validation import (
    AssumptionCategory,
    CostApplicabilityV2,
)
from trading_platform_api.validation.cost_models import (
    CostModelError,
    LiquidityRole,
    SpotExecutionCostProfile,
    build_spot_cost_assumption_set,
    estimate_spot_execution_cost,
)

NOW = datetime(2026, 11, 5, tzinfo=UTC)


def profile(**overrides):
    values = {
        "venue_id": "BINANCE-SPOT",
        "instrument_id": "BTC-USDT-SPOT",
        "asset": "BTC",
        "fee_tier": "personal-research-explicit-v1",
        "maker_fee_bps": Decimal("10"),
        "taker_fee_bps": Decimal("12"),
        "spread_bps": Decimal("4"),
        "slippage_bps": Decimal("6"),
        "latency_bars": Decimal("1"),
        "stress_multiplier": Decimal("1"),
        "effective_from": NOW - timedelta(days=1),
        "valid_until": NOW + timedelta(days=1),
    }
    values.update(overrides)
    return SpotExecutionCostProfile(**values)


def test_spot_cost_assumptions_are_deterministic_and_complete() -> None:
    strategy_version_id = uuid4()
    value = build_spot_cost_assumption_set(
        profile=profile(),
        strategy_version_id=strategy_version_id,
        as_of=NOW,
    )
    repeat = build_spot_cost_assumption_set(
        profile=profile(),
        strategy_version_id=strategy_version_id,
        as_of=NOW,
    )
    assert value == repeat
    assert value.assumption_set_id == repeat.assumption_set_id
    assert value.instrument_type == "SPOT"
    assert set(value.required_categories) == {
        AssumptionCategory.FEE,
        AssumptionCategory.SPREAD,
        AssumptionCategory.SLIPPAGE,
        AssumptionCategory.FUNDING,
        AssumptionCategory.LATENCY,
    }
    funding = next(
        item for item in value.assumptions if item.category is AssumptionCategory.FUNDING
    )
    assert funding.applicability is CostApplicabilityV2.NOT_APPLICABLE
    assert funding.value is None


def test_maker_taker_and_stress_costs_are_explicit() -> None:
    value = profile(stress_multiplier=Decimal("2"))
    maker = estimate_spot_execution_cost(
        profile=value,
        notional=Decimal("10000"),
        as_of=NOW,
        liquidity_role=LiquidityRole.MAKER,
    )
    taker = estimate_spot_execution_cost(
        profile=value,
        notional=Decimal("10000"),
        as_of=NOW,
        liquidity_role=LiquidityRole.TAKER,
    )
    assert maker.total_bps == Decimal("26")
    assert taker.total_bps == Decimal("28")
    assert taker.total > maker.total
    assert maker.spread == Decimal("4")
    assert maker.slippage == Decimal("12")
    assert maker.latency_bars == Decimal("1")


@pytest.mark.parametrize(
    "field",
    ["maker_fee_bps", "taker_fee_bps", "spread_bps", "slippage_bps"],
)
def test_zero_cost_defaults_are_rejected(field: str) -> None:
    with pytest.raises(CostModelError, match="positive"):
        profile(**{field: Decimal("0")})


def test_stale_or_future_cost_profile_is_rejected() -> None:
    value = profile(
        effective_from=NOW + timedelta(hours=1),
        valid_until=NOW + timedelta(hours=2),
    )
    with pytest.raises(CostModelError, match="not valid"):
        build_spot_cost_assumption_set(
            profile=value,
            strategy_version_id=uuid4(),
            as_of=NOW,
        )
    with pytest.raises(CostModelError, match="not valid"):
        estimate_spot_execution_cost(
            profile=value,
            notional=Decimal("1"),
            as_of=NOW,
        )


def test_changed_profile_changes_exact_model_and_assumption_identity() -> None:
    strategy_version_id = uuid4()
    first_profile = profile()
    second_profile = replace(first_profile, slippage_bps=Decimal("7"))
    first = build_spot_cost_assumption_set(
        profile=first_profile,
        strategy_version_id=strategy_version_id,
        as_of=NOW,
    )
    second = build_spot_cost_assumption_set(
        profile=second_profile,
        strategy_version_id=strategy_version_id,
        as_of=NOW,
    )
    assert first.content_sha256 != second.content_sha256
    assert first.assumption_set_id != second.assumption_set_id
    assert first_profile.model_reference != second_profile.model_reference


@pytest.mark.parametrize("notional", [Decimal("0"), Decimal("-1")])
def test_invalid_notional_is_rejected(notional: Decimal) -> None:
    with pytest.raises(CostModelError):
        estimate_spot_execution_cost(
            profile=profile(),
            notional=notional,
            as_of=NOW,
        )
