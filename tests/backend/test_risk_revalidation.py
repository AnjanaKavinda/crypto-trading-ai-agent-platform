"""Focused C-083 runtime tests; existing proposal helpers supply coherent evidence."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime
from decimal import ROUND_DOWN, Context, Decimal, localcontext
from uuid import UUID

import pytest
import test_risk_contracts as fixture
import test_risk_proposals as proposals
from trading_platform_api.risk import revalidation as runtime
from trading_platform_api.risk.contracts import (
    MarginMode,
    RevalidationStatus,
    RevalidationTrigger,
    RiskContractError,
    RiskVerdict,
    SnapshotState,
    calculate_position_size,
)
from trading_platform_api.risk.proposals import RiskProposalRequest, build_risk_proposal
from trading_platform_api.risk.revalidation import (
    RiskRevalidationRequest,
    detect_risk_changes,
    revalidate_risk_proposal,
)


def revision(source: RiskProposalRequest | None = None) -> RiskRevalidationRequest:
    source = source or proposals.proposal_request()
    original = build_risk_proposal(source)
    replacement = replace(
        source,
        proposal_id=UUID(int=1140),
        assessment_id=UUID(int=1141),
        decision_id=UUID(int=1142),
        previous_proposal=original.proposal,
    )
    return RiskRevalidationRequest(UUID(int=1143), original, replacement)


def rebind(
    source: RiskProposalRequest,
    *,
    when: datetime | None = None,
    leverage_changes=None,
    stop_changes=None,
    **changes,
):
    """Keep all supplied component bases coherent for changed sizing inputs."""
    old = source.stress.portfolio_request
    lev = old.basis.leverage_request
    sizing = replace(lev.sizing_request, **changes)
    stop = replace(old.basis.stop_request, **(stop_changes or {}))
    if when is not None:
        sizing = replace(sizing, evaluated_at=when)
        stop = replace(stop, evaluated_at=when)
    lev = replace(
        lev,
        sizing_request=sizing,
        evaluated_at=when or lev.evaluated_at,
        **(leverage_changes or {}),
    )
    basis = replace(old.basis, leverage_request=lev, stop_request=stop)
    portfolio = replace(
        old,
        evaluated_at=when or old.evaluated_at,
        basis=basis,
        positions=tuple(replace(x, basis=basis) for x in old.positions),
        proposal=replace(old.proposal, basis=basis),
        scenarios=tuple(replace(x, basis=basis) for x in old.scenarios),
        liquidity=tuple(replace(x, basis=basis) for x in old.liquidity),
        policy=replace(old.policy, basis=basis),
    )
    paths = replace(source.stress.ruin_paths, portfolio_request=portfolio)
    paths = replace(paths, content_sha256=paths.identity_digest())
    stress = replace(
        source.stress,
        evaluated_at=when or source.stress.evaluated_at,
        portfolio_request=portfolio,
        policy=replace(source.stress.policy, portfolio_request=portfolio),
        projections=tuple(
            replace(x, portfolio_request=portfolio) for x in source.stress.projections
        ),
        ruin_paths=paths,
    )
    liquidation = replace(
        source.liquidation,
        evaluated_at=when or source.liquidation.evaluated_at,
        leverage_request=lev,
        estimate=replace(source.liquidation.estimate, basis_request=lev),
    )
    target = replace(
        source.take_profit,
        evaluated_at=when or source.take_profit.evaluated_at,
        context=sizing.context,
        entry_price=sizing.entry,
        stop_loss_request=stop,
        sizing_result=calculate_position_size(sizing),
    )
    return replace(source, stress=stress, liquidation=liquidation, take_profit=target)


def test_rebuild_supersedes_without_mutation_or_authority_and_replays():
    request = revision()
    original = request.original
    request = replace(
        request,
        replacement=replace(
            request.replacement, risk_model_version=fixture.version("model-v2")
        ),
    )
    value = revalidate_risk_proposal(request)
    assert value.result.status is RevalidationStatus.PASSED
    assert value.result.triggers == (RevalidationTrigger.RISK_MODEL,)
    assert value.prior_risk_invalidated is True
    new = value.replacement.proposal
    assert new.supersedes_proposal_id == original.proposal.proposal_id
    assert new.revision == original.proposal.revision + 1
    assert new.proposal_id == request.replacement.proposal_id
    assert value.result.replacement_assessment == new.assessment
    assert value.result.replacement_decision == new.decision
    assert value.result.market_snapshot == request.replacement.market_snapshot
    assert value.result.valid_until == new.expires_at
    assert not new.approved and not new.executable
    assert not value.result.execution_authorized
    assert not new.decision.execution_authorized
    assert request.original == original
    assert original.proposal.revision == 1
    with pytest.raises(FrozenInstanceError):
        original.proposal.revision = 9
    with localcontext(Context(prec=8, rounding=ROUND_DOWN)):
        assert revalidate_risk_proposal(request) == value
    with pytest.raises(RiskContractError, match="CONTENT_MISMATCH"):
        replace(value, result=replace(value.result, content_sha256="f" * 64))


def test_operational_ids_are_noop_and_do_not_invoke_builder(monkeypatch):
    request = revision()
    assert detect_risk_changes(request) == ((), ())

    def forbidden(_):
        pytest.fail("unchanged input must not invoke the proposal builder")

    monkeypatch.setattr(runtime, "build_risk_proposal", forbidden)
    with pytest.raises(RiskContractError, match="RISK_REVALIDATION_NOT_REQUIRED"):
        revalidate_risk_proposal(request)


def test_calculation_clock_only_is_noop_until_expiry():
    request = revision()
    request = replace(
        request, replacement=rebind(request.replacement, when=fixture.T[5])
    )
    assert detect_risk_changes(request) == ((), ())


def test_expiry_is_strict_and_triggers_full_current_rebuild():
    request = revision(replace(proposals.proposal_request(), expires_at=fixture.T[4]))
    assert detect_risk_changes(request) == ((), ())  # equality remains current
    replacement = rebind(
        replace(request.replacement, expires_at=fixture.T[8]), when=fixture.T[5]
    )
    request = replace(request, replacement=replacement)
    triggers, changed = detect_risk_changes(request)
    assert RevalidationTrigger.EXPIRY in triggers
    assert "original_proposal.expires_at" in changed
    value = revalidate_risk_proposal(request)
    assert value.result.status is RevalidationStatus.PASSED
    assert value.result.revalidated_at == fixture.T[5]
    assert value.result.valid_until > request.original.proposal.expires_at


@pytest.mark.parametrize("kind", ["reject", "unknown", "warning"])
def test_new_verdict_dominates_original_and_retains_reasons(kind):
    request = revision(proposals.proposal_request(warning=kind == "warning"))
    new = replace(request.replacement, risk_model_version=fixture.version("model-v2"))
    if kind == "reject":
        projections = new.stress.projections
        new = replace(
            new,
            stress=replace(
                new.stress,
                projections=(
                    replace(projections[0], projected_loss=fixture.money("2000")),
                    *projections[1:],
                ),
            ),
        )
    elif kind == "unknown":
        new = replace(
            new, evidence_package=replace(new.evidence_package, content_sha256=None)
        )
    value = revalidate_risk_proposal(replace(request, replacement=new))
    verdict, status = {
        "reject": (RiskVerdict.REJECT, RevalidationStatus.FAILED),
        "unknown": (
            RiskVerdict.INSUFFICIENT_DATA,
            RevalidationStatus.INSUFFICIENT_DATA,
        ),
        "warning": (RiskVerdict.PASS_WITH_WARNING, RevalidationStatus.PASSED),
    }[kind]
    assert value.replacement.proposal.decision.verdict is verdict
    assert value.result.status is status
    assert set(value.replacement.proposal.decision.reason_codes) <= set(
        value.result.reason_codes
    )
    assert "PRIOR_RISK_PROGRESSION_INVALIDATED" in value.result.reason_codes
    assert not value.result.execution_authorized


@pytest.mark.parametrize(
    "field,trigger",
    [
        ("market_snapshot", RevalidationTrigger.MARKET),
        ("evidence_package", RevalidationTrigger.SIGNAL_EVIDENCE),
        ("risk_model_version", RevalidationTrigger.RISK_MODEL),
        ("constraints", RevalidationTrigger.POLICY),
        ("expires_at", RevalidationTrigger.EXPIRY),
    ],
)
def test_direct_material_groups(field, trigger):
    request = revision()
    old = getattr(request.replacement, field)
    value = (
        replace(old, content_sha256="b" * 64)
        if field.endswith("snapshot") or field == "evidence_package"
        else fixture.version("model-v2")
        if field == "risk_model_version"
        else (*old, "Supplied policy change")
        if field == "constraints"
        else fixture.T[7]
    )
    request = replace(
        request, replacement=replace(request.replacement, **{field: value})
    )
    assert trigger in detect_risk_changes(request)[0]


@pytest.mark.parametrize(
    "field,trigger",
    [
        ("entry", RevalidationTrigger.ENTRY),
        ("stop", RevalidationTrigger.STOP_LOSS),
        ("effective_risk", RevalidationTrigger.RISK_PERCENTAGE),
        ("account", RevalidationTrigger.ACCOUNT),
        ("portfolio", RevalidationTrigger.PORTFOLIO),
        ("context", RevalidationTrigger.STRATEGY_VALIDATION),
        ("volatility_version", RevalidationTrigger.POLICY),
    ],
)
def test_nested_changes_never_disappear(field, trigger):
    request = revision()
    sizing = request.replacement.stress.portfolio_request.basis.leverage_request.sizing_request
    value = {
        "entry": fixture.price("101"),
        "stop": fixture.price("89"),
        "effective_risk": fixture.money("121"),
        "account": replace(sizing.account, content_sha256="b" * 64),
        "portfolio": replace(sizing.portfolio, content_sha256="b" * 64),
        "context": replace(
            sizing.context,
            validation=replace(sizing.context.validation, content_sha256="b" * 64),
        ),
        "volatility_version": fixture.version("new-volatility-assumption"),
    }[field]
    replacement = rebind(request.replacement, **{field: value})
    triggers, changed = detect_risk_changes(replace(request, replacement=replacement))
    assert trigger in triggers
    assert "risk_input_snapshot" in changed


def test_exact_previous_proposal_and_result_identity_required():
    request = revision()
    with pytest.raises(RiskContractError, match="PREVIOUS_PROPOSAL_MISMATCH"):
        replace(
            request, replacement=replace(request.replacement, previous_proposal=None)
        )
    with pytest.raises(RiskContractError, match="RESULT_ID_COLLISION"):
        replace(request, result_id=request.replacement.proposal_id)


def test_unrelated_account_and_backdated_evaluation_rejected():
    request = revision()
    sizing = request.replacement.stress.portfolio_request.basis.leverage_request.sizing_request
    new = rebind(
        request.replacement, account=replace(sizing.account, account_id=UUID(int=999))
    )
    with pytest.raises(RiskContractError, match="UNRELATED_ACCOUNT_OR_TRADE"):
        replace(request, replacement=new)
    context = replace(sizing.context, instrument_id="UNRELATED-INSTRUMENT")
    new = rebind(request.replacement, context=context)
    with pytest.raises(RiskContractError, match="UNRELATED_ACCOUNT_OR_TRADE"):
        replace(request, replacement=new)
    new = rebind(request.replacement, when=fixture.T[3])
    with pytest.raises(RiskContractError, match="TIME_PRECEDES_ORIGINAL"):
        replace(request, replacement=new)


def test_missing_essential_evidence_remains_explicit_contract_error():
    request = revision()
    sizing = request.replacement.stress.portfolio_request.basis.leverage_request.sizing_request
    new = rebind(
        request.replacement,
        account=replace(
            sizing.account,
            state=SnapshotState.UNAVAILABLE,
            reason_codes=("MISSING_EQUITY",),
            equity=None,
        ),
    )
    request = replace(request, replacement=new)
    with pytest.raises(RiskContractError):
        revalidate_risk_proposal(request)


@pytest.mark.parametrize(
    "change,trigger",
    [
        ("leverage", RevalidationTrigger.LEVERAGE),
        ("margin", RevalidationTrigger.MARGIN_MODE),
        ("quantity", RevalidationTrigger.AMOUNT_OR_SIZE),
        ("target", RevalidationTrigger.TAKE_PROFIT),
    ],
)
def test_trade_parameter_changes_trigger_revalidation(change, trigger):
    request = revision()
    new = request.replacement
    if change == "leverage":
        new = rebind(new, leverage_changes={"requested_leverage": Decimal("4")})
    elif change == "margin":
        new = rebind(new, leverage_changes={"margin_mode": MarginMode.CROSS})
    elif change == "quantity":
        new = rebind(new, stop_changes={"quantity": Decimal("11")})
    else:
        target = replace(new.take_profit.targets[0], price=fixture.price("125"))
        new = replace(new, take_profit=replace(new.take_profit, targets=(target,)))
    assert trigger in detect_risk_changes(replace(request, replacement=new))[0]


def test_invalid_ruin_binding_cannot_be_normalized_away():
    request = revision()
    paths = replace(request.replacement.stress.ruin_paths, content_sha256="b" * 64)
    new = replace(
        request.replacement,
        stress=replace(request.replacement.stress, ruin_paths=paths),
    )
    with pytest.raises(RiskContractError, match="RUIN_PATH_DIGEST_MISMATCH"):
        revalidate_risk_proposal(replace(request, replacement=new))
