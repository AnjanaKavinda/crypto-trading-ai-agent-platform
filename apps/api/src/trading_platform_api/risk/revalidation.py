"""Deterministic research-risk supersession; no approval or execution workflow."""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass, replace
from uuid import UUID

from trading_platform_api.risk.contracts import (
    PositionSizingResult,
    RevalidationStatus,
    RevalidationTrigger,
    RiskContractError,
    RiskRevalidationResult,
    RiskVerdict,
    RuinPathEvidence,
    _risk_digest,
    _uuid,
)
from trading_platform_api.risk.proposals import (
    RiskProposalRequest,
    RiskProposalSnapshot,
    build_risk_proposal,
)

_OPERATION_FIELDS = frozenset(
    {
        "proposal_id",
        "assessment_id",
        "decision_id",
        "previous_proposal",
        "result_id",
        "evaluated_at",
    }
)


def _material(value: object) -> object:
    """Keep source evidence; normalize calculation IDs/clocks and derived hashes.

    Ruin hashes bind the entire calculation request, including its clock. Verify
    them before normalization; all path data, source versions and windows remain.
    """
    if (
        isinstance(value, RuinPathEvidence)
        and value.identity_digest() != value.content_sha256
    ):
        raise RiskContractError("RUIN_PATH_DIGEST_MISMATCH")
    if is_dataclass(value) and not isinstance(value, type):
        ignored = _OPERATION_FIELDS | (
            {"content_sha256"}
            if isinstance(value, (PositionSizingResult, RuinPathEvidence))
            else set()
        )
        return {
            f.name: _material(getattr(value, f.name))
            for f in fields(value)
            if f.name not in ignored
        }
    if isinstance(value, tuple):
        return tuple(_material(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class RiskRevalidationRequest:
    result_id: UUID
    original: RiskProposalSnapshot
    replacement: RiskProposalRequest

    def __post_init__(self) -> None:
        _uuid("result_id", self.result_id)
        if not isinstance(self.original, RiskProposalSnapshot) or not isinstance(
            self.replacement, RiskProposalRequest
        ):
            raise RiskContractError(
                "typed original snapshot and replacement request are required."
            )
        if self.replacement.previous_proposal != self.original.proposal:
            raise RiskContractError("REVALIDATION_PREVIOUS_PROPOSAL_MISMATCH")
        sizing = self.replacement.stress.portfolio_request.basis.leverage_request.sizing_request
        old_context, new_context = self.original.proposal.context, sizing.context
        if (
            sizing.account.account_id != self.original.account_snapshot.account_id
            or sizing.account.currency != self.original.account_snapshot.currency
            or (new_context.asset, new_context.instrument_id, new_context.side)
            != (old_context.asset, old_context.instrument_id, old_context.side)
        ):
            raise RiskContractError("REVALIDATION_UNRELATED_ACCOUNT_OR_TRADE")
        if self.replacement.stress.evaluated_at < self.original.proposal.created_at:
            raise RiskContractError("REVALIDATION_TIME_PRECEDES_ORIGINAL")
        if self.result_id in {
            self.replacement.proposal_id,
            self.replacement.assessment_id,
            self.replacement.decision_id,
        }:
            raise RiskContractError("REVALIDATION_RESULT_ID_COLLISION")


def _groups(
    source: RiskProposalRequest,
) -> dict[str, tuple[RevalidationTrigger, object]]:
    basis = source.stress.portfolio_request.basis
    sizing, leverage = basis.leverage_request.sizing_request, basis.leverage_request
    context = sizing.context
    return {
        "account_snapshot": (
            RevalidationTrigger.ACCOUNT,
            (sizing.account, context.account_snapshot),
        ),
        "portfolio_snapshot": (
            RevalidationTrigger.PORTFOLIO,
            (
                sizing.portfolio,
                context.portfolio_snapshot,
                source.stress.portfolio_request.positions,
                source.stress.portfolio_request.scenarios,
                source.stress.portfolio_request.liquidity,
            ),
        ),
        "market_snapshot": (
            RevalidationTrigger.MARKET,
            (source.market_snapshot, context.as_of),
        ),
        "signal_evidence": (
            RevalidationTrigger.SIGNAL_EVIDENCE,
            (
                context.signal,
                source.evidence_package,
                basis.stop_request.strategy_invalidation,
            ),
        ),
        "strategy_validation": (
            RevalidationTrigger.STRATEGY_VALIDATION,
            (context.strategy_version, context.validation),
        ),
        "risk_model": (
            RevalidationTrigger.RISK_MODEL,
            (
                source.risk_model_version,
                sizing.model_version,
                basis.stop_request.model_version,
                source.take_profit.model_version,
                source.stress.policy.scenario_model_version,
                source.stress.policy.cost_model_version,
            ),
        ),
        "policy_binding": (
            RevalidationTrigger.POLICY,
            (
                sizing.policy_version,
                sizing.configuration_version,
                sizing.budget_version,
                source.stress.portfolio_request.policy,
                source.accepted_risk_state,
                source.constraints,
                source.assumptions,
                source.human_modifiable_fields,
            ),
        ),
        "entry_price": (RevalidationTrigger.ENTRY, sizing.entry),
        "stop_loss": (
            RevalidationTrigger.STOP_LOSS,
            (sizing.stop, basis.stop_request.stop_loss),
        ),
        "take_profit_targets": (
            RevalidationTrigger.TAKE_PROFIT,
            source.take_profit.targets,
        ),
        "amount_or_size": (
            RevalidationTrigger.AMOUNT_OR_SIZE,
            (sizing.method, sizing.requested_notional, basis.stop_request.quantity),
        ),
        "risk_budget": (
            RevalidationTrigger.RISK_PERCENTAGE,
            (sizing.effective_risk, sizing.equity_fraction),
        ),
        "leverage": (RevalidationTrigger.LEVERAGE, leverage.requested_leverage),
        "margin_mode": (RevalidationTrigger.MARGIN_MODE, leverage.margin_mode),
        "requested_expiry": (RevalidationTrigger.EXPIRY, source.expires_at),
    }


def detect_risk_changes(
    request: RiskRevalidationRequest,
) -> tuple[tuple[RevalidationTrigger, ...], tuple[str, ...]]:
    """Detect supplied material changes without rebuilding unchanged risk."""
    if not isinstance(request, RiskRevalidationRequest):
        raise RiskContractError("request must be RiskRevalidationRequest.")
    old, new = request.original.source, request.replacement
    changed: list[str] = []
    triggers: set[RevalidationTrigger] = set()
    if _risk_digest("material source", _material(old)) != _risk_digest(
        "material source", _material(new)
    ):
        old_groups, new_groups = _groups(old), _groups(new)
        for name in sorted(old_groups):
            trigger, value = new_groups[name]
            if _risk_digest(
                "material group", _material(old_groups[name][1])
            ) != _risk_digest("material group", _material(value)):
                changed.append(name)
                triggers.add(trigger)
        # This includes every other configuration/assumption/evidence edit,
        # even when the descriptive named groups are unchanged. Full inputs
        # remain in the digest; no trade source field is silently discarded.
        changed.append("risk_input_snapshot")
        if not triggers:
            changed.append("calculation_assumptions")
            triggers.add(RevalidationTrigger.POLICY)
    if request.original.proposal.expires_at < new.stress.evaluated_at:
        changed.append("original_proposal.expires_at")
        triggers.add(RevalidationTrigger.EXPIRY)
    return tuple(sorted(triggers, key=lambda value: value.value)), tuple(
        sorted(set(changed))
    )


def _result_digest(
    source: RiskRevalidationRequest, result: RiskRevalidationResult
) -> str:
    return _risk_digest(
        "risk revalidation",
        {
            "source": source,
            "result": {
                f.name: getattr(result, f.name)
                for f in fields(result)
                if f.name != "content_sha256"
            },
        },
    )


@dataclass(frozen=True, slots=True)
class RiskRevalidationSnapshot:
    source: RiskRevalidationRequest
    replacement: RiskProposalSnapshot
    result: RiskRevalidationResult
    prior_risk_invalidated: bool = field(default=True, init=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source, RiskRevalidationRequest)
            or not isinstance(self.replacement, RiskProposalSnapshot)
            or not isinstance(self.result, RiskRevalidationResult)
        ):
            raise RiskContractError(
                "revalidation snapshot requires typed source and outputs."
            )
        if (
            self.replacement.source != self.source.replacement
            or self.result.original_proposal != self.source.original.proposal
            or self.result.replacement_proposal != self.replacement.proposal
            or self.result.content_sha256 != _result_digest(self.source, self.result)
        ):
            raise RiskContractError("REVALIDATION_SNAPSHOT_CONTENT_MISMATCH")


def revalidate_risk_proposal(
    request: RiskRevalidationRequest,
) -> RiskRevalidationSnapshot:
    """Invalidate old research progression and fully rebuild a distinct revision."""
    triggers, changed = detect_risk_changes(request)
    if not triggers:
        raise RiskContractError("RISK_REVALIDATION_NOT_REQUIRED")
    replacement = build_risk_proposal(request.replacement)
    proposal = replacement.proposal
    verdict = proposal.decision.verdict
    status = (
        RevalidationStatus.FAILED
        if verdict is RiskVerdict.REJECT
        else RevalidationStatus.PASSED
        if verdict in {RiskVerdict.PASS, RiskVerdict.PASS_WITH_WARNING}
        else RevalidationStatus.INSUFFICIENT_DATA
    )
    result = RiskRevalidationResult(
        result_id=request.result_id,
        original_proposal=request.original.proposal,
        replacement_proposal=proposal,
        triggers=triggers,
        changed_fields=changed,
        market_snapshot=request.replacement.market_snapshot,
        risk_model_version=proposal.risk_model_version,
        policy_version=proposal.policy_version,
        replacement_assessment=proposal.assessment,
        replacement_decision=proposal.decision,
        status=status,
        reason_codes=tuple(
            dict.fromkeys(
                ("PRIOR_RISK_PROGRESSION_INVALIDATED", *proposal.decision.reason_codes)
            )
        ),
        as_of=proposal.as_of,
        revalidated_at=request.replacement.stress.evaluated_at,
        valid_until=proposal.expires_at,
        content_sha256="0" * 64,
    )
    result = replace(result, content_sha256=_result_digest(request, result))
    return RiskRevalidationSnapshot(request, replacement, result)
