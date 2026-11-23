"""Focused proposal assembly tests, reusing the existing component fixtures."""

from dataclasses import FrozenInstanceError, replace
from decimal import ROUND_DOWN, Context, Decimal, localcontext
from uuid import UUID

import pytest
import test_risk_contracts as fixture
from trading_platform_api.risk.contracts import (
    RiskCheckOutcome,
    RiskContractError,
    RiskPolicyMode,
    RiskState,
    RiskVerdict,
    calculate_position_size,
    calculate_stop_loss_assessment,
)
from trading_platform_api.risk.proposals import (
    RiskProposalRequest,
    build_risk_proposal,
)


def proposal_request(
    *,
    warning: bool = False,
    gap: str = "0",
    mode: RiskPolicyMode = RiskPolicyMode.RESEARCH,
) -> RiskProposalRequest:
    stress = fixture.stress_assessment_request(warning=warning)
    old = stress.portfolio_request
    sizing = replace(old.basis.leverage_request.sizing_request, mode=mode)
    lev = replace(old.basis.leverage_request, sizing_request=sizing)
    stop = replace(old.basis.stop_request, adverse_gap_displacement=Decimal(gap))
    basis = replace(old.basis, leverage_request=lev, stop_request=stop)
    loss = calculate_stop_loss_assessment(stop).maximum_loss
    portfolio = replace(
        old,
        basis=basis,
        positions=tuple(replace(x, basis=basis) for x in old.positions),
        proposal=replace(old.proposal, basis=basis, open_risk=loss),
        scenarios=tuple(replace(x, basis=basis) for x in old.scenarios),
        liquidity=tuple(replace(x, basis=basis) for x in old.liquidity),
        policy=replace(old.policy, basis=basis),
    )
    paths = replace(stress.ruin_paths, portfolio_request=portfolio)
    paths = replace(paths, content_sha256=paths.identity_digest())
    stress = replace(
        stress,
        portfolio_request=portfolio,
        policy=replace(stress.policy, portfolio_request=portfolio),
        projections=tuple(
            replace(x, portfolio_request=portfolio) for x in stress.projections
        ),
        ruin_paths=paths,
    )
    liquidation = fixture.liquidation_assessment_request(
        leverage_overrides={"sizing_request": sizing}
    )
    liquidation = replace(
        liquidation,
        leverage_request=lev,
        estimate=replace(liquidation.estimate, basis_request=lev),
    )
    target = fixture.take_profit_assessment_request(stop_request=stop)
    target = replace(target, sizing_result=calculate_position_size(sizing))
    return RiskProposalRequest(
        UUID(int=113),
        UUID(int=1131),
        UUID(int=1132),
        stress,
        liquidation,
        target,
        fixture.ref("C-024"),
        fixture.ref("C-002"),
        fixture.version("proposal-model-v1"),
        RiskState.MODERATE_RISK,
        fixture.T[8],
        ("Caller-supplied research policy.",),
        (fixture.version("proposal-assumptions"),),
        ("entry_price", "stop_loss", "leverage"),
    )


def test_proposal_builder_recomputes_exact_financial_fields_and_snapshots() -> None:
    source = proposal_request()
    snapshot = build_risk_proposal(source)
    value = snapshot.proposal
    assert value.decision.verdict is RiskVerdict.PASS
    assert value.position_size == Decimal("10")
    assert value.maximum_loss == fixture.money("120")
    assert value.maximum_loss == value.assessment.stop_loss.maximum_loss
    assert value.expected_profit == fixture.money("180")
    assert value.risk_reward_ratio == Decimal("1.5")
    assert value.account_risk.value == Decimal("0.012")
    assert value.portfolio_risk.value == Decimal("0.013")
    assert value.expires_at == fixture.T[8]
    assert value.approved is False and value.executable is False
    assert value.decision.execution_authorized is False
    assert snapshot.trade_snapshot is source
    assert (
        snapshot.account_snapshot
        is source.stress.portfolio_request.basis.leverage_request.sizing_request.account
    )
    assert (
        snapshot.portfolio_snapshot
        is source.stress.portfolio_request.basis.leverage_request.sizing_request.portfolio
    )
    assert "NO_EXECUTION_AUTHORITY" in value.constraints
    assert len({x.limit_id for x in value.assessment.limits}) == len(
        value.assessment.limits
    )


def test_proposal_snapshot_replays_deterministically_and_rejects_content_substitution() -> (
    None
):
    source = proposal_request()
    snapshot = build_risk_proposal(source)
    assert build_risk_proposal(snapshot.source) == snapshot
    with localcontext(Context(prec=3, rounding=ROUND_DOWN)):
        assert build_risk_proposal(source) == snapshot
    changed = replace(source, constraints=("Changed policy constraint.",))
    assert (
        build_risk_proposal(changed).proposal.content_sha256
        != snapshot.proposal.content_sha256
    )
    with pytest.raises(RiskContractError, match="SNAPSHOT_CONTENT_MISMATCH"):
        replace(snapshot, source=changed)
    with pytest.raises(FrozenInstanceError):
        snapshot.proposal.approved = True
    with pytest.raises(FrozenInstanceError):
        snapshot.account_snapshot.equity = fixture.money("1")


