"""Bounded provider-neutral producer for the PERSONAL_SPOT_RESEARCH handoff."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Awaitable, Callable, Literal, Mapping
from uuid import UUID, uuid4, uuid5

from trading_platform_api.agents.contracts import (
    AgentEvaluation,
    AgentEvaluationOutcome,
    AgentPermissionProfile,
    AgentResult,
    AgentResultStatus,
    ModelCapabilityTier,
    ModelRequest,
    ModelRoute,
    ModelRoutingPolicy,
)
from trading_platform_api.agents.evaluation import build_agent_evaluation
from trading_platform_api.agents.registry import resolve_agent_definition
from trading_platform_api.agents.result_validation import (
    AgentResultExpectation,
    validate_agent_result,
)
from trading_platform_api.agents.routing import (
    ModelProvider,
    ProviderAvailabilityEvidence,
    invoke_provider,
    resolve_model_route,
)
from trading_platform_api.analysis.contracts import VersionReference
from trading_platform_api.analysis.spot_adversarial import (
    SpotAdversarialDraft,
    build_spot_market_context_v5_direct,
)
from trading_platform_api.analysis.spot_unavailable_context import (
    TECHNICAL_UNAVAILABLE_METHOD,
    UNCERTAINTY_PROJECTION_METHOD,
)
from trading_platform_api.analysis.versioned_contracts_v5 import MarketContextV5
from trading_platform_api.config import DeploymentEnvironment, OperatingMode
from trading_platform_api.contracts.serialization import (
    canonical_json_dumps,
    canonical_sha256,
)
from trading_platform_api.market_data.contracts import (
    DataQualityReportV2,
    DataSourceRecord,
    MarketData,
    MarketSnapshot,
)
from trading_platform_api.orchestration.spot_request_handoff import (
    SpotRequestAnalysisHandoff,
)

SPOT_ADVERSARIAL_WORKLOAD = "personal-spot-adversarial-draft"
_IDENTITY_VERSION = "producer-request-identity-v1"
_CANONICALIZATION_VERSION = "canonical-json-v1"
_REQUEST_NAMESPACE = UUID("9e6d0377-6a8c-5f8b-bc6e-91c6ebf734da")


@dataclass(frozen=True, slots=True)
class SpotProducerRuntime:
    """Explicit runtime configuration; absent configuration fails closed."""

    routing_policy: ModelRoutingPolicy
    availability: ProviderAvailabilityEvidence
    provider: ModelProvider
    permission_profile: AgentPermissionProfile
    environment: DeploymentEnvironment
    operating_mode: OperatingMode
    capability_tier: ModelCapabilityTier
    remaining_budget_usd: Decimal
    adversarial_method: VersionReference
    supported_adversarial_versions: tuple[VersionReference, ...]
    provider_deadline_seconds: float = 30.0


@dataclass(frozen=True, slots=True)
class CompletedSpotAgentHandoff:
    context: MarketContextV5
    result: AgentResult
    evaluation: AgentEvaluation
    correlation_id: UUID
    trace_id: UUID
    request_sha256: str
    request_document: str
    is_replay: bool = False


@dataclass(frozen=True, slots=True)
class ProducerReservation:
    status: Literal["RESERVED", "IN_PROGRESS", "FAILED", "COMPLETED"]
    completed: CompletedSpotAgentHandoff | None = None


@dataclass(frozen=True, slots=True)
class SpotProducerUnavailable:
    reason_code: str


ReserveProducerRequest = Callable[[str, str, str], Awaitable[ProducerReservation]]
FailProducerRequest = Callable[[str], Awaitable[None]]


def _strict_draft_payload(content: str) -> Mapping[str, object]:
    def unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate model output field")
            result[key] = value
        return result

    decoded = json.loads(content, object_pairs_hook=unique_pairs)
    expected = {
        "counter_thesis",
        "alternative_hypotheses",
        "supporting_evidence_ids",
        "falsification_evidence_ids",
        "failure_conditions",
        "data_limitations",
        "measurement_error_risks",
        "confirmation_bias_concerns",
        "coverage_gaps",
    }
    if type(decoded) is not dict or set(decoded) != expected:
        raise ValueError("model output fields do not match the approved schema")
    for name in expected - {"counter_thesis"}:
        value = decoded[name]
        if type(value) is not list or any(type(item) is not str for item in value):
            raise ValueError("model output list has an invalid type")
    if type(decoded["counter_thesis"]) is not str:
        raise ValueError("model counter-thesis has an invalid type")
    return decoded


def _draft_from_response(
    content: str,
    *,
    method: VersionReference,
    model: VersionReference,
    prompt: VersionReference,
    allowed_evidence_ids: tuple[UUID, ...],
) -> SpotAdversarialDraft:
    payload = _strict_draft_payload(content)
    support = tuple(UUID(item) for item in payload["supporting_evidence_ids"])
    falsification = tuple(UUID(item) for item in payload["falsification_evidence_ids"])
    if not set((*support, *falsification)).issubset(set(allowed_evidence_ids)):
        raise ValueError(
            "model output cites evidence outside exact usable C-008 inputs"
        )
    return SpotAdversarialDraft(
        counter_thesis=payload["counter_thesis"],
        alternative_hypotheses=tuple(payload["alternative_hypotheses"]),
        supporting_evidence_ids=support,
        falsification_evidence_ids=falsification,
        failure_conditions=tuple(payload["failure_conditions"]),
        data_limitations=tuple(payload["data_limitations"]),
        measurement_error_risks=tuple(payload["measurement_error_risks"]),
        confirmation_bias_concerns=tuple(payload["confirmation_bias_concerns"]),
        coverage_gaps=tuple(payload["coverage_gaps"]),
        method=method,
        model=model,
        prompt=prompt,
    )


def _request_content(handoff: SpotRequestAnalysisHandoff) -> str:
    usable_evidence = tuple(
        sorted(
            (item for item in handoff.evidence if item.usable),
            key=lambda item: str(item.evidence_id),
        )
    )
    if not usable_evidence:
        raise ValueError("no exact usable C-008 evidence is available")
    document = {
        "profile": "PERSONAL_SPOT_RESEARCH",
        "manifest": handoff.manifest,
        "primary_regime": handoff.regime,
        "usable_evidence": usable_evidence,
        "instructions": (
            "Return only the exact JSON fields requested by the approved prompt. "
            "Draft a counter-thesis and alternatives using only supplied evidence. "
            "Do not invent market data, indicators, confidence, probabilities, risk, "
            "qualification, approval, or execution instructions. Cite only supplied "
            "usable C-008 evidence IDs."
        ),
    }
    content = canonical_json_dumps(document)
    if len(content.encode("utf-8")) > 900_000:
        raise ValueError("bounded model request exceeds the producer input limit")
    return content


def _producer_identity(
    *,
    handoff: SpotRequestAnalysisHandoff,
    snapshot: MarketSnapshot,
    quality_report: DataQualityReportV2,
    observations: tuple[MarketData, ...],
    sources: tuple[DataSourceRecord, ...],
    runtime: SpotProducerRuntime,
    method: VersionReference,
    model: VersionReference,
    prompt: VersionReference,
    route: ModelRoute,
    availability: ProviderAvailabilityEvidence,
    prompt_content_sha256: str,
) -> dict[str, object]:
    definition = resolve_agent_definition("personal-spot-research", "1")
    profile = runtime.permission_profile
    policy = profile.policy
    source_version = "1/1"
    return {
        "identity_version": _IDENTITY_VERSION,
        "canonicalization_version": _CANONICALIZATION_VERSION,
        "profile": ("PERSONAL_SPOT_RESEARCH", "1"),
        "agent": (definition.agent_id, definition.agent_version, "C-061", "1", "N/A"),
        "permissions": {
            "c063": (
                str(profile.profile_id),
                profile.revision,
                profile.schema_version,
                canonical_sha256(profile),
            ),
            "c098": (
                str(policy.policy_id),
                policy.revision,
                policy.version.version,
                policy.schema_version,
                canonical_sha256(policy),
            ),
            "c064_tool_access_ids": (),
            "c064_schema": "1",
        },
        "inputs": {
            "c002": (str(snapshot.snapshot_id), "1/1", canonical_sha256(snapshot)),
            "c003": (
                str(quality_report.report_id),
                "2/2",
                canonical_sha256(quality_report),
                quality_report.assessment_policy_id,
                quality_report.assessment_policy_version,
                canonical_sha256(handoff.resolved_bindings[0].policy),
            ),
            "c005": (
                str(handoff.regime.regime_id),
                "1/1",
                canonical_sha256(handoff.regime),
                handoff.manifest.bindings[0].regime_method,
                handoff.manifest.bindings[0].regime_profile,
            ),
            "c008": tuple(
                (
                    str(item.evidence_id),
                    "2/2",
                    canonical_sha256(item),
                    item.method,
                    item.provenance,
                )
                for item in sorted(
                    handoff.evidence, key=lambda item: str(item.evidence_id)
                )
            ),
            "c007": (
                str(handoff.manifest.snapshot_id),
                "4/4",
                handoff.manifest.content_sha256,
            ),
            "c001": tuple(
                (str(item.market_data_id), source_version, canonical_sha256(item))
                for item in observations
            ),
            "c091": tuple(
                (str(item.source_record_id), source_version, canonical_sha256(item))
                for item in sources
            ),
            "scope": (
                handoff.manifest.timeframe,
                handoff.manifest.bindings[0].window_start.isoformat(),
                handoff.manifest.bindings[0].window_end.isoformat(),
            ),
        },
        "deterministic": {
            "c012": (
                str(handoff.unavailable_technical.assessment.assessment_id),
                "1/1",
                canonical_sha256(handoff.unavailable_technical.assessment),
                TECHNICAL_UNAVAILABLE_METHOD,
            ),
            "c009": (
                str(handoff.confluence.assessment_id),
                "3/3",
                canonical_sha256(handoff.confluence),
                handoff.confluence.method,
            ),
            "c010": tuple(
                (str(item.assessment_id), "3/3", canonical_sha256(item), item.method)
                for item in handoff.conflicts
            ),
            "c093": (
                str(handoff.assessment.independence_report.report_id),
                "1/1",
                canonical_sha256(handoff.assessment.independence_report),
                handoff.assessment.independence_report.method,
            ),
            "c069": (
                str(handoff.unavailable_technical.uncertainty.uncertainty_id),
                "1/1",
                canonical_sha256(handoff.unavailable_technical.uncertainty),
                UNCERTAINTY_PROJECTION_METHOD,
            ),
        },
        "handoff": {
            "prompt_content_sha256": prompt_content_sha256,
            "c019": (
                method.component,
                method.version,
                model.component,
                model.version,
                prompt.component,
                prompt.version,
                "2/2",
            ),
            "c006": ("5/5",),
            "c062": ("1/1",),
            "c066": ("1/1",),
            "c067": {
                "schema_lineage": "1/1",
                "policy": (route.policy_id, route.policy_version),
                "policy_digest": canonical_sha256(runtime.routing_policy),
                "route_digest": canonical_sha256(route),
                "policy_valid_until": runtime.routing_policy.valid_until.isoformat(),
                "provider": (route.provider_id, availability.provider_id),
                "model": (route.model_id, route.model_version, availability.model_id),
                "prompt": (route.prompt_id, route.prompt_version),
                "capability_tier": route.capability_tier.value,
                "workload": SPOT_ADVERSARIAL_WORKLOAD,
                "availability": (
                    availability.status.value,
                    availability.evidence_reference,
                    availability.checked_at.isoformat(),
                    availability.valid_until.isoformat(),
                ),
                "bounds": (
                    route.max_input_tokens,
                    route.max_output_tokens,
                    str(route.max_request_cost_usd),
                ),
                "fallback": "DENY",
            },
        },
    }


async def produce_spot_agent_handoff(
    *,
    handoff: SpotRequestAnalysisHandoff,
    snapshot: MarketSnapshot,
    quality_report: DataQualityReportV2,
    observations: tuple[MarketData, ...],
    sources: tuple[DataSourceRecord, ...],
    correlation_id: UUID,
    trace_id: UUID,
    now: datetime,
    runtime: SpotProducerRuntime | None,
    reserve_request: ReserveProducerRequest,
    fail_request: FailProducerRequest,
) -> CompletedSpotAgentHandoff | SpotProducerUnavailable:
    """Route one bounded C-019 draft and validate the complete exact C-006/C-062/C-066/C-067 handoff."""
    if runtime is None:
        return SpotProducerUnavailable("MODEL_ROUTE_NOT_CONFIGURED")
    if not 0 < runtime.provider_deadline_seconds <= 60:
        return SpotProducerUnavailable("MODEL_DEADLINE_INVALID")
    if runtime.operating_mode is not OperatingMode.RESEARCH:
        return SpotProducerUnavailable("RESEARCH_MODE_REQUIRED")
    instant = now.astimezone(UTC)
    if (
        len(handoff.resolved_bindings) != 1
        or handoff.manifest.expires_at <= instant
        or handoff.manifest.analysis_cutoff > instant
        or handoff.quality_report.report_id != quality_report.report_id
        or canonical_sha256(handoff.quality_report) != canonical_sha256(quality_report)
    ):
        return SpotProducerUnavailable("SPOT_INPUT_STALE_OR_MISMATCHED")
    resolved = handoff.resolved_bindings[0]
    if (
        resolved.dependency_expires_at <= instant
        or not resolved.direct_inputs_pass
        or resolved.snapshot.snapshot_id != snapshot.snapshot_id
        or canonical_sha256(resolved.snapshot) != canonical_sha256(snapshot)
        or resolved.report.report_id != quality_report.report_id
        or canonical_sha256(resolved.report) != canonical_sha256(quality_report)
        or tuple(item.market_data_id for item in resolved.observations)
        != tuple(item.market_data_id for item in observations)
        or tuple(canonical_sha256(item) for item in resolved.observations)
        != tuple(canonical_sha256(item) for item in observations)
        or tuple(item.source_record_id for item in resolved.sources)
        != tuple(item.source_record_id for item in sources)
        or tuple(canonical_sha256(item) for item in resolved.sources)
        != tuple(canonical_sha256(item) for item in sources)
        or tuple(item.market_data_id for item in observations)
        != snapshot.market_data_ids
        or tuple(item.source_record_id for item in sources)
        != snapshot.source_record_ids
        or canonical_sha256(resolved.regime) != canonical_sha256(handoff.regime)
    ):
        return SpotProducerUnavailable("SPOT_INPUT_STALE_OR_MISMATCHED")
    definition = resolve_agent_definition("personal-spot-research", "1")
    profile = runtime.permission_profile
    policy = profile.policy
    if (
        profile.agent_id != definition.agent_id
        or profile.agent_version != definition.agent_version
        or profile.role != definition.role
        or profile.mode != "PERSONAL_SPOT_RESEARCH"
        or profile.environment != runtime.environment.value
        or profile.tool_access_ids
        or profile.revoked_at is not None
        or not profile.valid_from <= instant < profile.valid_until
        or not policy.default_deny
        or not policy.effective_at <= instant < policy.expires_at
        or runtime.operating_mode is not OperatingMode.RESEARCH
        or not set(definition.allowed_modes).issuperset({profile.mode})
    ):
        return SpotProducerUnavailable("AGENT_PERMISSION_PROFILE_UNAVAILABLE")
    route = next(
        (
            item
            for item in runtime.routing_policy.routes
            if item.capability_tier is runtime.capability_tier
        ),
        None,
    )
    if route is None:
        return SpotProducerUnavailable("MODEL_ROUTE_UNAVAILABLE")
    method = runtime.adversarial_method
    model = VersionReference(route.model_id, route.model_version)
    prompt = VersionReference(route.prompt_id, route.prompt_version)
    if (
        method not in runtime.supported_adversarial_versions
        or model not in runtime.supported_adversarial_versions
        or prompt not in runtime.supported_adversarial_versions
        or len(set(runtime.supported_adversarial_versions))
        != len(runtime.supported_adversarial_versions)
    ):
        return SpotProducerUnavailable("ADVERSARIAL_METHOD_NOT_REGISTERED")
    content = _request_content(handoff)
    reserved_request_sha256: str | None = None
    try:
        identity = _producer_identity(
            handoff=handoff,
            snapshot=snapshot,
            quality_report=quality_report,
            observations=observations,
            sources=sources,
            runtime=runtime,
            method=method,
            model=model,
            prompt=prompt,
            route=route,
            availability=runtime.availability,
            prompt_content_sha256=canonical_sha256(content),
        )
        request_document = canonical_json_dumps(identity)
        request_sha256 = canonical_sha256(identity)
        request = ModelRequest(
            request_id=uuid5(_REQUEST_NAMESPACE, request_sha256),
            workload_id=SPOT_ADVERSARIAL_WORKLOAD,
            capability_tier=runtime.capability_tier,
            prompt_id=route.prompt_id,
            prompt_version=route.prompt_version,
            content=content,
            # UTF-8 bytes are a conservative upper bound for tokenizer input size.
            requested_input_tokens=len(content.encode("utf-8")),
            requested_output_tokens=route.max_output_tokens,
        )
        decision = resolve_model_route(
            policy=runtime.routing_policy,
            request=request,
            availability=runtime.availability,
            now=instant,
            remaining_budget_usd=runtime.remaining_budget_usd,
        )
        if decision.provider_id != runtime.provider.provider_id:
            return SpotProducerUnavailable("MODEL_PROVIDER_MISMATCH")
        reservation = await reserve_request(
            request_sha256, request_document, str(snapshot.snapshot_id)
        )
        if reservation.status == "COMPLETED" and reservation.completed is not None:
            if (
                reservation.completed.request_sha256 != request_sha256
                or reservation.completed.context.expires_at <= instant
            ):
                return SpotProducerUnavailable("COMPLETED_HANDOFF_EXPIRED")
            return CompletedSpotAgentHandoff(
                context=reservation.completed.context,
                result=reservation.completed.result,
                evaluation=reservation.completed.evaluation,
                correlation_id=reservation.completed.correlation_id,
                trace_id=reservation.completed.trace_id,
                request_sha256=reservation.completed.request_sha256,
                request_document=reservation.completed.request_document,
                is_replay=True,
            )
        if reservation.status != "RESERVED":
            return SpotProducerUnavailable("PRODUCER_REQUEST_ALREADY_RESERVED")
        reserved_request_sha256 = request_sha256
        async with asyncio.timeout(runtime.provider_deadline_seconds):
            response = await invoke_provider(
                provider=runtime.provider,
                decision=decision,
                request=request,
                now=instant,
            )
        draft = _draft_from_response(
            response.content,
            method=method,
            model=model,
            prompt=prompt,
            allowed_evidence_ids=tuple(
                item.evidence_id for item in handoff.evidence if item.usable
            ),
        )
        evidence = {item.evidence_id: item for item in handoff.evidence}
        supported_versions = tuple(dict.fromkeys((method, model, prompt)))
        context = build_spot_market_context_v5_direct(
            manifest=handoff.manifest,
            resolved_bindings=handoff.resolved_bindings,
            evidence=evidence,
            technical_assessment=handoff.unavailable_technical.assessment,
            confluence=handoff.confluence,
            conflicts=handoff.conflicts,
            uncertainty=handoff.unavailable_technical.uncertainty,
            supported_independence_reports=(handoff.confluence.independence_report,),
            supported_adversarial_versions=supported_versions,
            draft=draft,
            now=response.completed_at,
        )
        expectation = AgentResultExpectation(
            task_id=uuid4(),
            context_id=context.context_id,
            agent_id=definition.agent_id,
            agent_version=definition.agent_version,
            routing_decision=decision,
            allowed_tool_access_ids=(),
            allowed_evidence_ids=tuple(sorted(evidence, key=str)),
            allowed_output_schemas={"C-006": ("5", MarketContextV5)},
        )
        result = AgentResult(
            result_id=uuid4(),
            task_id=expectation.task_id,
            context_id=context.context_id,
            agent_id=definition.agent_id,
            agent_version=definition.agent_version,
            routing_decision=decision,
            tool_access_ids=(),
            generated_at=response.completed_at,
            expires_at=min(context.expires_at, decision.expires_at),
            status=AgentResultStatus.COMPLETE,
            confidence=None,
            supporting_evidence_ids=draft.supporting_evidence_ids,
            contradicting_evidence_ids=draft.falsification_evidence_ids,
            unresolved_risks=tuple(
                sorted(set(draft.data_limitations + draft.coverage_gaps))
            )
            or ("ANALYSIS_ONLY_NO_TRADE_AUTHORITY",),
            output=context,
        )
        validate_agent_result(
            result, expectation=expectation, now=response.completed_at
        )
        evaluation = build_agent_evaluation(
            result,
            expectation=expectation,
            correlation_id=correlation_id,
            trace_id=trace_id,
            environment=runtime.environment,
            mode=OperatingMode.RESEARCH,
            started_at=decision.decided_at,
            ended_at=response.completed_at,
            evaluated_at=response.completed_at,
            duration_ms=int(
                (response.completed_at - decision.decided_at).total_seconds() * 1000
            ),
            outcome=AgentEvaluationOutcome.COMPLETED,
            failure_classification=None,
            validation_completed=True,
        )
        return CompletedSpotAgentHandoff(
            context,
            result,
            evaluation,
            correlation_id,
            trace_id,
            request_sha256,
            request_document,
        )
    except Exception:
        if reserved_request_sha256 is not None:
            try:
                await fail_request(reserved_request_sha256)
            except Exception:
                pass
        return SpotProducerUnavailable("MODEL_HANDOFF_INVALID_OR_UNAVAILABLE")


__all__ = [
    "CompletedSpotAgentHandoff",
    "ProducerReservation",
    "SpotProducerRuntime",
    "SpotProducerUnavailable",
    "produce_spot_agent_handoff",
]
