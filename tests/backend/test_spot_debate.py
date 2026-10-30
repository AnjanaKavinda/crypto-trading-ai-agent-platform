import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from trading_platform_api.agents.contracts import (
    AgentEvaluation,
    AgentEvaluationOutcome,
    AgentResult,
    AgentResultStatus,
    ModelAvailability,
    ModelCapabilityTier,
    ModelRoutingDecision,
)
from trading_platform_api.agents.result_validation import AgentResultExpectation
from trading_platform_api.analysis.contracts import (
    AnalyticalDirection,
    AnalyticalUncertainty,
    AssessmentStatus,
    EvidenceRelation,
    FundamentalAssessment,
    ResolutionStatus,
    UncertaintyCategory,
    VersionReference,
)
from trading_platform_api.analysis.spot_adversarial import (
    SpotAdversarialDraft,
    build_spot_market_context_v5,
)
from trading_platform_api.analysis.spot_meta_analysis import (
    C093Registry,
    ConflictMaterialityV2,
    FindingReadiness,
    SpotMetaFinding,
    calculate_spot_conflicts_v3,
    calculate_spot_confluence_v3,
)
from trading_platform_api.analysis.versioned_contracts import (
    AdversarialAssessment,
    AnalyticalConfidenceReasonV2,
    AnalyticalConfidenceStateV2,
    AnalyticalConfidenceV2,
    ConfluenceEvidenceStrengthV2,
    ConfluenceReasonV2,
    ConfluenceStateV2,
    ConfluenceStatusV2,
    EvidenceDependenceV2,
    EvidenceItemV2,
)
from trading_platform_api.analysis.versioned_contracts_v4 import (
    AnalysisOutputReferenceV4,
    AnalysisSnapshotReferenceV4,
    ConfluenceAssessmentV3,
    ConfluenceComponentV2,
    MarketContextV4,
    create_analysis_snapshot_v4,
    resolve_analysis_snapshot_v4,
)
from trading_platform_api.analysis.versioned_contracts_v5 import MarketContextV5
from trading_platform_api.config import DeploymentEnvironment, OperatingMode
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.market_data import (
    DataSourceRecord,
    MarketData,
    MarketSnapshot,
    MetricValue,
    ProviderBatch,
    ProviderBatchStatus,
    ProviderDataKind,
    assess_complete_binance_spot_batch,
)
from trading_platform_api.orchestration.spot_debate import (
    SpotDebateConclusion,
    SpotDebateError,
    _conclusion,
    _thesis_branches,
    compose_spot_debate,
)
from trading_platform_api.orchestration.spot_market_thesis import (
    SpotMarketThesisError,
    ThesisAssumptionState,
    ThesisCaseState,
    ThesisInvalidationState,
    _case,
    compose_spot_market_thesis,
)
from trading_platform_api.orchestration.spot_request_handoff import (
    build_spot_analysis_manifest,
)
from trading_platform_api.orchestration.spot_results import (
    build_spot_result_graph,
    run_spot_result_graph,
)
from trading_platform_api.spot_research import approved_quality_policy_template

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


@dataclass(frozen=True)
class DebateEnvelope:
    result: AgentResult
    expectation: AgentResultExpectation
    evaluation: AgentEvaluation
    context: MarketContextV5
    manifest: object
    resolved: tuple[object, ...]
    evidence: dict[UUID, EvidenceItemV2]
    independence: object
    supported_adversarial_versions: tuple[VersionReference, ...]
    correlation_id: UUID
    trace_id: UUID


