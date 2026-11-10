from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from trading_platform_api.config import DeploymentEnvironment
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.validation import AssumptionCategory
from trading_platform_api.validation.contracts_v2 import ValidationArtifactReferenceV2
from trading_platform_api.validation.cost_models import (
    CostSourceKind,
    SpotExecutionCostProfile,
    build_spot_cost_assumption_set,
)
from trading_platform_api.validation.spot_cost_adapter import SpotExecutionCostAdapter
from trading_platform_api.validation.spot_execution import (
    ExecutionCostRequest,
    OrderKind,
    OrderSide,
    SimulationUnavailable,
    SpotExecutionPolicy,
)

T = datetime(2026, 11, 5, tzinfo=UTC)
STRATEGY_ID = UUID("33333333-3333-4333-8333-333333333333")
REVISION_ID = UUID("44444444-4444-4444-8444-444444444444")


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
        "latency_bars": 0,
        "stress_multiplier": Decimal("1"),
        "available_at": T,
        "effective_from": T,
        "valid_until": T + timedelta(days=1),
    }
    values.update(overrides)
    return SpotExecutionCostProfile(**values)  # type: ignore[arg-type]


def adapter_and_request(**profile_changes: object):
    model = profile(**profile_changes)
    assumptions = build_spot_cost_assumption_set(
        profile=model,
        strategy_version_id=STRATEGY_ID,
        as_of=max(model.available_at, model.effective_from),
    )
    adapter = SpotExecutionCostAdapter(model, assumptions)
    start, end = T + timedelta(minutes=1), T + timedelta(minutes=2)
    policy = SpotExecutionPolicy(
        model.venue_id,
        model.instrument_id,
        model.asset,
        model.price_unit,
        model.quantity_unit,
        "1m",
        DeploymentEnvironment.TEST,
        T,
        T + timedelta(minutes=10),
        Decimal("0.25"),
        Decimal("0.1"),
        Decimal("1000"),
        Decimal("0"),
        model.latency_bars,
        0,
    )
    request = ExecutionCostRequest(
        policy,
        UUID("55555555-5555-4555-8555-555555555555"),
        OrderSide.BUY,
        OrderKind.LIMIT,
        Decimal("0.5"),
        Decimal("100"),
        T + timedelta(seconds=1),
        start,
        end,
        REVISION_ID,
        "e" * 64,
        end,
        assumptions,
    )
    return adapter, request


def test_adapter_quotes_actual_partial_fill_and_binds_exact_identity() -> None:
    adapter, request = adapter_and_request()
    quote = adapter.quote(request)

    assert quote.request_sha256 == canonical_sha256(request)
    assert quote.assumption_set_id == request.assumptions.assumption_set_id
    assert quote.assumption_set_sha256 == request.assumptions.content_sha256
    assert quote.adapter_reference == adapter.adapter_reference
    assert (quote.fee, quote.spread, quote.slippage) == (
        Decimal("0.06"),
        Decimal("0.01"),
        Decimal("0.03"),
    )
    assert quote.fee + quote.spread + quote.slippage == Decimal("0.10")


def test_late_bar_availability_does_not_replace_actual_allocation_interval() -> None:
    start, end = T + timedelta(minutes=1), T + timedelta(minutes=2)
    adapter, request = adapter_and_request(
        effective_from=start,
        valid_until=end,
    )
    late = replace(request, observed_at=end + timedelta(minutes=4))
    assert adapter.quote(late).request_sha256 == canonical_sha256(late)

    expired = adapter_and_request(
        effective_from=start,
        valid_until=end - timedelta(microseconds=1),
    )
    with pytest.raises(SimulationUnavailable, match="full allocation bar"):
        expired[0].quote(expired[1])


def test_adapter_fails_closed_for_profile_not_known_by_decision() -> None:
    adapter, request = adapter_and_request(available_at=T + timedelta(seconds=2))
    with pytest.raises(SimulationUnavailable, match="unavailable at the decision"):
        adapter.quote(request)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("venue", "OTHER-SPOT"),
        ("instrument_id", "ETH-USDT-SPOT"),
        ("asset", "ETH"),
        ("quote_unit", "USD"),
        ("quantity_unit", "ETH"),
        ("latency_bars", 1),
    ],
)
def test_adapter_rejects_mismatched_policy_scope_and_latency(
    field: str, value: object
) -> None:
    adapter, request = adapter_and_request()
    changed = replace(request, policy=replace(request.policy, **{field: value}))
    with pytest.raises(SimulationUnavailable):
        adapter.quote(changed)


