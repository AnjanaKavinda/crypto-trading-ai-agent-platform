"""Deterministic unavailable C-012/C-069 records for the approved Spot profile."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid5

from trading_platform_api.analysis.contracts import (
    AnalyticalUncertainty,
    AssessmentStatus,
    ResolutionStatus,
    TechnicalAssessment,
    UncertaintyCategory,
    VersionReference,
)
from trading_platform_api.analysis.versioned_contracts import DataQualityReportV2
from trading_platform_api.analysis.versioned_contracts_v4 import AnalysisSnapshotV4
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.market_data.contracts import MarketSnapshot

TECHNICAL_UNAVAILABLE_METHOD = VersionReference(
    "spot-profile-technical-unavailable-adapter", "1"
)
UNCERTAINTY_PROJECTION_METHOD = VersionReference(
    "spot-profile-unavailability-severity", "1"
)
_IDENTITY_NAMESPACE = UUID("52b95d6d-8940-50fc-a09d-2c3c085fac91")
_UNAVAILABLE_REASON = "C007_V4_REGIME_EVIDENCE_ONLY"


@dataclass(frozen=True, slots=True)
class SpotUnavailableTechnicalContext:
    assessment: TechnicalAssessment
    uncertainty: AnalyticalUncertainty


def unavailable_technical_assessment_id(
    snapshot: MarketSnapshot, quality_report: DataQualityReportV2
) -> UUID:
    """Bind the stable C-012 identity to exact raw snapshot and quality inputs."""
    material = (
        str(snapshot.snapshot_id),
        canonical_sha256(snapshot),
        str(quality_report.report_id),
        canonical_sha256(quality_report),
        _UNAVAILABLE_REASON,
        TECHNICAL_UNAVAILABLE_METHOD,
    )
    return uuid5(_IDENTITY_NAMESPACE, f"c012-unavailable:{canonical_sha256(material)}")


def build_spot_unavailable_technical_context(
    *,
    snapshot: MarketSnapshot,
    quality_report: DataQualityReportV2,
    manifest: AnalysisSnapshotV4,
) -> SpotUnavailableTechnicalContext:
    """Build the exact typed unavailable assessment and its scoped C-069 reason.

    The required C-012 numeric confidence value is schema-mandated but has no
    confidence meaning while status is UNAVAILABLE. Consumers must branch on
    status; no findings, observations, or evidence are fabricated here.
    """
    if (
        type(snapshot) is not MarketSnapshot
        or type(quality_report) is not DataQualityReportV2
        or type(manifest) is not AnalysisSnapshotV4
        or manifest.bindings[0].market_snapshot.record_id != str(snapshot.snapshot_id)
        or manifest.bindings[0].data_quality_report.record_id
        != str(quality_report.report_id)
        or manifest.bindings[0].data_quality_report.content_sha256
        != canonical_sha256(quality_report)
    ):
        raise ValueError("Unavailable technical context inputs are not exact.")
    # C-007's expiry is already bounded by the exact quality/freshness and
    # regime/evidence dependencies assembled by the Spot manifest builder.
    expires_at = manifest.expires_at
    as_of = manifest.analysis_cutoff
    if as_of >= expires_at:
        raise ValueError("Unavailable technical context has no valid lifetime.")
    uncertainty_id = uuid5(
        _IDENTITY_NAMESPACE,
        "c069-unavailable:"
        + canonical_sha256(
            (
                str(manifest.snapshot_id),
                manifest.content_sha256,
                _UNAVAILABLE_REASON,
                UNCERTAINTY_PROJECTION_METHOD,
            )
        ),
    )
    uncertainty = AnalyticalUncertainty(
        uncertainty_id=uncertainty_id,
        category=UncertaintyCategory.METHOD,
        description=(
            "Spot market structure is unavailable in this context because C-007 "
            "v4 binds regime evidence only; the distinct structure evidence "
            "cannot be projected or relabeled."
        ),
        affected_finding_ids=(),
        affected_domains=("spot-market-structure",),
        severity=Decimal("1.0"),
        reducible=True,
        required_evidence=(
            "approved-spot-market-structure-pivot-break-policy",
            "owner-approved-multi-method-c007-compatibility-decision",
        ),
        as_of=as_of,
        expires_at=expires_at,
        resolution_status=ResolutionStatus.UNRESOLVED,
    )
    assessment = TechnicalAssessment(
        assessment_id=unavailable_technical_assessment_id(snapshot, quality_report),
        asset=manifest.asset,
        instrument_id=manifest.instrument_id,
        timeframe=manifest.timeframe,
        as_of=as_of,
        available_at=as_of,
        expires_at=expires_at,
        status=AssessmentStatus.UNAVAILABLE,
        analytical_confidence=Decimal("0"),
        findings=(),
        observations=(),
        evidence_ids=(),
        contradiction_ids=(),
        uncertainty_ids=(uncertainty_id,),
        data_quality_report_id=quality_report.report_id,
        provenance=(TECHNICAL_UNAVAILABLE_METHOD,),
    )
    return SpotUnavailableTechnicalContext(assessment, uncertainty)


__all__ = [
    "TECHNICAL_UNAVAILABLE_METHOD",
    "UNCERTAINTY_PROJECTION_METHOD",
    "SpotUnavailableTechnicalContext",
    "build_spot_unavailable_technical_context",
    "unavailable_technical_assessment_id",
]
