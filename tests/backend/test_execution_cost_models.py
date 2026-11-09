from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from uuid import UUID

import pytest
from trading_platform_api.validation import AssumptionCategory
from trading_platform_api.validation.contracts_v2 import (
    CostApplicabilityV2,
    ValidationArtifactReferenceV2,
)
from trading_platform_api.validation.cost_models import (
    CostModelError,
    CostSourceKind,
    LiquidityRole,
    SpotExecutionCostProfile,
    build_spot_cost_assumption_set,
    estimate_spot_execution_cost,
)

NOW = datetime(2026, 11, 5, tzinfo=UTC)
STRATEGY_ID = UUID("33333333-3333-4333-8333-333333333333")


def profile(**overrides: object) -> SpotExecutionCostProfile:
    values: dict[str, object] = {
        "venue_id": "SYNTHETIC-SPOT",
        "instrument_id": "BTC-USDT-SPOT",
        "asset": "BTC",
        "price_unit": "USDT",
        "quantity_unit": "BTC",
        "fee_tier": "configured-research-tier-v1",
        "source_reference": ValidationArtifactReferenceV2(
            "SYNTHETIC_COST_CONFIGURATION",
            UUID("22222222-2222-4222-8222-222222222222"),
            "1",
            "c" * 64,
        ),
        "source_kind": CostSourceKind.CONFIGURED_RESEARCH_ASSUMPTION,
        "methodology_version": "spot-cost-model-v1",
        "maker_fee_bps": Decimal("10"),
        "taker_fee_bps": Decimal("12"),
        "spread_bps": Decimal("4"),
        "slippage_bps": Decimal("6"),
        "latency_bars": 1,
        "stress_multiplier": Decimal("1"),
        "available_at": NOW - timedelta(days=2),
        "effective_from": NOW - timedelta(days=1),
        "valid_until": NOW + timedelta(days=1),
    }
    values.update(overrides)
    return SpotExecutionCostProfile(**values)  # type: ignore[arg-type]


def test_cost_assumptions_bind_profile_strategy_and_spot_funding() -> None:
    model = profile()
    costs = build_spot_cost_assumption_set(
        profile=model, strategy_version_id=STRATEGY_ID, as_of=NOW
    )
    repeat = build_spot_cost_assumption_set(
        profile=model, strategy_version_id=STRATEGY_ID, as_of=NOW
    )

    assert costs == repeat
    assert costs.assumption_set_id == repeat.assumption_set_id
    assert costs.instrument_type == "SPOT"
    assert costs.strategy_version_id == STRATEGY_ID
    assert {assumption.model for assumption in costs.assumptions} == {
        model.model_reference
    }
    funding = next(
        item
        for item in costs.assumptions
        if item.category is AssumptionCategory.FUNDING
    )
    assert funding.applicability is CostApplicabilityV2.NOT_APPLICABLE
    assert funding.value is funding.unit is None
    fee = next(
        item for item in costs.assumptions if item.category is AssumptionCategory.FEE
    )
    assert "not a verified exchange fee feed" in fee.rationale
    spread = next(
        item for item in costs.assumptions if item.category is AssumptionCategory.SPREAD
    )
    assert spread.value == Decimal("4")
    assert "full quoted spread" in spread.rationale


def test_known_maker_taker_spread_slippage_stress_and_latency_arithmetic() -> None:
    model = profile(stress_multiplier=Decimal("2"))
    maker = estimate_spot_execution_cost(
        profile=model,
        notional=Decimal("10000"),
        as_of=NOW,
        liquidity_role=LiquidityRole.MAKER,
    )
    taker = estimate_spot_execution_cost(
        profile=model,
        notional=Decimal("10000"),
        as_of=NOW,
        liquidity_role=LiquidityRole.TAKER,
    )

    assert (maker.fee, maker.spread, maker.slippage, maker.total) == tuple(
        map(Decimal, ("10", "4", "12", "26"))
    )
    assert (taker.fee, taker.spread, taker.slippage, taker.total) == tuple(
        map(Decimal, ("12", "4", "12", "28"))
    )
    assert maker.total_bps == Decimal("26")
    assert taker.total_bps == Decimal("28")
    assert taker.latency_bars == 1


def test_c027_assumption_builder_rejects_unproven_maker_eligibility() -> None:
    with pytest.raises(CostModelError, match="maker eligibility"):
        build_spot_cost_assumption_set(
            profile=profile(),
            strategy_version_id=STRATEGY_ID,
            as_of=NOW,
            liquidity_role=LiquidityRole.MAKER,
        )


