"""Deterministic execution-cost assumptions for PERSONAL_SPOT_RESEARCH."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
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


class CostModelError(ValueError):
    """Cost assumptions are unavailable, stale, ambiguous, or unsafe."""


class LiquidityRole(StrEnum):
    MAKER = "MAKER"
    TAKER = "TAKER"


@dataclass(frozen=True, slots=True)
class SpotExecutionCostProfile:
    venue_id: str
    instrument_id: str
    asset: str
    fee_tier: str
    source_reference: ValidationArtifactReferenceV2
    maker_fee_bps: Decimal
    taker_fee_bps: Decimal
    spread_bps: Decimal
    slippage_bps: Decimal
    latency_bars: Decimal
    stress_multiplier: Decimal
    effective_from: datetime
    valid_until: datetime
    methodology_version: str = "spot-cost-model-v1"

    def __post_init__(self) -> None:
        for name in (
            "venue_id",
            "instrument_id",
            "asset",
            "fee_tier",
            "methodology_version",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise CostModelError(f"{name} must be a non-blank trimmed string.")
        if type(self.source_reference) is not ValidationArtifactReferenceV2:
            raise CostModelError(
                "source_reference must be an exact versioned source reference."
            )
        for name in (
            "maker_fee_bps",
            "taker_fee_bps",
            "spread_bps",
            "slippage_bps",
            "latency_bars",
            "stress_multiplier",
        ):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite():
                raise CostModelError(f"{name} must be a finite Decimal.")
        if (
            self.maker_fee_bps <= 0
            or self.taker_fee_bps <= 0
            or self.spread_bps <= 0
            or self.slippage_bps <= 0
            or self.latency_bars < 0
            or self.stress_multiplier < Decimal("1")
        ):
            raise CostModelError(
                "Spot costs require explicit positive fee/spread/slippage values, "
                "non-negative latency, and stress_multiplier >= 1."
            )
        effective = _utc("effective_from", self.effective_from)
        valid_until = _utc("valid_until", self.valid_until)
        if effective >= valid_until:
            raise CostModelError("cost profile validity interval is empty.")
        object.__setattr__(self, "effective_from", effective)
        object.__setattr__(self, "valid_until", valid_until)

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
    latency_bars: Decimal
    profile_reference: ValidationArtifactReferenceV2


def build_spot_cost_assumption_set(
    *,
    profile: SpotExecutionCostProfile,
    strategy_version_id: UUID,
    as_of: datetime,
    liquidity_role: LiquidityRole = LiquidityRole.TAKER,
) -> CostAssumptionSetV2:
    at = _utc("as_of", as_of)
    if not profile.effective_from <= at < profile.valid_until:
        raise CostModelError("cost profile is not valid at the requested timestamp.")
    if not isinstance(strategy_version_id, UUID):
        raise CostModelError("strategy_version_id must be a UUID.")
    if not isinstance(liquidity_role, LiquidityRole):
        raise CostModelError("liquidity_role must be explicit.")

    fee = (
        profile.maker_fee_bps
        if liquidity_role is LiquidityRole.MAKER
        else profile.taker_fee_bps
    )
    model = profile.model_reference
    assumptions = (
        ResearchAssumptionV2(
            AssumptionCategory.FEE,
            CostApplicabilityV2.APPLICABLE,
            model,
            fee,
            "bps",
            f"{liquidity_role.value} fee tier {profile.fee_tier}",
        ),
        ResearchAssumptionV2(
            AssumptionCategory.SPREAD,
            CostApplicabilityV2.APPLICABLE,
            model,
            profile.spread_bps * profile.stress_multiplier,
            "bps",
            "Explicit full quoted-spread assumption with stress multiplier.",
        ),
        ResearchAssumptionV2(
            AssumptionCategory.SLIPPAGE,
            CostApplicabilityV2.APPLICABLE,
            model,
            profile.slippage_bps * profile.stress_multiplier,
            "bps",
            "Explicit adverse slippage assumption with stress multiplier.",
        ),
        ResearchAssumptionV2(
            AssumptionCategory.FUNDING,
            CostApplicabilityV2.NOT_APPLICABLE,
            model,
            None,
            None,
            "Spot funding is explicitly not applicable.",
        ),
        ResearchAssumptionV2(
            AssumptionCategory.LATENCY,
            CostApplicabilityV2.APPLICABLE,
            model,
            profile.latency_bars,
            "bars",
            "Explicit candle-delay approximation for Spot research.",
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
    at = _utc("as_of", as_of)
    if not profile.effective_from <= at < profile.valid_until:
        raise CostModelError("cost profile is not valid at the requested timestamp.")
    if (
        not isinstance(notional, Decimal)
        or not notional.is_finite()
        or notional <= 0
    ):
        raise CostModelError("notional must be a positive finite Decimal.")
    if not isinstance(liquidity_role, LiquidityRole):
        raise CostModelError("liquidity_role must be explicit.")

    fee_bps = (
        profile.maker_fee_bps
        if liquidity_role is LiquidityRole.MAKER
        else profile.taker_fee_bps
    )
    spread_bps = profile.spread_bps * profile.stress_multiplier / Decimal("2")
    slippage_bps = profile.slippage_bps * profile.stress_multiplier
    total_bps = fee_bps + spread_bps + slippage_bps
    divisor = Decimal("10000")
    fee = notional * fee_bps / divisor
    spread = notional * spread_bps / divisor
    slippage = notional * slippage_bps / divisor
    return SpotExecutionCost(
        notional=notional,
        liquidity_role=liquidity_role,
        fee=fee,
        spread=spread,
        slippage=slippage,
        total=fee + spread + slippage,
        total_bps=total_bps,
        latency_bars=profile.latency_bars,
        profile_reference=profile.model_reference,
    )


def _utc(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise CostModelError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


__all__ = [
    "CostModelError",
    "LiquidityRole",
    "SpotExecutionCost",
    "SpotExecutionCostProfile",
    "build_spot_cost_assumption_set",
    "estimate_spot_execution_cost",
]
