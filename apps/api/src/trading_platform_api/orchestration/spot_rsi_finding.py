"""Conservative RSI14-to-finding adapter for the read-only Spot profile."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Callable, Mapping
from uuid import UUID, uuid5

from trading_platform_api.analysis.contracts import (
    AnalyticalDirection,
    EvidenceRelation,
    VersionReference,
)
from trading_platform_api.analysis.momentum import (
    MomentumStatus,
    RSISeries,
    calculate_rsi,
)
from trading_platform_api.analysis.spot_meta_analysis import (
    FindingReadiness,
    SpotMetaFinding,
)
from trading_platform_api.analysis.versioned_contracts import (
    ConfluenceEvidenceStrengthV2,
    EvidenceItemV2,
)
from trading_platform_api.analysis.versioned_contracts_v4 import (
    AnalysisSnapshotV4,
    AnalysisV2ContractError,
    ResolvedSpotOHLCVBindingV4,
    validate_evidence_item_v2_for_v4,
)
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.market_data.contracts import DataQualityStatus
from trading_platform_api.orchestration.spot_analysis_fanout import (
    SpotAnalysisTask,
    SpotAnalysisTaskReason,
    SpotAnalysisUnavailable,
)

SPOT_RSI_FINDING_METHOD = VersionReference("spot-rsi-momentum-finding", "1")
RSI_METHOD_VERSION = "rsi-wilder-sma-seed-v1"
_IDENTITY_NAMESPACE = UUID("0a30a58e-648f-5c7f-a068-b1bd68bb19ba")


def _unavailable(reason: SpotAnalysisTaskReason) -> SpotAnalysisUnavailable:
    return SpotAnalysisUnavailable(reason)


def _direction_and_relation(
    rsi_value: Decimal, regime_direction: AnalyticalDirection
) -> tuple[AnalyticalDirection, EvidenceRelation]:
    direction = (
        AnalyticalDirection.BULLISH
        if rsi_value > Decimal(50)
        else AnalyticalDirection.BEARISH
        if rsi_value < Decimal(50)
        else AnalyticalDirection.NEUTRAL
    )
    relation = EvidenceRelation.NEUTRAL
    if direction in {
        AnalyticalDirection.BULLISH,
        AnalyticalDirection.BEARISH,
    } and regime_direction in {
        AnalyticalDirection.BULLISH,
        AnalyticalDirection.BEARISH,
    }:
        relation = (
            EvidenceRelation.SUPPORTING
            if direction is regime_direction
            else EvidenceRelation.CONTRADICTING
        )
    return direction, relation


def adapt_rsi14_finding(
    *,
    series: RSISeries,
    evidence_ids: tuple[UUID, ...],
    evidence_by_id: Mapping[UUID, EvidenceItemV2],
    manifest: AnalysisSnapshotV4,
    resolved_binding: ResolvedSpotOHLCVBindingV4,
    now: datetime,
) -> SpotMetaFinding | SpotAnalysisUnavailable:
    """Map exact, resolved RSI14 evidence to a PARTIAL descriptive finding.

    The caller must supply C-008 source items already included in the exact
    resolved C-007 binding. Their observation coverage must equal the RSI
    calculator inputs. The adapter never creates evidence or lineage IDs.
    """
    if type(series) is not RSISeries:
        return _unavailable(SpotAnalysisTaskReason.INVALID_INPUT)
    if (
        series.indicator_id != "rsi"
        or series.parameters != (("period", 14),)
        or series.metadata_version != "1"
        or series.calculation_version != RSI_METHOD_VERSION
        or not series.points
    ):
        return _unavailable(SpotAnalysisTaskReason.INVALID_INPUT)

    point = series.points[-1]
    value = point.value
    if value.status is MomentumStatus.WARMUP:
        return _unavailable(SpotAnalysisTaskReason.INSUFFICIENT_WARMUP)
    if value.status is MomentumStatus.UNDEFINED:
        return _unavailable(SpotAnalysisTaskReason.INPUT_UNAVAILABLE)
    if value.status is not MomentumStatus.READY or value.value is None:
        return _unavailable(SpotAnalysisTaskReason.INVALID_INPUT)
    if not evidence_ids:
        return _unavailable(SpotAnalysisTaskReason.INPUT_UNAVAILABLE)
    if (
        type(manifest) is not AnalysisSnapshotV4
        or type(resolved_binding) is not ResolvedSpotOHLCVBindingV4
    ):
        return _unavailable(SpotAnalysisTaskReason.INVALID_INPUT)

    binding = resolved_binding.binding
    if (
        not resolved_binding.direct_inputs_pass
        or resolved_binding.report.status is not DataQualityStatus.VALID
        or series.snapshot_id != resolved_binding.snapshot.snapshot_id
        or series.quality_report_id != resolved_binding.report.report_id
        or series.instrument_id != binding.instrument_id
        or series.venue_id != binding.venue_id
        or series.timeframe != binding.timeframe
        or series.as_of != binding.analysis_cutoff
        or point.candle_end != binding.analysis_cutoff
        or series.input_market_data_ids != resolved_binding.snapshot.market_data_ids
        or series.unit != "percent"
        or value.value < Decimal(0)
        or value.value > Decimal(100)
    ):
        return _unavailable(SpotAnalysisTaskReason.INVALID_INPUT)

    at = now
    if resolved_binding.dependency_expires_at <= at or any(
        evidence_by_id.get(evidence_id) is not None
        and evidence_by_id[evidence_id].expires_at <= at
        for evidence_id in evidence_ids
    ):
        return _unavailable(SpotAnalysisTaskReason.STALE_INPUT)
    if len(set(evidence_ids)) != len(evidence_ids):
        return _unavailable(SpotAnalysisTaskReason.INPUT_UNAVAILABLE)
    resolved_evidence = {item.evidence_id: item for item in resolved_binding.evidence}
    selected: list[EvidenceItemV2] = []
    expected_observations = set(series.input_market_data_ids)
    sources_by_observation = {
        item.market_data_id: item.source_record_id
        for item in resolved_binding.observations
    }
    covered_observations: set[UUID] = set()
    covered_sources: set[UUID] = set()
    for evidence_id in sorted(evidence_ids, key=str):
        item = evidence_by_id.get(evidence_id)
        if item is None or resolved_evidence.get(evidence_id) != item:
            return _unavailable(SpotAnalysisTaskReason.INPUT_UNAVAILABLE)
        try:
            validate_evidence_item_v2_for_v4(
                item,
                manifest,
                resolved_bindings=(resolved_binding,),
                now=at,
            )
        except AnalysisV2ContractError:
            return _unavailable(SpotAnalysisTaskReason.INPUT_UNAVAILABLE)
        if (
            item.method != binding.regime_method
            or binding.regime_profile not in item.provenance
            or not item.observation_ids
            or not set(item.observation_ids).issubset(expected_observations)
            or set(item.source_record_ids)
            != {sources_by_observation[item_id] for item_id in item.observation_ids}
            or item.quality_status is not DataQualityStatus.VALID
            or not item.usable
        ):
            return _unavailable(SpotAnalysisTaskReason.INPUT_UNAVAILABLE)
        selected.append(item)
        covered_observations.update(item.observation_ids)
        covered_sources.update(item.source_record_ids)
    if covered_observations != expected_observations or covered_sources != set(
        sources_by_observation.values()
    ):
        return _unavailable(SpotAnalysisTaskReason.INPUT_UNAVAILABLE)

    direction, relation = _direction_and_relation(
        value.value, resolved_binding.regime.direction
    )

    identity_material = canonical_sha256(
        {
            "binding_id": binding.binding_id,
            "regime_id": resolved_binding.regime.regime_id,
            "regime_direction": resolved_binding.regime.direction,
            "snapshot_id": series.snapshot_id,
            "quality_report_id": series.quality_report_id,
            "cutoff": series.as_of,
            "evidence_ids": tuple(sorted(evidence_ids, key=str)),
            "method": SPOT_RSI_FINDING_METHOD,
            "metadata_version": series.metadata_version,
            "calculation_version": series.calculation_version,
            "value": value.value,
            "unit": series.unit,
        }
    )
    finding_id = uuid5(_IDENTITY_NAMESPACE, identity_material)
    # Touch selected to make it explicit that only exact, individually checked
    # items contribute IDs to the finding.
    selected_ids = tuple(item.evidence_id for item in selected)
    return SpotMetaFinding(
        finding_id=finding_id,
        domain="spot-momentum",
        direction=direction,
        relation=relation,
        evidence_strength=ConfluenceEvidenceStrengthV2.UNKNOWN,
        readiness=FindingReadiness.PARTIAL,
        evidence_ids=selected_ids,
        input_binding_ids=(binding.binding_id,),
        method=SPOT_RSI_FINDING_METHOD,
        result_value=value.value,
        result_unit=series.unit,
        provenance=tuple(
            sorted(
                {
                    binding.regime_method,
                    binding.regime_profile,
                    VersionReference("indicator-metadata:rsi", series.metadata_version),
                    VersionReference("rsi", series.calculation_version),
                },
                key=lambda item: (item.component, item.version),
            )
        ),
    )


def build_spot_rsi14_task(
    *,
    evidence_ids: tuple[UUID, ...],
    evidence_by_id: Mapping[UUID, EvidenceItemV2],
    manifest: AnalysisSnapshotV4,
    resolved_binding: ResolvedSpotOHLCVBindingV4,
    clock: Callable[[], datetime] | None = None,
) -> SpotAnalysisTask:
    """Bind RSI calculation and validation into one fan-out task.

    The callback consumes only the exact already-resolved C-007 input. Its task
    identity is stable for that manifest, binding, and selected source evidence;
    the evaluation time is read when the bounded fan-out invokes it.
    """
    if (
        type(manifest) is not AnalysisSnapshotV4
        or type(resolved_binding) is not ResolvedSpotOHLCVBindingV4
        or not isinstance(evidence_ids, tuple)
        or any(type(item) is not UUID for item in evidence_ids)
        or not isinstance(evidence_by_id, Mapping)
        or (clock is not None and not callable(clock))
    ):
        raise ValueError("RSI fan-out task inputs are invalid")

    ordered_evidence_ids = tuple(sorted(evidence_ids, key=str))
    task_id = uuid5(
        _IDENTITY_NAMESPACE,
        "rsi14-task:"
        + canonical_sha256(
            {
                "manifest_id": manifest.snapshot_id,
                "manifest_sha256": manifest.content_sha256,
                "binding_id": resolved_binding.binding.binding_id,
                "binding_sha256": canonical_sha256(resolved_binding.binding),
                "evidence_ids": ordered_evidence_ids,
                "method": SPOT_RSI_FINDING_METHOD,
                "metadata_version": "1",
                "calculation_version": RSI_METHOD_VERSION,
            }
        ),
    )
    get_now = clock or (lambda: datetime.now(UTC))

    def calculate_and_adapt() -> SpotMetaFinding | SpotAnalysisUnavailable:
        series = calculate_rsi(
            snapshot=resolved_binding.snapshot,
            observations=resolved_binding.observations,
            quality=resolved_binding.report,
            period=14,
            timeframe=resolved_binding.binding.timeframe,
            sources=resolved_binding.sources,
        )
        return adapt_rsi14_finding(
            series=series,
            evidence_ids=ordered_evidence_ids,
            evidence_by_id=evidence_by_id,
            manifest=manifest,
            resolved_binding=resolved_binding,
            now=get_now(),
        )

    async def run() -> SpotMetaFinding | SpotAnalysisUnavailable:
        return await asyncio.to_thread(calculate_and_adapt)

    return SpotAnalysisTask(task_id, "spot-momentum", run)


__all__ = [
    "SPOT_RSI_FINDING_METHOD",
    "adapt_rsi14_finding",
    "build_spot_rsi14_task",
]