def test_adapter_rejects_changed_cost_set_and_model_identity() -> None:
    adapter, request = adapter_and_request()
    changed_profile = profile(taker_fee_bps=Decimal("13"))
    changed_costs = build_spot_cost_assumption_set(
        profile=changed_profile, strategy_version_id=STRATEGY_ID, as_of=T
    )
    with pytest.raises(SimulationUnavailable, match="changed C-027v2"):
        adapter.quote(replace(request, assumptions=changed_costs))
    with pytest.raises(ValueError, match="do not match"):
        SpotExecutionCostAdapter(adapter.profile, changed_costs)


def test_quote_binds_entire_request_digest_including_revision_and_bar_interval() -> (
    None
):
    adapter, request = adapter_and_request()
    initial = adapter.quote(request)
    changes = (
        {"quantity": Decimal("0.4")},
        {"gross_price": Decimal("101")},
        {"bar_start": request.bar_start + timedelta(seconds=1)},
        {
            "bar_end": request.bar_end + timedelta(seconds=1),
            "observed_at": request.observed_at + timedelta(seconds=1),
        },
        {"source_revision_id": UUID("66666666-6666-4666-8666-666666666666")},
        {"source_revision_sha256": "f" * 64},
    )
    for change in changes:
        changed = replace(request, **change)
        quote = adapter.quote(changed)
        assert quote.request_sha256 == canonical_sha256(changed)
        assert quote.request_sha256 != initial.request_sha256


def test_adapter_never_infers_maker_from_limit_order_kind() -> None:
    adapter, request = adapter_and_request()
    quote = adapter.quote(request)
    assert request.kind is OrderKind.LIMIT
    assert quote.fee == Decimal("0.06")


def test_positive_assumed_charges_do_not_disappear_below_output_precision() -> None:
    adapter, request = adapter_and_request(taker_fee_bps=Decimal("1e-18"))
    request = replace(request, quantity=Decimal("1e-18"))
    with pytest.raises(SimulationUnavailable, match="fee must be"):
        adapter.quote(request)


def test_adapter_charges_exact_normalized_pinned_rates() -> None:
    adapter, request = adapter_and_request(
        spread_bps=Decimal("1e-18"),
        slippage_bps=Decimal("1e-18"),
        stress_multiplier=Decimal("1.5"),
    )
    request = replace(
        request,
        quantity=Decimal("1e20"),
        gross_price=Decimal("1"),
    )
    pinned = {item.category: item for item in adapter.assumptions.assumptions}

    quote = adapter.quote(request)

    assert pinned[AssumptionCategory.SPREAD].value == Decimal("2e-18")
    assert pinned[AssumptionCategory.SLIPPAGE].value == Decimal("2e-18")
    assert quote.spread == Decimal("0.01")
    assert quote.slippage == Decimal("0.02")


@pytest.mark.parametrize(
    ("spread_bps", "stress", "pinned_spread", "expected_charge"),
    [
        ("2e-18", "1.5", "3e-18", "0.015"),
        ("1e-18", "1", "1e-18", "0.005"),
        ("1e-18", "5", "5e-18", "0.025"),
    ],
)
def test_adapter_preserves_exact_half_of_odd_normalized_full_spread(
    spread_bps: str,
    stress: str,
    pinned_spread: str,
    expected_charge: str,
) -> None:
    adapter, request = adapter_and_request(
        spread_bps=Decimal(spread_bps),
        stress_multiplier=Decimal(stress),
    )
    request = replace(request, quantity=Decimal("1e20"), gross_price=Decimal("1"))
    pinned = {item.category: item for item in adapter.assumptions.assumptions}
    quote = adapter.quote(request)
    assert pinned[AssumptionCategory.SPREAD].value == Decimal(pinned_spread)
    assert quote.spread == Decimal(expected_charge)
    assert quote.request_sha256 == canonical_sha256(request)
