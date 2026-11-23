"""Pure research proposal assembly over existing deterministic risk calculators."""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Context, DecimalException, Inexact, localcontext
from typing import TypeVar
from uuid import UUID

from trading_platform_api.risk.contracts import (
    AccountSnapshot,
    ContractReference,
    LiquidationAssessmentRequest,
    PortfolioSnapshot,
    RiskAssessment,
    RiskCheckOutcome,
    RiskContractError,
    RiskDecision,
    RiskLimitSeverity,
    RiskPolicyMode,
    RiskProposal,
    RiskState,
    RiskVerdict,
    StressAssessmentRequest,
    TakeProfitAssessmentRequest,
    VersionReference,
    _hard_failure,
    _risk_digest,
    _text_tuple,
    _time,
    _typed_tuple,
    _uuid,
    calculate_leverage_assessment,
    calculate_liquidation_assessment,
    calculate_portfolio_impact,
    calculate_position_size,
    calculate_stop_loss_assessment,
    calculate_stress_assessment,
    calculate_take_profit_assessment,
)

_T = TypeVar("_T")


def _required(value: _T | None, name: str) -> _T:
    if value is None:
        raise RiskContractError("PROPOSAL_ESSENTIAL_EVIDENCE_MISSING:" + name)
    return value


_EDITABLE = frozenset(
    {
        "entry_price",
        "stop_loss",
        "take_profit_targets",
        "position_size",
        "leverage",
        "margin_mode",
    }
)
_CONSTRAINTS = (
    "OFFLINE_RESEARCH_ONLY",
    "RISK_ACCEPTANCE_IS_NOT_HUMAN_APPROVAL",
    "NO_EXECUTION_AUTHORITY",
)


@dataclass(frozen=True, slots=True)
class RiskProposalRequest:
    proposal_id: UUID
    assessment_id: UUID
    decision_id: UUID
    stress: StressAssessmentRequest
    liquidation: LiquidationAssessmentRequest
    take_profit: TakeProfitAssessmentRequest
    evidence_package: ContractReference
    market_snapshot: ContractReference
    risk_model_version: VersionReference
    accepted_risk_state: RiskState
    expires_at: datetime
    constraints: tuple[str, ...]
    assumptions: tuple[VersionReference, ...]
    human_modifiable_fields: tuple[str, ...]
    previous_proposal: RiskProposal | None = None

    def __post_init__(self) -> None:
        for name in ("proposal_id", "assessment_id", "decision_id"):
            _uuid(name, getattr(self, name))
        for name, kind in (
            ("stress", StressAssessmentRequest),
            ("liquidation", LiquidationAssessmentRequest),
            ("take_profit", TakeProfitAssessmentRequest),
            ("risk_model_version", VersionReference),
        ):
            if not isinstance(getattr(self, name), kind):
                raise RiskContractError(f"{name} has an invalid type.")
        for name, expected in (
            ("evidence_package", "C-024"),
            ("market_snapshot", "C-002"),
        ):
            reference = getattr(self, name)
            if (
                not isinstance(reference, ContractReference)
                or reference.contract_id != expected
            ):
                raise RiskContractError(f"{name} must reference {expected}.")
        basis = self.stress.portfolio_request.basis
        sizing = basis.leverage_request.sizing_request
        if sizing.mode is not RiskPolicyMode.RESEARCH:
            raise RiskContractError("PROPOSAL_RESEARCH_MODE_REQUIRED")
        if (
            self.liquidation.leverage_request != basis.leverage_request
            or self.liquidation.stop_loss != basis.stop_request.stop_loss
            or self.take_profit.stop_loss_request != basis.stop_request
            or self.take_profit.context != sizing.context
            or self.take_profit.entry_price != sizing.entry
            or self.liquidation.evaluated_at != self.stress.evaluated_at
            or self.take_profit.evaluated_at != self.stress.evaluated_at
        ):
            raise RiskContractError("PROPOSAL_INPUT_BASIS_MISMATCH")
        if not isinstance(
            self.accepted_risk_state, RiskState
        ) or self.accepted_risk_state not in {
            RiskState.LOW_RISK,
            RiskState.MODERATE_RISK,
        }:
            raise RiskContractError(
                "accepted_risk_state requires an explicit bounded policy label."
            )
        expires = _time("expires_at", self.expires_at)
        if expires < self.stress.evaluated_at:
            raise RiskContractError("requested proposal expiry precedes evaluation.")
        object.__setattr__(self, "expires_at", expires)
        _text_tuple("constraints", self.constraints, empty=False)
        _typed_tuple("assumptions", self.assumptions, VersionReference, empty=False)
        editable = _text_tuple(
            "human_modifiable_fields", self.human_modifiable_fields, empty=False
        )
        if len(set(editable)) != len(editable) or not set(editable).issubset(_EDITABLE):
            raise RiskContractError("PROPOSAL_EDITABLE_FIELDS_INVALID")
        if self.previous_proposal is not None:
            if not isinstance(self.previous_proposal, RiskProposal):
                raise RiskContractError(
                    "previous_proposal must be RiskProposal or None."
                )
            if self.previous_proposal.proposal_id == self.proposal_id:
                raise RiskContractError("a revision requires a new proposal identity.")
            if (
                self.previous_proposal.assessment.assessment_id == self.assessment_id
                or self.previous_proposal.decision.decision_id == self.decision_id
            ):
                raise RiskContractError(
                    "a revision requires new assessment and decision identities."
                )