def _id(number: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{number:012d}")


def _envelope(
    status: AgentResultStatus = AgentResultStatus.COMPLETE,
    *,
    missing_bearish: bool = False,
) -> DebateEnvelope:
    step = timedelta(minutes=1)
    start = NOW - timedelta(minutes=50)
    observations: list[MarketData] = []
    sources: list[DataSourceRecord] = []
    for index in range(50):
        opened = start + index * step
        closed = opened + step
        source_id = _id(1000 + index)
        close = Decimal(100 + index)
        sources.append(
            DataSourceRecord(
                source_id,
                "binance-spot-public",
                "spot-api-2026-09",
                opened,
                closed,
                closed,
                "spot-public-v1",
                "binance-spot-adapter-v1",
                "synthetic-test-terms",
                "a" * 64,
            )
        )
        observations.append(
            MarketData(
                _id(2000 + index),
                "BTC-USDT-SPOT",
                "BINANCE-SPOT",
                "OHLCV",
                opened,
                opened,
                closed,
                closed,
                source_id,
                (
                    MetricValue("open", close - Decimal("0.2"), "USDT"),
                    MetricValue("high", close + Decimal("1"), "USDT"),
                    MetricValue("low", close - Decimal("1"), "USDT"),
                    MetricValue("close", close, "USDT"),
                    MetricValue("volume", Decimal("2"), "BTC"),
                ),
            )
        )

    snapshot = MarketSnapshot(
        _id(3000),
        NOW,
        NOW,
        "BTC-USDT-SPOT",
        "BINANCE-SPOT",
        tuple(item.market_data_id for item in observations),
        tuple(item.source_record_id for item in sources),
    )
    policy = approved_quality_policy_template().for_request(
        instrument_id=snapshot.instrument_id,
        timeframe="1m",
        cutoff=NOW,
        coverage_start=start,
        coverage_end=NOW,
    )
    batch = ProviderBatch(
        _id(3001),
        "binance-spot-public",
        "spot-api-2026-09",
        ProviderDataKind.OHLCV,
        ProviderBatchStatus.COMPLETE,
        NOW,
        NOW + timedelta(seconds=30),
        tuple(sources),
        tuple(observations),
        (snapshot,),
    )
    quality_v1 = assess_complete_binance_spot_batch(batch, policy, assessed_at=NOW)
    manifest, quality, regime, evidence_items, resolved = build_spot_analysis_manifest(
        snapshot=snapshot,
        quality_v1=quality_v1,
        observations=tuple(observations),
        sources=tuple(sources),
        policy=policy,
        timeframe="1m",
        now=NOW,
    )
    evidence = {item.evidence_id: item for item in evidence_items}
    binding_id = manifest.bindings[0].binding_id
    evidence_pair = tuple(
        sorted(evidence.values(), key=lambda item: str(item.evidence_id))[:2]
    )
    directional_findings = (
        SpotMetaFinding(
            _id(3100),
            "spot-trend",
            AnalyticalDirection.BULLISH,
            EvidenceRelation.SUPPORTING,
            ConfluenceEvidenceStrengthV2.MODERATE,
            FindingReadiness.READY,
            (evidence_pair[0].evidence_id,),
            (binding_id,),
            evidence_pair[0].method,
            ConflictMaterialityV2.MATERIAL,
            False,
            False,
            provenance=evidence_pair[0].provenance,
        ),
        SpotMetaFinding(
            _id(3101),
            "spot-momentum",
            AnalyticalDirection.BEARISH,
            EvidenceRelation.SUPPORTING,
            ConfluenceEvidenceStrengthV2.MODERATE,
            FindingReadiness.READY,
            (evidence_pair[1].evidence_id,),
            (binding_id,),
            evidence_pair[1].method,
            ConflictMaterialityV2.MATERIAL,
            False,
            False,
            provenance=evidence_pair[1].provenance,
        ),
    )
    findings = directional_findings[:1] if missing_bearish else directional_findings
    confluence, independence = calculate_spot_confluence_v3(
        manifest=manifest,
        resolved_bindings=resolved,
        evidence=evidence,
        findings=findings,
        now=NOW,
    )
    conflicts = calculate_spot_conflicts_v3(
        manifest=manifest,
        resolved_bindings=resolved,
        evidence=evidence,
        findings=findings,
        now=NOW,
    )
    independence_ref = C093Registry.reference(independence)
    final_manifest = create_analysis_snapshot_v4(
        snapshot_id=manifest.snapshot_id,
        asset=manifest.asset,
        instrument_id=manifest.instrument_id,
        venue_id=manifest.venue_id,
        timeframe=manifest.timeframe,
        analysis_cutoff=manifest.analysis_cutoff,
        created_at=manifest.created_at,
        expires_at=manifest.expires_at,
        bindings=manifest.bindings,
        assessment_ids=(_id(3200),),
        evidence_ids=manifest.evidence_ids,
        provenance=manifest.provenance,
        analysis_outputs=tuple(
            sorted(
                (
                    *manifest.analysis_outputs,
                    AnalysisOutputReferenceV4(
                        "C-009",
                        confluence.assessment.assessment_id,
                        "3",
                        "3",
                        canonical_sha256(confluence.assessment),
                    ),
                    independence_ref,
                    *(
                        AnalysisOutputReferenceV4(
                            "C-010",
                            item.assessment_id,
                            "3",
                            "3",
                            canonical_sha256(item),
                        )
                        for item in conflicts.assessments
                    ),
                ),
                key=lambda item: (item.contract_id, str(item.record_id)),
            )
        ),
    )
    resolved = resolve_analysis_snapshot_v4(
        final_manifest,
        now=NOW,
        snapshots={snapshot.snapshot_id: snapshot},
        reports={quality.report_id: quality},
        observations={item.market_data_id: item for item in observations},
        sources={item.source_record_id: item for item in sources},
        regimes={regime.regime_id: regime},
        evidence=evidence,
    )
    assessment = FundamentalAssessment(
        _id(3200),
        "BTC",
        "BTC-USDT-SPOT",
        "1m",
        NOW,
        NOW,
        final_manifest.expires_at,
        AssessmentStatus.UNAVAILABLE,
        Decimal("0.5"),
        (),
        (),
        final_manifest.evidence_ids,
        (),
        (),
        quality.report_id,
        (VersionReference("spot-fundamental-profile", "1"),),
    )
    uncertainty = AnalyticalUncertainty(
        _id(3201),
        UncertaintyCategory.DATA,
        "Only the bounded Spot OHLCV evidence is available.",
        (),
        ("derivatives", "sentiment", "on-chain"),
        Decimal("0.5"),
        False,
        (),
        NOW,
        final_manifest.expires_at,
        ResolutionStatus.UNRESOLVED,
    )
    base_context = MarketContextV4(
        _id(3202),
        "BTC",
        "BTC-USDT-SPOT",
        NOW,
        final_manifest.expires_at,
        ("1m",),
        regime,
        (assessment,),
        confluence.assessment,
        conflicts.assessments,
        AdversarialAssessment(
            _id(3203),
            NOW,
            final_manifest.expires_at,
            "A counter-thesis remains necessary.",
            ("The observed direction may not persist.",),
            (),
            ("The input window may expire.",),
            (),
            (),
            (),
            Decimal("0.5"),
        ),
        (uncertainty,),
        final_manifest.evidence_ids,
        AnalysisSnapshotReferenceV4(
            final_manifest.snapshot_id,
            final_manifest.schema_version,
            final_manifest.content_sha256,
        ),
    )
    adversarial_method = VersionReference("spot-adversarial-assessment", "v2")
    adversarial_model = VersionReference("spot-adversarial-model", "v1")
    adversarial_prompt = VersionReference("spot-adversarial-prompt", "v1")
    adversarial_versions = (
        adversarial_method,
        adversarial_model,
        adversarial_prompt,
    )
    context = build_spot_market_context_v5(
        base_context=base_context,
        manifest=final_manifest,
        resolved_bindings=resolved,
        evidence=evidence,
        supported_independence_reports=(independence_ref,),
        supported_adversarial_versions=adversarial_versions,
        draft=SpotAdversarialDraft(
            counter_thesis="The two directions remain unresolved in one shared OHLCV source.",
            alternative_hypotheses=("The apparent direction may be temporary.",),
            supporting_evidence_ids=(evidence_pair[0].evidence_id,),
            falsification_evidence_ids=(evidence_pair[1].evidence_id,),
            failure_conditions=("The next validated window invalidates the view.",),
            data_limitations=("Only Spot OHLCV is available.",),
            measurement_error_risks=(
                "Candle aggregation can hide intraperiod movement.",
            ),
            confirmation_bias_concerns=("Recent movement may be overweighted.",),
            coverage_gaps=("No derivatives, sentiment, or on-chain evidence.",),
            method=adversarial_method,
            model=adversarial_model,
            prompt=adversarial_prompt,
        ),
        now=NOW,
    )
    route = ModelRoutingDecision(
        request_id=_id(3300),
        request_sha256="b" * 64,
        workload_id="personal-spot-research",
        capability_tier=ModelCapabilityTier.ECONOMICAL_FAST,
        provider_id="approved-provider",
        model_id="approved-model",
        model_version="model-v1",
        prompt_id="spot-analysis",
        prompt_version="prompt-v1",
        policy_id="spot-policy",
        policy_version="1",
        decided_at=NOW - timedelta(seconds=1),
        expires_at=NOW + timedelta(minutes=5),
        max_input_tokens=4000,
        max_output_tokens=1000,
        max_request_cost_usd=Decimal("0.10"),
        availability=ModelAvailability.AVAILABLE,
        availability_reference="synthetic-provider-health",
        availability_checked_at=NOW - timedelta(seconds=2),
    )
    result = AgentResult(
        result_id=_id(3301),
        task_id=_id(3302),
        context_id=context.context_id,
        agent_id="personal-spot-research",
        agent_version="1",
        routing_decision=route,
        tool_access_ids=(),
        generated_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        status=status,
        confidence=None,
        supporting_evidence_ids=(evidence_pair[0].evidence_id,),
        contradicting_evidence_ids=(evidence_pair[1].evidence_id,),
        unresolved_risks=("The evidence remains insufficient.",)
        if status in {AgentResultStatus.NO_TRADE, AgentResultStatus.INSUFFICIENT_DATA}
        else (),
        output=context,
    )
    expectation = AgentResultExpectation(
        task_id=result.task_id,
        context_id=result.context_id,
        agent_id=result.agent_id,
        agent_version=result.agent_version,
        routing_decision=route,
        allowed_tool_access_ids=(),
        allowed_evidence_ids=result.supporting_evidence_ids
        + result.contradicting_evidence_ids,
        allowed_output_schemas={"C-006": ("5", MarketContextV5)},
    )
    correlation_id, trace_id = _id(3303), _id(3304)
    graph = build_spot_result_graph(
        expectation=expectation,
        checkpointer=None,
        clock=lambda: NOW,
    )
    state = asyncio.run(
        run_spot_result_graph(
            graph,
            expectation=expectation,
            correlation_id=correlation_id,
            trace_id=trace_id,
            environment=DeploymentEnvironment.TEST,
            mode=OperatingMode.RESEARCH,
            agent_result=result,
            thread_id=str(result.task_id),
            clock=lambda: NOW,
        )
    )
    evaluation = state["agent_evaluation"]
    return DebateEnvelope(
        result,
        expectation,
        evaluation,
        context,
        final_manifest,
        resolved,
        evidence,
        independence,
        adversarial_versions,
        correlation_id,
        trace_id,
    )


def _compose(envelope: DebateEnvelope, **overrides):
    values = {
        "agent_result": envelope.result,
        "agent_evaluation": envelope.evaluation,
        "expectation": envelope.expectation,
        "correlation_id": envelope.correlation_id,
        "trace_id": envelope.trace_id,
        "market_context": envelope.context,
        "manifest": envelope.manifest,
        "resolved_bindings": envelope.resolved,
        "evidence": envelope.evidence,
        "independence_reports": {
            envelope.independence.report_id: envelope.independence
        },
        "supported_adversarial_versions": envelope.supported_adversarial_versions,
        "now": NOW,
    }
    values.update(overrides)
    return compose_spot_debate(**values)


def _component(
    number: int, direction: AnalyticalDirection, evidence_id: UUID
) -> ConfluenceComponentV2:
    return ConfluenceComponentV2(
        component_id=_id(number),
        domain=f"synthetic-domain-{number}",
        direction=direction,
        relation=EvidenceRelation.SUPPORTING,
        evidence_strength=ConfluenceEvidenceStrengthV2.MODERATE,
        dependence=EvidenceDependenceV2.UNKNOWN,
        evidence_ids=(evidence_id,),
        input_binding_ids=(_id(90),),
    )


def _confluence(
    components: tuple[ConfluenceComponentV2, ...],
    *,
    status: ConfluenceStatusV2 = ConfluenceStatusV2.AVAILABLE,
) -> ConfluenceAssessmentV3:
    return ConfluenceAssessmentV3(
        assessment_id=_id(20),
        asset="BTC",
        instrument_id="BTC-USDT-SPOT",
        timeframe="1m",
        as_of=NOW,
        expires_at=NOW + timedelta(minutes=5),
        state=(
            ConfluenceStateV2.INDETERMINATE
            if status is ConfluenceStatusV2.INDETERMINATE
            else ConfluenceStateV2.PARTIALLY_ALIGNED
        ),
        status=status,
        status_reason=(
            ConfluenceReasonV2.INSUFFICIENT_EVIDENCE
            if status is ConfluenceStatusV2.INDETERMINATE
            else None
        ),
        components=components,
        analytical_confidence=AnalyticalConfidenceV2(
            AnalyticalConfidenceStateV2.UNAVAILABLE,
            None,
            None,
            AnalyticalConfidenceReasonV2.NOT_ASSESSED,
        ),
        evidence_strength=(
            ConfluenceEvidenceStrengthV2.UNKNOWN
            if status is ConfluenceStatusV2.INDETERMINATE
            else ConfluenceEvidenceStrengthV2.MODERATE
        ),
        independence_report=AnalysisOutputReferenceV4(
            "C-093",
            _id(21),
            C093Registry.schema_version,
            C093Registry.lineage_version,
            "a" * 64,
            C093Registry.method,
        ),
        input_snapshot_id=_id(22),
        input_snapshot_schema_version="4",
        data_quality_reports=(),
        evidence_ids=tuple(
            sorted({value for c in components for value in c.evidence_ids}, key=str)
        ),
        method=VersionReference("spot-confluence", "spot-confluence-v1"),
        provenance=(VersionReference("spot-profile", "v1"),),
    )


def test_directional_evidence_is_separated_and_exact_references_are_retained() -> None:
    bull_evidence, bear_evidence = _id(1), _id(2)
    confluence = _confluence(
        (
            _component(3, AnalyticalDirection.BULLISH, bull_evidence),
            _component(4, AnalyticalDirection.BEARISH, bear_evidence),
        )
    )

    bullish, bearish = _thesis_branches(confluence)

    assert bullish.available and bullish.evidence_ids == (bull_evidence,)
    assert bearish.available and bearish.evidence_ids == (bear_evidence,)
    assert bullish.component_ids == (_id(3),)
    assert bearish.component_ids == (_id(4),)


def test_missing_branch_is_unavailable_and_never_assigned_neutral_evidence() -> None:
    bullish, bearish = _thesis_branches(
        _confluence((_component(3, AnalyticalDirection.BULLISH, _id(1)),))
    )
    assert bullish.available
    assert not bearish.available
    assert bearish.evidence_ids == ()
    assert (
        _conclusion(
            result_status=AgentResultStatus.COMPLETE,
            confluence=_confluence(
                (_component(3, AnalyticalDirection.BULLISH, _id(1)),)
            ),
            conflicts=False,
            bullish=bullish,
            bearish=bearish,
        )
        is SpotDebateConclusion.BULLISH_EVIDENCE_UNRESOLVED
    )


def test_contradicting_only_component_does_not_become_thesis_support() -> None:
    component = replace(
        _component(3, AnalyticalDirection.BULLISH, _id(1)),
        relation=EvidenceRelation.CONTRADICTING,
    )
    bullish, bearish = _thesis_branches(_confluence((component,)))

    assert not bullish.available
    assert bullish.evidence_ids == (_id(1),)
    assert bullish.components == (component,)
    assert not bearish.available


def test_conflicting_branches_are_preserved_without_selecting_a_winner() -> None:
    confluence = _confluence(
        (
            _component(3, AnalyticalDirection.BULLISH, _id(1)),
            _component(4, AnalyticalDirection.BEARISH, _id(2)),
        )
    )
    bullish, bearish = _thesis_branches(confluence)

    assert (
        _conclusion(
            result_status=AgentResultStatus.COMPLETE,
            confluence=confluence,
            conflicts=True,
            bullish=bullish,
            bearish=bearish,
        )
        is SpotDebateConclusion.MIXED_OR_CONFLICTED
    )


def test_no_trade_and_indeterminate_analysis_remain_first_class() -> None:
    confluence = _confluence((), status=ConfluenceStatusV2.INDETERMINATE)
    bullish, bearish = _thesis_branches(confluence)

    assert (
        _conclusion(
            result_status=AgentResultStatus.COMPLETE,
            confluence=confluence,
            conflicts=False,
            bullish=bullish,
            bearish=bearish,
        )
        is SpotDebateConclusion.INSUFFICIENT_EVIDENCE
    )
    assert (
        _conclusion(
            result_status=AgentResultStatus.NO_TRADE,
            confluence=confluence,
            conflicts=False,
            bullish=bullish,
            bearish=bearish,
        )
        is SpotDebateConclusion.NO_TRADE
    )


def test_untyped_confluence_fails_closed() -> None:
    with pytest.raises(SpotDebateError, match="C-009 v3"):
        _thesis_branches(object())  # type: ignore[arg-type]


def test_public_composition_preserves_full_validated_bounded_envelope() -> None:
    envelope = _envelope()

    result = _compose(envelope)

    assert result.conclusion is SpotDebateConclusion.MIXED_OR_CONFLICTED
    assert result.disagreement_preserved
    assert result.bullish.available and result.bearish.available
    assert result.bullish.evidence_ids
    assert result.bearish.evidence_ids
    assert result.market_context.adversarial is envelope.context.adversarial
    assert result.independence_report == envelope.independence
    assert result.agent_result == envelope.result
    assert result.agent_evaluation == envelope.evaluation
    assert result.correlation_id == envelope.correlation_id
    assert result.trace_id == envelope.trace_id
    assert result.result_id == envelope.result.result_id
    assert result.task_id == envelope.result.task_id
    assert result.context_id == envelope.context.context_id
    assert result.market_context.confluence.independence_report.record_id == (
        envelope.independence.report_id
    )
    assert result.market_context.adversarial.contradictory_evidence_ids
    assert result.market_context.uncertainties
    assert all(
        item.resolution_status is ResolutionStatus.UNRESOLVED
        for item in result.market_context.uncertainties
    )


def test_public_composition_keeps_missing_thesis_branch_unavailable() -> None:
    envelope = _envelope(missing_bearish=True)

    result = _compose(envelope)

    assert result.bullish.available
    assert not result.bearish.available
    assert result.bearish.evidence_ids == ()
    assert result.market_context.adversarial.contradictory_evidence_ids
    assert result.disagreement_preserved


@pytest.mark.parametrize(
    "binding, expected_message",
    (
        ("result_id", "C-066 is not the completed evaluation"),
        ("correlation_id", "C-066 is not the completed evaluation"),
        ("trace_id", "C-066 is not the completed evaluation"),
        ("provider_id", "C-066 is not the completed evaluation"),
        ("model_id", "C-066 is not the completed evaluation"),
        ("prompt_version", "C-066 is not the completed evaluation"),
    ),
)
def test_public_composition_rejects_c066_binding_mismatch(
    binding: str, expected_message: str
) -> None:
    envelope = _envelope()
    changed_evaluation = replace(
        envelope.evaluation,
        **{
            binding: uuid4()
            if binding in {"result_id", "correlation_id", "trace_id"}
            else "wrong-identity"
        },
    )

    with pytest.raises(SpotDebateError, match=expected_message):
        _compose(envelope, agent_evaluation=changed_evaluation)


def test_public_composition_fails_closed_for_expired_c006_c019_lineage() -> None:
    envelope = _envelope()

    with pytest.raises(SpotDebateError, match="C-006 lineage, C-019, or C-093"):
        _compose(envelope, now=NOW + timedelta(seconds=65))


def test_public_composition_fails_closed_for_invalid_c007_manifest_binding() -> None:
    envelope = _envelope()
    invalid_manifest = create_analysis_snapshot_v4(
        snapshot_id=_id(3999),
        asset=envelope.manifest.asset,
        instrument_id=envelope.manifest.instrument_id,
        venue_id=envelope.manifest.venue_id,
        timeframe=envelope.manifest.timeframe,
        analysis_cutoff=envelope.manifest.analysis_cutoff,
        created_at=envelope.manifest.created_at,
        expires_at=envelope.manifest.expires_at,
        bindings=envelope.manifest.bindings,
        assessment_ids=envelope.manifest.assessment_ids,
        evidence_ids=envelope.manifest.evidence_ids,
        provenance=envelope.manifest.provenance,
        analysis_outputs=envelope.manifest.analysis_outputs,
    )

    with pytest.raises(SpotDebateError, match="C-006 lineage, C-019, or C-093"):
        _compose(envelope, manifest=invalid_manifest)


def test_public_composition_fails_closed_for_c093_digest_mismatch() -> None:
    envelope = _envelope()
    changed_report = replace(
        envelope.independence,
        limitations=(*envelope.independence.limitations, "changed report content"),
    )

    with pytest.raises(SpotDebateError, match="C-006 lineage, C-019, or C-093"):
        _compose(
            envelope,
            independence_reports={changed_report.report_id: changed_report},
        )


def test_public_composition_fails_closed_for_unresolved_c019_versions() -> None:
    envelope = _envelope()

    with pytest.raises(SpotDebateError, match="C-006 lineage, C-019, or C-093"):
        _compose(envelope, supported_adversarial_versions=())


@pytest.mark.parametrize(
    ("failure", "expected_outcome"),
    (
        ("timeout", AgentEvaluationOutcome.TIMED_OUT),
        ("failed", AgentEvaluationOutcome.FAILED),
    ),
)
def test_public_debate_rejects_noncompleted_c066_for_typed_c062(
    failure: str, expected_outcome: AgentEvaluationOutcome
) -> None:
    envelope = _envelope()

    class FailedGraph:
        async def ainvoke(self, _state: object, *, config: object) -> object:
            raise RuntimeError("sensitive evaluator detail")

    class SlowGraph:
        async def ainvoke(self, _state: object, *, config: object) -> object:
            await asyncio.sleep(0.05)
            return {}

    state = asyncio.run(
        run_spot_result_graph(
            FailedGraph() if failure == "failed" else SlowGraph(),
            expectation=envelope.expectation,
            correlation_id=envelope.correlation_id,
            trace_id=envelope.trace_id,
            environment=DeploymentEnvironment.TEST,
            mode=OperatingMode.RESEARCH,
            agent_result=envelope.result,
            thread_id=str(envelope.result.task_id),
            timeout_seconds=0.001,
            clock=lambda: NOW,
        )
    )
    evaluation = state["agent_evaluation"]

    assert evaluation.result_id == envelope.result.result_id
    assert evaluation.outcome is expected_outcome
    with pytest.raises(SpotDebateError, match="C-066 is not the completed evaluation"):
        _compose(envelope, agent_evaluation=evaluation)


@pytest.mark.parametrize(
    ("status", "expected"),
    (
        (AgentResultStatus.NO_TRADE, SpotDebateConclusion.NO_TRADE),
        (
            AgentResultStatus.INSUFFICIENT_DATA,
            SpotDebateConclusion.INSUFFICIENT_EVIDENCE,
        ),
    ),
)
def test_public_composition_preserves_no_trade_and_insufficient_evidence(
    status: AgentResultStatus, expected: SpotDebateConclusion
) -> None:
    envelope = _envelope(status)

    result = _compose(envelope)

    assert result.conclusion is expected
    assert result.agent_result.status is status
    assert result.agent_evaluation.result_status is status


def test_market_thesis_preserves_all_cases_and_exact_wave_one_evidence() -> None:
    envelope = _envelope()
    debate = _compose(envelope)

    thesis = compose_spot_market_thesis(debate, now=NOW)

    assert thesis.bullish.state is ThesisCaseState.AVAILABLE
    assert thesis.bearish.state is ThesisCaseState.AVAILABLE
    assert thesis.base.state is ThesisCaseState.UNAVAILABLE
    assert thesis.base.supporting_evidence_ids == ()
    assert thesis.bullish.supporting_evidence_ids == debate.bullish.evidence_ids
    assert thesis.bearish.supporting_evidence_ids == debate.bearish.evidence_ids
    assert thesis.source_debate is debate
    assert thesis.unresolved_conflicts
    assert thesis.unresolved_conflicts is debate.market_context.conflicts
    assert thesis.unresolved_uncertainties is debate.market_context.uncertainties
    assert thesis.critic_contradictory_evidence_ids == (
        debate.market_context.adversarial.contradictory_evidence_ids
    )
    assert thesis.expires_at == debate.expires_at
    assert thesis.no_trade_compatible
    assert all(
        item.state is ThesisInvalidationState.UNASSIGNED
        and item.source_contract_id == "C-019"
        and item.source_assessment_id == debate.market_context.adversarial.assessment_id
        for item in thesis.invalidation_candidates
    )
    assert thesis.invalidation_candidates
    assert thesis.bullish.assumptions == thesis.bearish.assumptions == ()
    assert (
        thesis.bullish.assumptions_state
        is ThesisAssumptionState.NOT_PROVIDED_BY_APPROVED_INPUTS
    )


def test_neutral_case_requires_explicit_neutral_supporting_evidence() -> None:
    neutral = _component(30, AnalyticalDirection.NEUTRAL, _id(31))

    base = _case((neutral,), AnalyticalDirection.NEUTRAL)
    contradictory = replace(
        _component(32, AnalyticalDirection.NEUTRAL, _id(33)),
        relation=EvidenceRelation.CONTRADICTING,
    )
    unsupported = _case((contradictory,), AnalyticalDirection.NEUTRAL)

    assert base.state is ThesisCaseState.AVAILABLE
    assert base.supporting_component_ids == (_id(30),)
    assert base.supporting_evidence_ids == (_id(31),)
    assert unsupported.state is ThesisCaseState.UNAVAILABLE
    assert unsupported.contradictory_evidence_ids == (_id(33),)


def test_both_directional_cases_remain_unavailable_without_support() -> None:
    components = (
        replace(
            _component(34, AnalyticalDirection.BULLISH, _id(35)),
            relation=EvidenceRelation.CONTRADICTING,
        ),
        replace(
            _component(36, AnalyticalDirection.BEARISH, _id(37)),
            relation=EvidenceRelation.CONTRADICTING,
        ),
    )

    bullish = _case(components, AnalyticalDirection.BULLISH)
    bearish = _case(components, AnalyticalDirection.BEARISH)

    assert bullish.state is ThesisCaseState.UNAVAILABLE
    assert bearish.state is ThesisCaseState.UNAVAILABLE
    assert bullish.supporting_evidence_ids == bearish.supporting_evidence_ids == ()
    assert bullish.contradictory_evidence_ids == (_id(35),)
    assert bearish.contradictory_evidence_ids == (_id(37),)


def test_market_thesis_composition_is_deterministic_and_no_trade_compatible() -> None:
    envelope = _envelope(AgentResultStatus.NO_TRADE)
    debate = _compose(envelope)

    first = compose_spot_market_thesis(debate, now=NOW)
    second = compose_spot_market_thesis(debate, now=NOW)

    assert first == second
    assert first.thesis_id == second.thesis_id
    assert first.decision_state is SpotDebateConclusion.NO_TRADE
    assert first.no_trade_compatible
    assert first.source_debate.agent_result is debate.agent_result


@pytest.mark.parametrize(
    "identity", ("context_id", "task_id", "correlation_id", "trace_id")
)
def test_market_thesis_rejects_mismatched_identity(identity: str) -> None:
    debate = _compose(_envelope())
    changed = replace(debate, **{identity: uuid4()})

    with pytest.raises(SpotMarketThesisError, match="identity or C-006 binding"):
        compose_spot_market_thesis(changed, now=NOW)


def test_market_thesis_rejects_expired_debate() -> None:
    debate = _compose(_envelope())

    with pytest.raises(SpotMarketThesisError, match="current and unexpired"):
        compose_spot_market_thesis(debate, now=debate.expires_at)