def test_proposal_revisions_rebuild_without_mutating_history() -> None:
    source = proposal_request()
    first = build_risk_proposal(source)
    previous_hash = first.proposal.content_sha256
    second = build_risk_proposal(
        replace(
            source,
            proposal_id=UUID(int=1133),
            assessment_id=UUID(int=1134),
            decision_id=UUID(int=1135),
            previous_proposal=first.proposal,
        )
    )
    assert (
        first.proposal.revision == 1 and first.proposal.content_sha256 == previous_hash
    )
    assert second.proposal.revision == 2
    assert second.proposal.supersedes_proposal_id == first.proposal.proposal_id
    assert second.proposal.content_sha256 != previous_hash
    assert second.proposal.approved is False and second.proposal.executable is False
    for field in ("assessment_id", "decision_id"):
        with pytest.raises(RiskContractError, match="new assessment and decision"):
            replace(second.source, **{field: getattr(source, field)})
    with pytest.raises(RiskContractError, match="new proposal identity"):
        replace(source, previous_proposal=first.proposal)


def test_proposal_warning_does_not_become_clean_pass() -> None:
    value = build_risk_proposal(proposal_request(warning=True)).proposal
    assert value.assessment.outcome is RiskCheckOutcome.WARNING
    assert value.decision.verdict is RiskVerdict.PASS_WITH_WARNING
    assert value.warnings and value.decision.soft_warning_ids


def test_proposal_hard_failure_dominates_missing_provenance_and_warning() -> None:
    source = proposal_request(warning=True)
    stress = replace(
        source.stress,
        projections=(
            replace(source.stress.projections[0], projected_loss=fixture.money("2000")),
            *source.stress.projections[1:],
        ),
    )
    source = replace(
        source,
        stress=stress,
        evidence_package=replace(source.evidence_package, content_sha256=None),
    )
    value = build_risk_proposal(source).proposal
    assert value.assessment.outcome is RiskCheckOutcome.FAILED
    assert value.decision.verdict is RiskVerdict.REJECT
    assert value.decision.hard_breach_ids and value.warnings
    assert any(
        x.startswith("C-081/") and x.endswith("/loss")
        for x in value.decision.hard_breach_ids
    )
    assert value.expires_at == source.stress.evaluated_at


@pytest.mark.parametrize("missing", ["evidence", "market", "liquidation", "stress"])
def test_proposal_missing_evidence_cannot_pass(missing: str) -> None:
    source = proposal_request()
    if missing == "evidence":
        source = replace(
            source,
            evidence_package=replace(source.evidence_package, content_sha256=None),
        )
    elif missing == "market":
        source = replace(
            source, market_snapshot=replace(source.market_snapshot, valid_until=None)
        )
    elif missing == "liquidation":
        source = replace(source, liquidation=replace(source.liquidation, estimate=None))
    else:
        source = replace(source, stress=replace(source.stress, ruin_paths=None))
    value = build_risk_proposal(source).proposal
    assert value.assessment.outcome is RiskCheckOutcome.INSUFFICIENT_DATA
    assert value.decision.verdict is RiskVerdict.INSUFFICIENT_DATA
    assert value.decision.reason_codes
    assert value.executable is False


@pytest.mark.parametrize("schema", ["1", "2"])
def test_proposal_evidence_versions_and_exact_expiry_boundary(schema: str) -> None:
    source = proposal_request()
    source = replace(
        source,
        evidence_package=replace(
            source.evidence_package, schema_version=schema, valid_until=fixture.T[4]
        ),
    )
    value = build_risk_proposal(source).proposal
    assert value.decision.verdict is RiskVerdict.PASS
    assert value.expires_at == fixture.T[4]
    stale = build_risk_proposal(
        replace(
            source,
            evidence_package=replace(source.evidence_package, valid_until=fixture.T[3]),
        )
    ).proposal
    assert stale.decision.verdict is RiskVerdict.INSUFFICIENT_DATA
    unsupported = build_risk_proposal(
        replace(
            source,
            evidence_package=replace(source.evidence_package, schema_version="999"),
        )
    ).proposal
    assert unsupported.decision.verdict is RiskVerdict.REJECT


@pytest.mark.parametrize(
    "field", ["approved", "executable", "content_sha256", "risk_model_version"]
)
def test_proposal_whitelist_cannot_edit_authority_or_provenance(field: str) -> None:
    with pytest.raises(RiskContractError, match="EDITABLE_FIELDS_INVALID"):
        replace(proposal_request(), human_modifiable_fields=(field,))


def test_proposal_rejects_substituted_basis_sizing_and_incompatible_loss() -> None:
    source = proposal_request()
    with pytest.raises(RiskContractError, match="INPUT_BASIS_MISMATCH"):
        replace(
            source,
            liquidation=replace(source.liquidation, stop_loss=fixture.price("85")),
        )
    forged = replace(source.take_profit.sizing_result, content_sha256="b" * 64)
    with pytest.raises(RiskContractError, match="TAKE_PROFIT_SIZING_MISMATCH"):
        build_risk_proposal(
            replace(
                source, take_profit=replace(source.take_profit, sizing_result=forged)
            )
        )
    with pytest.raises(RiskContractError, match="LOSS_BASIS_MISMATCH"):
        build_risk_proposal(proposal_request(gap="0.25"))
    with pytest.raises(RiskContractError, match="RESEARCH_MODE_REQUIRED"):
        proposal_request(mode=RiskPolicyMode.LIVE_SUPERVISED)