def _proposal_digest(source: RiskProposalRequest, proposal: RiskProposal) -> str:
    return _risk_digest(
        "risk proposal snapshot",
        {
            "source": source,
            "proposal": {
                f.name: getattr(proposal, f.name)
                for f in fields(proposal)
                if f.name != "content_sha256"
            },
        },
    )


@dataclass(frozen=True, slots=True)
class RiskProposalSnapshot:
    """Nonpersisted replay bundle; canonical contracts remain unchanged."""

    source: RiskProposalRequest
    proposal: RiskProposal

    def __post_init__(self) -> None:
        if not isinstance(self.source, RiskProposalRequest) or not isinstance(
            self.proposal, RiskProposal
        ):
            raise RiskContractError(
                "snapshot requires a typed source and C-034 proposal."
            )
        if (
            self.source.proposal_id != self.proposal.proposal_id
            or self.proposal.content_sha256
            != _proposal_digest(self.source, self.proposal)
        ):
            raise RiskContractError("PROPOSAL_SNAPSHOT_CONTENT_MISMATCH")

    @property
    def account_snapshot(self) -> AccountSnapshot:
        return self.source.stress.portfolio_request.basis.leverage_request.sizing_request.account

    @property
    def portfolio_snapshot(self) -> PortfolioSnapshot:
        return self.source.stress.portfolio_request.basis.leverage_request.sizing_request.portfolio

    @property
    def trade_snapshot(self) -> RiskProposalRequest:
        return self.source


def build_risk_proposal(request: RiskProposalRequest) -> RiskProposalSnapshot:
    """Recompute supplied research inputs; never approve or authorize execution."""
    if not isinstance(request, RiskProposalRequest):
        raise RiskContractError("request must be RiskProposalRequest.")
    try:
        with localcontext(Context(prec=34, rounding=ROUND_HALF_EVEN)) as arithmetic:
            arithmetic.traps[Inexact] = True
            return _build_risk_proposal(request)
    except DecimalException as error:
        raise RiskContractError(
            "proposal arithmetic cannot be represented safely at precision 34."
        ) from error


