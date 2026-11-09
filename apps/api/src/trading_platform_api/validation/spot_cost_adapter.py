"""Pure C-027v2 cost adapter for the bounded Spot scenario kernel."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid5

from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.validation.contracts_v2 import (
    CostAssumptionSetV2,
    ValidationArtifactReferenceV2,
)
from trading_platform_api.validation.cost_models import (
    CostModelError,
    LiquidityRole,
    SpotExecutionCostProfile,
    build_spot_cost_assumption_set,
    calculate_spot_notional,
    estimate_spot_execution_cost,
)
from trading_platform_api.validation.spot_execution import (
    ExecutionCostQuote,
    ExecutionCostRequest,
    SimulationUnavailable,
)

_ADAPTER_NAMESPACE = UUID("28c07a45-2491-5b11-b7ac-935fc934a2a3")
_ADAPTER_METHOD = "spot-execution-cost-adapter-v1"


@dataclass(frozen=True, slots=True)
class SpotExecutionCostAdapter:
    profile: SpotExecutionCostProfile
    assumptions: CostAssumptionSetV2
    adapter_reference: ValidationArtifactReferenceV2 = field(init=False)

    def __post_init__(self) -> None:
        if type(self.profile) is not SpotExecutionCostProfile:
            raise CostModelError("profile must be an exact SpotExecutionCostProfile.")
        if type(self.assumptions) is not CostAssumptionSetV2:
            raise CostModelError("assumptions must be an exact C-027v2 set.")
        usable_from = max(self.profile.available_at, self.profile.effective_from)
        expected = build_spot_cost_assumption_set(
            profile=self.profile,
            strategy_version_id=self.assumptions.strategy_version_id,
            as_of=usable_from,
            liquidity_role=LiquidityRole.TAKER,
        )
        if self.assumptions != expected:
            raise CostModelError(
                "C-027v2 assumptions do not match the exact TAKER profile."
            )
        digest = canonical_sha256(
            {
                "adapter_method": _ADAPTER_METHOD,
                "profile_sha256": self.profile.content_sha256,
                "assumption_set_id": self.assumptions.assumption_set_id,
                "assumption_set_sha256": self.assumptions.content_sha256,
            }
        )
        object.__setattr__(
            self,
            "adapter_reference",
            ValidationArtifactReferenceV2(
                "SPOT-COST-ADAPTER",
                uuid5(_ADAPTER_NAMESPACE, digest),
                _ADAPTER_METHOD,
                digest,
            ),
        )

    def quote(self, request: ExecutionCostRequest) -> ExecutionCostQuote:
        try:
            return self._quote(request)
        except CostModelError as exc:
            raise SimulationUnavailable(str(exc)) from exc

    def _quote(self, request: ExecutionCostRequest) -> ExecutionCostQuote:
        if type(request) is not ExecutionCostRequest:
            raise SimulationUnavailable("INVALID_COST_REQUEST")
        policy = request.policy
        profile = self.profile
        if (
            policy.venue != profile.venue_id
            or policy.instrument_id != profile.instrument_id
            or policy.asset != profile.asset
            or policy.quote_unit != profile.price_unit
            or policy.quantity_unit != profile.quantity_unit
        ):
            raise CostModelError(
                "cost profile venue, instrument, asset, or units mismatch."
            )
        if not (
            policy.period_start <= request.decision_time < policy.period_end
            and policy.period_start
            <= request.bar_start
            < request.bar_end
            <= policy.period_end
        ):
            raise CostModelError(
                "cost request interval is outside the execution period."
            )
        if request.assumptions != self.assumptions:
            raise CostModelError("cost request uses a changed C-027v2 assumption set.")
        if policy.latency_bars != profile.latency_bars:
            raise CostModelError(
                "cost profile latency does not match the execution policy."
            )
        if profile.available_at > request.decision_time:
            raise CostModelError("cost profile was unavailable at the decision time.")
        if not (
            profile.effective_from <= request.bar_start
            and request.bar_start < request.bar_end
            and request.bar_end <= profile.valid_until
        ):
            raise CostModelError("cost profile does not cover the full allocation bar.")
        if request.observed_at < request.bar_end:
            raise CostModelError(
                "allocation evidence is unavailable before the bar ends."
            )
        expected = build_spot_cost_assumption_set(
            profile=profile,
            strategy_version_id=self.assumptions.strategy_version_id,
            as_of=request.bar_start,
            liquidity_role=LiquidityRole.TAKER,
        )
        if expected != self.assumptions:
            raise CostModelError(
                "cost model or C-027v2 identity changed for this request."
            )
        if not isinstance(request.source_revision_id, UUID) or not _is_sha256(
            request.source_revision_sha256
        ):
            raise CostModelError("source revision identity and digest are required.")

        result = estimate_spot_execution_cost(
            profile=profile,
            notional=calculate_spot_notional(
                quantity=request.quantity,
                gross_price=request.gross_price,
            ),
            as_of=request.bar_start,
            liquidity_role=LiquidityRole.TAKER,
        )
        return ExecutionCostQuote(
            canonical_sha256(request),
            self.assumptions.assumption_set_id,
            self.assumptions.content_sha256,
            self.adapter_reference,
            result.fee,
            result.spread,
            result.slippage,
        )


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = ["SpotExecutionCostAdapter"]
