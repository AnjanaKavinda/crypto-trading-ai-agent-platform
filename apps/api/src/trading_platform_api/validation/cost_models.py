"""Versioned deterministic execution-cost assumptions for Spot research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from enum import StrEnum
from uuid import UUID, uuid5

from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.validation.contracts import AssumptionCategory
from trading_platform_api.validation.contracts_v2 import (
    CostApplicabilityV2,
    CostAssumptionSetV2,
    ResearchAssumptionV2,
    ValidationArtifactReferenceV2,
)

_COST_MODEL_NAMESPACE = UUID("850bdada-e08a-596a-a740-86155ea0b6bd")
_COST_SET_NAMESPACE = UUID("904ac177-ab77-59b4-a63f-ac00978601c2")
_CONTEXT = Context(prec=120, rounding=ROUND_HALF_EVEN)
_BPS = Decimal("10000")
_QUANTUM = Decimal("1e-18")


class CostModelError(ValueError):
    """Cost assumptions are unavailable, stale, ambiguous, or unsafe."""


class CostSourceKind(StrEnum):
    CONFIGURED_RESEARCH_ASSUMPTION = "CONFIGURED_RESEARCH_ASSUMPTION"


class LiquidityRole(StrEnum):
    MAKER = "MAKER"
    TAKER = "TAKER"


@dataclass(frozen=True, slots=True)
class SpotExecutionCostProfile:
    venue_id: str
    instrument_id: str
    asset: str
    price_unit: str
    quantity_unit: str
    fee_tier: str
    source_reference: ValidationArtifactReferenceV2
    source_kind: CostSourceKind
    methodology_version: str
    maker_fee_bps: Decimal
    taker_fee_bps: Decimal
    spread_bps: Decimal
    slippage_bps: Decimal
    latency_bars: int
    stress_multiplier: Decimal
    available_at: datetime
    effective_from: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        for name in (
            "venue_id",
            "instrument_id",
            "asset",
            "price_unit",
            "quantity_unit",
            "fee_tier",
            "methodology_version",
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value.strip()
                or value != value.strip()
                or len(value) > 128
            ):
                raise CostModelError(f"{name} must be a non-blank trimmed string.")
        if type(self.source_reference) is not ValidationArtifactReferenceV2:
            raise CostModelError(
                "source_reference must be an exact versioned reference."
            )
        if type(self.source_kind) is not CostSourceKind:
            raise CostModelError(
                "source_kind must explicitly identify configured input."
            )
        for name in (
            "maker_fee_bps",
            "taker_fee_bps",
            "spread_bps",
            "slippage_bps",
            "stress_multiplier",
        ):
            _decimal(name, getattr(self, name), positive=True)
        if self.stress_multiplier < Decimal("1"):
            raise CostModelError("stress_multiplier must be at least one.")
        if type(self.latency_bars) is not int or not 0 <= self.latency_bars <= 10_000:
            raise CostModelError("latency_bars must be a bounded non-negative integer.")
        for name in ("available_at", "effective_from", "valid_until"):
            object.__setattr__(self, name, _utc(name, getattr(self, name)))
        if (
            self.effective_from >= self.valid_until
            or self.available_at >= self.valid_until
        ):
            raise CostModelError("cost profile has no available effective interval.")

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self)

    @property
    def model_reference(self) -> ValidationArtifactReferenceV2:
        digest = self.content_sha256
        return ValidationArtifactReferenceV2(
            "C-027-COSTMODEL",
            uuid5(_COST_MODEL_NAMESPACE, digest),
            self.methodology_version,
            digest,
        )


@dataclass(frozen=True, slots=True)
class SpotExecutionCost:
    notional: Decimal
    liquidity_role: LiquidityRole
    fee: Decimal
    spread: Decimal
    slippage: Decimal
    total: Decimal
    total_bps: Decimal
    latency_bars: int
    profile_reference: ValidationArtifactReferenceV2


def build_spot_cost_assumption_set(
    *,
    profile: SpotExecutionCostProfile,
    strategy_version_id: UUID,
    as_of: datetime,
    liquidity_role: LiquidityRole = LiquidityRole.TAKER,
) -> CostAssumptionSetV2:
    if type(profile) is not SpotExecutionCostProfile:
        raise CostModelError("profile must be an exact SpotExecutionCostProfile.")
    at = _utc("as_of", as_of)
    if not profile.available_at <= at:
        raise CostModelError(
            "cost profile is not available at the requested timestamp."
        )
    if not profile.effective_from <= at < profile.valid_until:
        raise CostModelError(
            "cost profile is not effective at the requested timestamp."
        )
    if type(strategy_version_id) is not UUID:
        raise CostModelError("strategy_version_id must be a UUID.")
    if type(liquidity_role) is not LiquidityRole:
        raise CostModelError("liquidity_role must be explicit.")
    if liquidity_role is not LiquidityRole.TAKER:
        raise CostModelError("maker eligibility is unsupported by the Spot adapter.")

    with localcontext(_CONTEXT):
        fee = profile.taker_fee_bps
        spread = _round_bounded(profile.spread_bps * profile.stress_multiplier)
        slippage = _round_bounded(profile.slippage_bps * profile.stress_multiplier)
        _decimal("stressed spread assumption", spread, positive=True)
        _decimal("stressed slippage assumption", slippage, positive=True)
        model = profile.model_reference
        assumptions = (
            ResearchAssumptionV2(
                AssumptionCategory.FEE,
                CostApplicabilityV2.APPLICABLE,
                model,
                fee,
                "bps",
                (
                    f"Configured research assumption for {liquidity_role.value} "
                    f"fee tier {profile.fee_tier}; not a verified exchange fee feed."
                ),
            ),
            ResearchAssumptionV2(
                AssumptionCategory.SPREAD,
                CostApplicabilityV2.APPLICABLE,
                model,
                spread,
                "bps",
                (
                    "Configured full quoted spread in bps after stress; the "
                    "adverse execution charge is one half of this value."
                ),
            ),
            ResearchAssumptionV2(
                AssumptionCategory.SLIPPAGE,
                CostApplicabilityV2.APPLICABLE,
                model,
                slippage,
                "bps",
                "Configured adverse slippage in bps after stress.",
            ),
            ResearchAssumptionV2(
                AssumptionCategory.FUNDING,
                CostApplicabilityV2.NOT_APPLICABLE,
                model,
                None,
                None,
                "Funding is not applicable to this Spot profile.",
            ),
            ResearchAssumptionV2(
                AssumptionCategory.LATENCY,
                CostApplicabilityV2.APPLICABLE,
                model,
                Decimal(profile.latency_bars),
                "bars",
                "Configured candle-delay approximation for Spot research.",
            ),
        )
        required = tuple(item.category for item in assumptions)
        identity = canonical_sha256(
            {
                "strategy_version_id": strategy_version_id,
                "profile": profile,
                "liquidity_role": liquidity_role.value,
                "assumptions": assumptions,
            }
        )
        return CostAssumptionSetV2.build(
            assumption_set_id=uuid5(_COST_SET_NAMESPACE, identity),
            strategy_version_id=strategy_version_id,
            asset=profile.asset,
            instrument_type="SPOT",
            required_categories=required,
            assumptions=assumptions,
        )


def estimate_spot_execution_cost(
    *,
    profile: SpotExecutionCostProfile,
    notional: Decimal,
    as_of: datetime,
    liquidity_role: LiquidityRole = LiquidityRole.TAKER,
) -> SpotExecutionCost:
    if type(profile) is not SpotExecutionCostProfile:
        raise CostModelError("profile must be an exact SpotExecutionCostProfile.")
    at = _utc("as_of", as_of)
    if not profile.available_at <= at:
        raise CostModelError(
            "cost profile is not available at the requested timestamp."
        )
    if not profile.effective_from <= at < profile.valid_until:
        raise CostModelError(
            "cost profile is not effective at the requested timestamp."
        )
    _decimal("notional", notional, positive=True)
    if type(liquidity_role) is not LiquidityRole:
        raise CostModelError("liquidity_role must be explicit.")

    with localcontext(_CONTEXT):
        fee_bps = (
            profile.maker_fee_bps
            if liquidity_role is LiquidityRole.MAKER
            else profile.taker_fee_bps
        )
        charged_spread_bps = (
            profile.spread_bps * profile.stress_multiplier / Decimal("2")
        )
        slippage_bps = profile.slippage_bps * profile.stress_multiplier
        total_bps = fee_bps + charged_spread_bps + slippage_bps
        fee = _round_bounded(notional * fee_bps / _BPS)
        spread = _round_bounded(notional * charged_spread_bps / _BPS)
        slippage = _round_bounded(notional * slippage_bps / _BPS)
        total = _round_bounded(fee + spread + slippage)
        total_bps = _round_bounded(total_bps)
        for name, value in (
            ("fee", fee),
            ("spread", spread),
            ("slippage", slippage),
            ("total", total),
            ("total_bps", total_bps),
        ):
            _decimal(name, value, positive=True)
        return SpotExecutionCost(
            notional,
            liquidity_role,
            fee,
            spread,
            slippage,
            total,
            total_bps,
            profile.latency_bars,
            profile.model_reference,
        )


def calculate_spot_notional(*, quantity: Decimal, gross_price: Decimal) -> Decimal:
    _decimal("quantity", quantity, positive=True)
    _decimal("gross_price", gross_price, positive=True)
    with localcontext(_CONTEXT):
        notional = _round_bounded(quantity * gross_price)
    return _decimal("notional", notional, positive=True)


def _round_bounded(value: Decimal) -> Decimal:
    return value.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)


def _decimal(name: str, value: object, *, positive: bool = False) -> Decimal:
    if (
        type(value) is not Decimal
        or not value.is_finite()
        or (value <= 0 if positive else value < 0)
        or value.adjusted() > 30
        or int(value.as_tuple().exponent) < -18
    ):
        qualifier = "positive " if positive else "non-negative "
        raise CostModelError(f"{name} must be a bounded finite {qualifier}Decimal.")
    return value


def _utc(name: str, value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise CostModelError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


__all__ = [
    "CostModelError",
    "CostSourceKind",
    "LiquidityRole",
    "SpotExecutionCost",
    "SpotExecutionCostProfile",
    "build_spot_cost_assumption_set",
    "calculate_spot_notional",
    "estimate_spot_execution_cost",
]