def _build_risk_proposal(request: RiskProposalRequest) -> RiskProposalSnapshot:
    portfolio_request = request.stress.portfolio_request
    basis = portfolio_request.basis
    sizing_request = basis.leverage_request.sizing_request
    # C-080's explicit essential-evidence rejection is preserved, not replaced
    # with invented mandatory C-034 amounts or synthetic exposure buckets.
    portfolio = calculate_portfolio_impact(portfolio_request)
    sizing = calculate_position_size(sizing_request)
    if request.take_profit.sizing_result != sizing:
        raise RiskContractError("PROPOSAL_TAKE_PROFIT_SIZING_MISMATCH")
    leverage = calculate_leverage_assessment(basis.leverage_request)
    liquidation = calculate_liquidation_assessment(request.liquidation)
    stop = calculate_stop_loss_assessment(basis.stop_request)
    target = calculate_take_profit_assessment(request.take_profit)
    stress = calculate_stress_assessment(request.stress)
    quantity = _required(sizing.recommended_quantity, "quantity")
    notional = _required(sizing.recommended_notional, "notional")
    margin = _required(sizing.recommended_margin, "margin")
    maximum_loss = _required(sizing.maximum_loss, "maximum_loss")
    account_risk = _required(sizing.account_risk, "account_risk")
    portfolio_risk = _required(portfolio.post_trade_risk, "portfolio_risk")
    stop_price = _required(stop.stop_loss, "stop_price")
    if _required(stop.maximum_loss, "stop_maximum_loss") != maximum_loss:
        raise RiskContractError("PROPOSAL_STOP_SIZING_LOSS_BASIS_MISMATCH")
    components = (sizing, leverage, liquidation, stop, target, portfolio, stress)
    limits = tuple(
        replace(limit, limit_id=f"{component.contract_id}/{limit.limit_id}")
        for component in (leverage, stop, portfolio)
        for limit in component.limits
    )
    hard = [item.limit_id for item in limits if _hard_failure((item,))]
    hard.extend(f"C-081/{identity}" for identity in stress.breached_limit_ids)
    hard.extend(
        f"{x.contract_id}/{x.result_id}"
        for x in components
        if x.outcome is RiskCheckOutcome.FAILED
    )
    warnings = [
        f"{x.contract_id}:{reason}"
        for x in components
        if x.outcome is RiskCheckOutcome.WARNING
        for reason in x.reason_codes
    ]
    warnings.extend(
        item.limit_id
        for item in limits
        if item.severity is RiskLimitSeverity.SOFT
        and item.outcome
        not in {RiskCheckOutcome.PASSED, RiskCheckOutcome.NOT_APPLICABLE}
    )
    reasons = [
        f"{x.contract_id}:{reason}" for x in components for reason in x.reason_codes
    ]
    insufficient = any(
        x.outcome
        not in {
            RiskCheckOutcome.PASSED,
            RiskCheckOutcome.WARNING,
            RiskCheckOutcome.FAILED,
        }
        for x in components
    )
    context = sizing.context
    references = (
        context.signal,
        context.validation,
        context.strategy_version,
        context.account_snapshot,
        context.portfolio_snapshot,
        request.evidence_package,
        request.market_snapshot,
    )
    expiries = [request.expires_at, *(x.valid_until for x in components)]
    for reference in references:
        supported = (
            {"1", "2"}
            if reference.contract_id in {"C-070", "C-028", "C-021", "C-024"}
            else {"1"}
        )
        label = f"{reference.contract_id}/{reference.entity_id}"
        if reference.schema_version not in supported:
            hard.append("reference/" + label)
            reasons.append("PROPOSAL_REFERENCE_SCHEMA_UNSUPPORTED:" + label)
        if reference.content_sha256 is None or reference.valid_until is None:
            insufficient = True
            reasons.append("PROPOSAL_REFERENCE_PROVENANCE_MISSING:" + label)
        elif reference.valid_until < request.stress.evaluated_at:
            insufficient = True
            reasons.append("PROPOSAL_REFERENCE_EXPIRED:" + label)
        if reference.valid_until is not None:
            expiries.append(reference.valid_until)
    outcome = (
        RiskCheckOutcome.FAILED
        if hard
        else RiskCheckOutcome.INSUFFICIENT_DATA
        if insufficient
        else RiskCheckOutcome.WARNING
        if warnings
        else RiskCheckOutcome.PASSED
    )
    state = (
        RiskState.REJECTED
        if hard
        else RiskState.INSUFFICIENT_DATA
        if insufficient
        else RiskState.MODERATE_RISK
        if warnings
        else request.accepted_risk_state
    )
    verdict = {
        RiskCheckOutcome.FAILED: RiskVerdict.REJECT,
        RiskCheckOutcome.INSUFFICIENT_DATA: RiskVerdict.INSUFFICIENT_DATA,
        RiskCheckOutcome.WARNING: RiskVerdict.PASS_WITH_WARNING,
        RiskCheckOutcome.PASSED: RiskVerdict.PASS,
    }[outcome]
    evaluated = request.stress.evaluated_at
    valid = max(evaluated, min(expiries))
    if outcome in {RiskCheckOutcome.FAILED, RiskCheckOutcome.INSUFFICIENT_DATA}:
        valid = evaluated
    if outcome is not RiskCheckOutcome.PASSED and not reasons:
        reasons.append("PROPOSAL_COMPONENTS_NOT_PASSED")
    reasons_value = tuple(dict.fromkeys(reasons))
    warnings_value = tuple(dict.fromkeys(warnings))
    constraints = tuple(dict.fromkeys((*_CONSTRAINTS, *request.constraints)))
    assumptions = tuple(
        dict.fromkeys((*request.assumptions, *(x.model_version for x in components)))
    )
    assessment = RiskAssessment(
        assessment_id=request.assessment_id,
        context=context,
        position_sizing=sizing,
        leverage=leverage,
        liquidation=liquidation,
        stop_loss=stop,
        take_profit=target,
        portfolio_impact=portfolio,
        stress_test=stress,
        limits=limits,
        warnings=warnings_value,
        constraints=constraints,
        assumptions=assumptions,
        risk_state=state,
        outcome=outcome,
        reason_codes=reasons_value,
        risk_model_version=request.risk_model_version,
        policy_version=sizing_request.policy_version,
        as_of=context.as_of,
        evaluated_at=evaluated,
        valid_until=valid,
        content_sha256="0" * 64,
    )
    assessment = replace(
        assessment,
        content_sha256=_risk_digest(
            "risk assessment",
            {
                "source": request,
                "assessment": {
                    f.name: getattr(assessment, f.name)
                    for f in fields(assessment)
                    if f.name != "content_sha256"
                },
            },
        ),
    )
    decision = RiskDecision(
        decision_id=request.decision_id,
        proposal_id=request.proposal_id,
        assessment=assessment,
        verdict=verdict,
        risk_state=state,
        hard_breach_ids=tuple(sorted(set(hard))),
        soft_warning_ids=tuple(sorted(set(warnings))),
        reason_codes=reasons_value,
        risk_model_version=request.risk_model_version,
        policy_version=sizing_request.policy_version,
        as_of=context.as_of,
        decided_at=evaluated,
        valid_until=valid,
    )
    proposal = RiskProposal(
        proposal_id=request.proposal_id,
        revision=1
        if request.previous_proposal is None
        else request.previous_proposal.revision + 1,
        supersedes_proposal_id=None
        if request.previous_proposal is None
        else request.previous_proposal.proposal_id,
        context=context,
        evidence_package=request.evidence_package,
        entry_price=sizing_request.entry,
        stop_loss=stop_price,
        take_profit_targets=target.targets,
        position_size=quantity,
        notional_value=notional,
        position_sizing=sizing,
        margin_required=margin,
        leverage=_required(leverage.requested_leverage, "leverage"),
        margin_mode=leverage.margin_mode,
        maximum_loss=maximum_loss,
        expected_profit=target.expected_profit,
        risk_reward_ratio=target.risk_reward_ratio,
        account_risk=account_risk,
        portfolio_risk=portfolio_risk,
        liquidation=liquidation,
        portfolio_impact=portfolio,
        stress_test=stress,
        assessment=assessment,
        decision=decision,
        warnings=warnings_value,
        constraints=constraints,
        assumptions=assumptions,
        human_modifiable_fields=request.human_modifiable_fields,
        risk_model_version=request.risk_model_version,
        policy_version=sizing_request.policy_version,
        configuration_version=sizing_request.configuration_version,
        as_of=context.as_of,
        created_at=evaluated,
        expires_at=valid,
        content_sha256="0" * 64,
    )
    proposal = replace(proposal, content_sha256=_proposal_digest(request, proposal))
    return RiskProposalSnapshot(request, proposal)