def test_identity_and_calculation_ignore_ambient_decimal_context() -> None:
    model = profile(
        maker_fee_bps=Decimal("10.123456789012345678"),
        taker_fee_bps=Decimal("12.123456789012345678"),
        spread_bps=Decimal("4.123456789012345678"),
        slippage_bps=Decimal("6.123456789012345678"),
        stress_multiplier=Decimal("1.234567890123456789"),
    )
    results = []
    for precision in (6, 80):
        with localcontext() as context:
            context.prec = precision
            assumptions = build_spot_cost_assumption_set(
                profile=model, strategy_version_id=STRATEGY_ID, as_of=NOW
            )
            result = estimate_spot_execution_cost(
                profile=model, notional=Decimal("12345.6789"), as_of=NOW
            )
            results.append((model.content_sha256, assumptions, result))
    assert results[0] == results[1]


def test_profile_identity_changes_when_any_cost_source_or_scope_changes() -> None:
    original = profile()
    changes = (
        {"taker_fee_bps": Decimal("13")},
        {"venue_id": "OTHER-SPOT"},
        {
            "source_reference": replace(
                original.source_reference, content_sha256="d" * 64
            )
        },
        {"available_at": NOW - timedelta(days=3)},
        {"valid_until": NOW + timedelta(days=2)},
    )
    original_set = build_spot_cost_assumption_set(
        profile=original, strategy_version_id=STRATEGY_ID, as_of=NOW
    )
    for change in changes:
        changed = replace(original, **change)
        changed_set = build_spot_cost_assumption_set(
            profile=changed, strategy_version_id=STRATEGY_ID, as_of=NOW
        )
        assert changed.content_sha256 != original.content_sha256
        assert changed.model_reference != original.model_reference
        assert changed_set.content_sha256 != original_set.content_sha256
        assert changed_set.assumption_set_id != original_set.assumption_set_id


@pytest.mark.parametrize(
    "field",
    ["maker_fee_bps", "taker_fee_bps", "spread_bps", "slippage_bps"],
)
def test_implicit_zero_cost_assumptions_are_rejected(field: str) -> None:
    with pytest.raises(CostModelError, match="positive"):
        profile(**{field: Decimal("0")})


@pytest.mark.parametrize(
    "value",
    [
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-1"),
        Decimal("1e31"),
        Decimal("1e-19"),
        1.0,
    ],
)
def test_non_finite_negative_and_unbounded_cost_inputs_are_rejected(
    value: object,
) -> None:
    with pytest.raises(CostModelError):
        profile(taker_fee_bps=value)


def test_explicit_zero_latency_is_valid_but_fractional_latency_is_not() -> None:
    assert profile(latency_bars=0).latency_bars == 0
    with pytest.raises(CostModelError, match="latency_bars"):
        profile(latency_bars=Decimal("0.5"))


def test_profile_availability_and_effective_expiry_boundaries_fail_closed() -> None:
    model = profile(
        available_at=NOW,
        effective_from=NOW,
        valid_until=NOW + timedelta(hours=1),
    )
    build_spot_cost_assumption_set(
        profile=model, strategy_version_id=STRATEGY_ID, as_of=NOW
    )
    for unavailable_at in (
        NOW - timedelta(microseconds=1),
        NOW + timedelta(hours=1),
    ):
        with pytest.raises(CostModelError):
            build_spot_cost_assumption_set(
                profile=model,
                strategy_version_id=STRATEGY_ID,
                as_of=unavailable_at,
            )
    late_available = replace(
        model,
        available_at=NOW + timedelta(hours=1),
        valid_until=NOW + timedelta(hours=2),
    )
    with pytest.raises(CostModelError, match="available"):
        build_spot_cost_assumption_set(
            profile=late_available, strategy_version_id=STRATEGY_ID, as_of=NOW
        )


def test_profile_rejects_empty_validity_and_naive_time() -> None:
    with pytest.raises(CostModelError, match="interval"):
        profile(valid_until=NOW - timedelta(days=1))
    with pytest.raises(CostModelError, match="timezone-aware"):
        profile(available_at=datetime(2026, 11, 4))


def test_cost_quote_math_uses_full_spread_as_half_spread_charge() -> None:
    model = profile(stress_multiplier=Decimal("1.5"))
    result = estimate_spot_execution_cost(
        profile=model, notional=Decimal("1000"), as_of=NOW
    )
    assert result.spread == Decimal("0.3")
    assert result.slippage == Decimal("0.9")
    assert result.total == Decimal("2.4")


def test_positive_costs_cannot_round_silently_to_zero() -> None:
    with pytest.raises(CostModelError, match="positive"):
        estimate_spot_execution_cost(
            profile=profile(),
            notional=Decimal("1e-18"),
            as_of=NOW,
        )
