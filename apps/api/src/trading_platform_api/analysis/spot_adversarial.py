"""Fail-closed binding for the bounded Spot adversarial analysis stage.

The upstream analyst supplies typed adversarial text and exact version
references. This module does not invoke a model or infer a counter-thesis from
market data; it validates and binds that untrusted draft to the approved Spot
evidence before producing C-019 v2 / C-006 v5.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping
from uuid import UUID, uuid5

from trading_platform_api.analysis.contracts import (
    VersionReference,
    _text_tuple,
    _time,
    _typed_tuple,
    _unique,
    _uuid_tuple,
)
from trading_platform_api.analysis.versioned_contracts import (
    AnalysisV2ContractError,
    AnalyticalConfidenceReasonV2,
    AnalyticalConfidenceStateV2,
    AnalyticalConfidenceV2,
    EvidenceItemV2,
)
from trading_platform_api.analysis.versioned_contracts_v4 import (
    AnalysisOutputReferenceV4,
    AnalysisSnapshotReferenceV4,
    AnalysisSnapshotV4,
    MarketContextV4,
    ResolvedSpotOHLCVBindingV4,
    validate_market_context_v4,
)
from trading_platform_api.analysis.versioned_contracts_v5 import (
    AdversarialAssessmentV2,
    AdversarialEvidenceReferenceV2,
    MarketContextV5,
    validate_market_context_v5,
)
from trading_platform_api.contracts.serialization import canonical_sha256

_IDENTITY_NAMESPACE = UUID("e643d9e5-299d-5ca5-b37d-4423dbab8c54")


@dataclass(frozen=True, slots=True)
class SpotAdversarialDraft:
    """Untrusted analyst output to bind to one validated Spot context."""

    counter_thesis: str
    alternative_hypotheses: tuple[str, ...]
    supporting_evidence_ids: tuple[UUID, ...]
    falsification_evidence_ids: tuple[UUID, ...]
    failure_conditions: tuple[str, ...]
    data_limitations: tuple[str, ...]
    measurement_error_risks: tuple[str, ...]
    confirmation_bias_concerns: tuple[str, ...]
    coverage_gaps: tuple[str, ...]
    method: VersionReference
    model: VersionReference
    prompt: VersionReference

    def __post_init__(self) -> None:
        if not isinstance(self.counter_thesis, str) or not self.counter_thesis.strip():
            raise AnalysisV2ContractError("Counter-thesis must be explicit.")
        object.__setattr__(self, "counter_thesis", self.counter_thesis.strip())
        alternatives = _text_tuple(
            "alternative_hypotheses", self.alternative_hypotheses, empty=False
        )
        if not alternatives:
            raise AnalysisV2ContractError(
                "At least one alternative hypothesis is required."
            )
        _unique("alternative hypotheses", alternatives)
        object.__setattr__(self, "alternative_hypotheses", alternatives)
        for name in ("supporting_evidence_ids", "falsification_evidence_ids"):
            values = _uuid_tuple(name, getattr(self, name), empty=False)
            _unique(name, values)
            object.__setattr__(self, name, tuple(sorted(values, key=str)))
        if set(self.supporting_evidence_ids) & set(self.falsification_evidence_ids):
            raise AnalysisV2ContractError(
                "Supporting and falsification evidence must be distinct."
            )
        for name in (
            "failure_conditions",
            "data_limitations",
            "measurement_error_risks",
            "confirmation_bias_concerns",
            "coverage_gaps",
        ):
            text_values = _text_tuple(name, getattr(self, name), empty=False)
            if not text_values:
                raise AnalysisV2ContractError(f"{name} must be explicit.")
            _unique(name, text_values)
            object.__setattr__(self, name, text_values)
        for name in ("method", "model", "prompt"):
            if type(getattr(self, name)) is not VersionReference:
                raise AnalysisV2ContractError(f"{name} version must be explicit.")


def build_spot_market_context_v5(
    *,
    base_context: MarketContextV4,
    manifest: AnalysisSnapshotV4,
    resolved_bindings: tuple[ResolvedSpotOHLCVBindingV4, ...],
    evidence: Mapping[UUID, EvidenceItemV2],
    supported_independence_reports: tuple[AnalysisOutputReferenceV4, ...],
    supported_adversarial_versions: tuple[VersionReference, ...],
    draft: SpotAdversarialDraft,
    now: datetime,
) -> MarketContextV5:
    """Validate, bind, and emit an exact C-019 v2 / C-006 v5 Spot context.

    No model, provider, refresh, persistence, or network work occurs here.
    Caller-supplied narrative is treated as untrusted until this function
    validates its exact evidence and version bindings.
    """

    at = _time("now", now)
    if type(draft) is not SpotAdversarialDraft:
        raise AnalysisV2ContractError("Expected an exact typed Spot adversarial draft.")
    validate_market_context_v4(
        base_context,
        manifest,
        resolved_bindings=resolved_bindings,
        evidence=evidence,
        supported_independence_reports=supported_independence_reports,
        now=at,
    )
    if len(resolved_bindings) != 1:
        raise AnalysisV2ContractError("Spot profile requires one exact OHLCV binding.")
    binding = resolved_bindings[0]
    selected_ids = tuple(
        sorted(
            set(draft.supporting_evidence_ids) | set(draft.falsification_evidence_ids),
            key=str,
        )
    )
    if not selected_ids:
        raise AnalysisV2ContractError(
            "Supporting and falsification evidence must be supplied."
        )
    selected: list[EvidenceItemV2] = []
    for evidence_id in selected_ids:
        item = evidence.get(evidence_id)
        if item is None or not item.usable:
            raise AnalysisV2ContractError(
                "Adversarial evidence must resolve to usable C-008 v2 records."
            )
        selected.append(item)

    expires_at = min(
        base_context.expires_at,
        manifest.expires_at,
        binding.dependency_expires_at,
        base_context.regime.expires_at,
        base_context.confluence.expires_at,
        *(item.expires_at for item in base_context.assessments),
        *(item.expires_at for item in base_context.conflicts),
        *(item.expires_at for item in base_context.uncertainties),
        *(item.expires_at for item in selected),
    )
    if expires_at <= at or expires_at <= manifest.analysis_cutoff:
        raise AnalysisV2ContractError(
            "Spot adversarial evidence is stale or has no valid remaining lifetime."
        )

    required_versions = {draft.method, draft.model, draft.prompt}
    supported_versions = _typed_tuple(
        "supported_adversarial_versions",
        supported_adversarial_versions,
        VersionReference,
        empty=False,
    )
    _unique("supported adversarial versions", supported_versions)
    if not required_versions.issubset(set(supported_versions)):
        raise AnalysisV2ContractError(
            "Draft method/model/prompt versions are not resolved by the caller registry."
        )

    evidence_refs = tuple(
        AdversarialEvidenceReferenceV2(
            AnalysisOutputReferenceV4(
                "C-008",
                item.evidence_id,
                item.schema_version,
                item.schema_version,
                canonical_sha256(item),
            ),
            item.binding_ids,
            item.observation_ids,
            item.source_record_ids,
        )
        for item in selected
    )
    input_fingerprint = canonical_sha256(
        (manifest, base_context, draft, tuple(selected))
    )
    assessment_id = uuid5(_IDENTITY_NAMESPACE, f"c019-v2:{input_fingerprint}")
    snapshot_ref = AnalysisSnapshotReferenceV4(
        manifest.snapshot_id, manifest.schema_version, manifest.content_sha256
    )
    adversarial = AdversarialAssessmentV2(
        assessment_id=assessment_id,
        asset=manifest.asset,
        instrument_id=manifest.instrument_id,
        timeframe=manifest.timeframe,
        coverage_start=binding.binding.window_start,
        coverage_end=binding.binding.window_end,
        snapshot_as_of=binding.binding.snapshot_as_of,
        analysis_cutoff=manifest.analysis_cutoff,
        as_of=manifest.analysis_cutoff,
        expires_at=expires_at,
        counter_thesis=draft.counter_thesis,
        alternative_hypotheses=draft.alternative_hypotheses,
        evidence=evidence_refs,
        contradictory_evidence_ids=draft.falsification_evidence_ids,
        failure_conditions=draft.failure_conditions,
        data_limitations=tuple(
            sorted(set((*draft.data_limitations, *draft.coverage_gaps)))
        ),
        measurement_error_risks=draft.measurement_error_risks,
        confirmation_bias_concerns=draft.confirmation_bias_concerns,
        analytical_confidence=AnalyticalConfidenceV2(
            AnalyticalConfidenceStateV2.UNAVAILABLE,
            None,
            None,
            AnalyticalConfidenceReasonV2.NOT_ASSESSED,
        ),
        analysis_snapshot=snapshot_ref,
        data_quality_report=binding.binding.data_quality_report,
        method=draft.method,
        model=draft.model,
        prompt=draft.prompt,
    )
    context_id = uuid5(
        _IDENTITY_NAMESPACE,
        f"c006-v5:{base_context.context_id}:{assessment_id}",
    )
    context = MarketContextV5(
        context_id=context_id,
        asset=base_context.asset,
        instrument_id=base_context.instrument_id,
        as_of=base_context.as_of,
        expires_at=expires_at,
        multi_timeframe_state=base_context.multi_timeframe_state,
        regime=base_context.regime,
        assessments=base_context.assessments,
        confluence=base_context.confluence,
        conflicts=base_context.conflicts,
        adversarial=adversarial,
        uncertainties=base_context.uncertainties,
        evidence_ids=base_context.evidence_ids,
        analysis_snapshot=snapshot_ref,
    )
    validate_market_context_v5(
        context,
        manifest,
        resolved_bindings=resolved_bindings,
        evidence=evidence,
        supported_independence_reports=supported_independence_reports,
        supported_adversarial_versions=supported_versions,
        now=at,
    )
    return context


__all__ = ["SpotAdversarialDraft", "build_spot_market_context_v5"]
