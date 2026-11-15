"""Deterministic, observation-only bias checks over an exact Spot replay."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from trading_platform_api.lineage.store import SqlAlchemyLineageStore
from trading_platform_api.validation.bias_contracts_v2 import (
    CHECK_TYPES,
    METHOD,
    METHOD_VERSION,
    BiasArchiveReferenceV2,
    BiasAuditOutcomeV2,
    BiasCheckObservationV2,
    SpotBiasAuditResultV2,
)
from trading_platform_api.validation.contracts import BiasCheckType, CheckOutcome
from trading_platform_api.validation.contracts_v2 import ValidationArtifactReferenceV2
from trading_platform_api.validation.contracts_v3 import (
    BacktestOutcomeV3,
    BacktestResultV3,
)
from trading_platform_api.validation.spot_backtest import (
    SpotBacktestBundle,
    SpotBacktestOutcome,
    SpotBacktestRunRequest,
    SpotBacktestTrace,
    resolve_spot_backtest_result,
    run_spot_backtest,
)
from trading_platform_api.validation.spot_oos import _request_digest
from trading_platform_api.validation.spot_replay_inputs import StrategyVersionResolver

_REQUEST_NAMESPACE = uuid5(
    NAMESPACE_URL, "trading-platform:C-094:2:spot-backtest-request-identity-v1"
)
_REPLAY_CHECK_TYPES = (
    BiasCheckType.POINT_IN_TIME,
    BiasCheckType.LOOK_AHEAD,
)
_UNSUPPORTED_REASONS = {
    BiasCheckType.FEATURE_TARGET_LEAKAGE: "FEATURE_TARGET_LEAKAGE_AUDIT_UNAVAILABLE",
    BiasCheckType.NORMALIZATION_PARAMETER_LEAKAGE: "NORMALIZATION_PARAMETER_AUDIT_UNAVAILABLE",
    BiasCheckType.SURVIVORSHIP: "SURVIVORSHIP_AUDIT_UNAVAILABLE",
    BiasCheckType.SELECTION: "SELECTION_BIAS_AUDIT_UNAVAILABLE",
    BiasCheckType.DATA_SNOOPING: "DATA_SNOOPING_AUDIT_UNAVAILABLE",
    BiasCheckType.MULTIPLE_TESTING: "MULTIPLE_TESTING_AUDIT_UNAVAILABLE",
    BiasCheckType.UNIVERSE_METHODOLOGY: "UNIVERSE_METHODOLOGY_AUDIT_UNAVAILABLE",
}


class SpotBiasAuditInputError(ValueError):
    """The frozen replay request or audit timestamps are malformed."""


def _time(name: str, value: datetime) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise SpotBiasAuditInputError(f"{name.upper()}_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(UTC)


def _request_reference(
    request: SpotBacktestRunRequest,
) -> ValidationArtifactReferenceV2:
    digest = _request_digest(request)
    identity = uuid5(_REQUEST_NAMESPACE, digest)
    return ValidationArtifactReferenceV2("SPOT_BACKTEST_REQUEST", identity, "1", digest)


def _strategy_reference(
    request: SpotBacktestRunRequest,
) -> ValidationArtifactReferenceV2:
    strategy = request.replay_inputs.strategy
    return ValidationArtifactReferenceV2(
        "C-021",
        strategy.strategy_version_id,
        "2",
        strategy.content_sha256,
    )


def _reference(
    kind: str, identity: UUID, version: str, digest: str
) -> ValidationArtifactReferenceV2:
    return ValidationArtifactReferenceV2(kind, identity, version, digest)


def _archive_reference(
    contract_id: str, record_id: str, version: str, digest: str
) -> BiasArchiveReferenceV2:
    return BiasArchiveReferenceV2(contract_id, record_id, version, "1", digest)


def _empty_checks(
    *,
    replay_check_outcome: CheckOutcome,
    reason: str,
    request_ref: ValidationArtifactReferenceV2,
) -> tuple[BiasCheckObservationV2, ...]:
    return tuple(
        BiasCheckObservationV2(
            check_type,
            replay_check_outcome
            if check_type in _REPLAY_CHECK_TYPES
            else CheckOutcome.INCONCLUSIVE,
            reason
            if check_type in _REPLAY_CHECK_TYPES
            else _UNSUPPORTED_REASONS[check_type],
            (request_ref,) if check_type in _REPLAY_CHECK_TYPES else (),
        )
        for check_type in CHECK_TYPES
    )


def _source_closure(
    result: BacktestResultV3,
) -> tuple[
    BiasArchiveReferenceV2,
    BiasArchiveReferenceV2,
    tuple[BiasArchiveReferenceV2, ...],
    tuple[BiasArchiveReferenceV2, ...],
    BiasArchiveReferenceV2,
    str,
    str,
    str,
    str,
    str,
]:
    manifest = result.reconstruction_manifest
    return (
        _archive_reference(
            "C-092",
            result.dataset.dataset_id,
            result.dataset.version,
            result.dataset_sha256,
        ),
        _archive_reference(
            "C-101",
            manifest.universe_id,
            manifest.universe_version,
            manifest.universe_sha256,
        ),
        tuple(
            _archive_reference("C-102", str(pin.evidence_id), "1", pin.content_sha256)
            for pin in manifest.revision_pins
        ),
        tuple(
            _archive_reference("C-091", str(pin.evidence_id), "1", pin.content_sha256)
            for pin in manifest.source_pins
        ),
        _archive_reference(
            "C-103", result.manifest_sha256, "1", result.manifest_sha256
        ),
        result.dataset.dataset_id,
        result.dataset.version,
        result.dataset.lineage_sha256,
        manifest.universe_id,
        manifest.universe_version,
    )


def _build(
    request: SpotBacktestRunRequest,
    *,
    outcome: BiasAuditOutcomeV2,
    checks: tuple[BiasCheckObservationV2, ...],
    reasons: tuple[str, ...],
    as_of: datetime,
    created_at: datetime,
    replay_result: ValidationArtifactReferenceV2 | None = None,
    trace: ValidationArtifactReferenceV2 | None = None,
    dataset: BiasArchiveReferenceV2 | None = None,
    dataset_id: str | None = None,
    dataset_version: str | None = None,
    dataset_lineage_sha256: str | None = None,
    universe: BiasArchiveReferenceV2 | None = None,
    universe_id: str | None = None,
    universe_version: str | None = None,
    revisions: tuple[BiasArchiveReferenceV2, ...] = (),
    sources: tuple[BiasArchiveReferenceV2, ...] = (),
    manifest: BiasArchiveReferenceV2 | None = None,
    replay_as_of: datetime | None = None,
    replay_created_at: datetime | None = None,
    replay_expires_at: datetime | None = None,
) -> SpotBiasAuditResultV2:
    expires_at = min(
        request.expires_at,
        replay_expires_at if replay_expires_at is not None else request.expires_at,
    )
    if expires_at <= created_at:
        raise SpotBiasAuditInputError("REPLAY_EXPIRED_BEFORE_AUDIT_CREATION")
    return SpotBiasAuditResultV2.build(
        outcome=outcome,
        method=METHOD,
        method_version=METHOD_VERSION,
        request=_request_reference(request),
        replay_result=replay_result,
        trace=trace,
        strategy_version=_strategy_reference(request),
        dataset=dataset,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        dataset_lineage_sha256=dataset_lineage_sha256,
        universe=universe,
        universe_id=universe_id,
        universe_version=universe_version,
        revisions=revisions,
        sources=sources,
        manifest=manifest,
        request_as_of=request.result_as_of,
        request_created_at=request.created_at,
        request_expires_at=request.expires_at,
        replay_as_of=replay_as_of,
        replay_created_at=replay_created_at,
        replay_expires_at=replay_expires_at,
        as_of=as_of,
        created_at=created_at,
        expires_at=expires_at,
        checks=checks,
        reasons=reasons,
    )


async def run_spot_bias_audit(
    *,
    request: SpotBacktestRunRequest,
    session: AsyncSession,
    strategy_registry: StrategyVersionResolver,
    lineage_store: SqlAlchemyLineageStore,
    as_of: datetime,
    created_at: datetime,
) -> SpotBiasAuditResultV2:
    """Run the pinned replay once; never infer unsupported bias categories."""
    if type(request) is not SpotBacktestRunRequest:
        raise SpotBiasAuditInputError("EXACT_SPOT_BACKTEST_REQUEST_REQUIRED")
    now = _time("as_of", as_of)
    created = _time("created_at", created_at)
    if created < now or now < request.created_at or now >= request.expires_at:
        raise SpotBiasAuditInputError("INVALID_AUDIT_OR_REQUEST_CHRONOLOGY")
    request_ref = _request_reference(request)
    try:
        bundle = await run_spot_backtest(
            request=request,
            session=session,
            strategy_registry=strategy_registry,
            lineage_store=lineage_store,
        )
    except (ValueError, TypeError, KeyError, AttributeError):
        reason = "REPLAY_INPUT_OR_PROVENANCE_INVALID"
        return _build(
            request,
            outcome=BiasAuditOutcomeV2.FAILED,
            checks=_empty_checks(
                replay_check_outcome=CheckOutcome.FAILED,
                reason=reason,
                request_ref=request_ref,
            ),
            reasons=(reason, *_UNSUPPORTED_REASONS.values()),
            as_of=now,
            created_at=created,
        )
    except Exception as exc:
        reason = f"TRUSTED_REPLAY_UNAVAILABLE:{type(exc).__name__}"
        return _build(
            request,
            outcome=BiasAuditOutcomeV2.INCONCLUSIVE,
            checks=_empty_checks(
                replay_check_outcome=CheckOutcome.INCONCLUSIVE,
                reason=reason,
                request_ref=request_ref,
            ),
            reasons=(reason, *_UNSUPPORTED_REASONS.values()),
            as_of=now,
            created_at=created,
        )
    if (
        type(bundle) is not SpotBacktestBundle
        or bundle.outcome is not SpotBacktestOutcome.OBSERVED
        or type(bundle.result) is not BacktestResultV3
        or type(bundle.trace) is not SpotBacktestTrace
    ):
        invalid_evidence = type(bundle) is SpotBacktestBundle and any(
            marker in reason
            for reason in bundle.reason_codes
            for marker in ("MISMATCH", "INVALID", "FAILED", "CORRUPT")
        )
        reason = (
            "REPLAY_PIN_OR_PROVENANCE_MISMATCH"
            if invalid_evidence
            else "TRUSTED_REPLAY_UNAVAILABLE"
        )
        return _build(
            request,
            outcome=(
                BiasAuditOutcomeV2.FAILED
                if invalid_evidence
                else BiasAuditOutcomeV2.INCONCLUSIVE
            ),
            checks=_empty_checks(
                replay_check_outcome=(
                    CheckOutcome.FAILED
                    if invalid_evidence
                    else CheckOutcome.INCONCLUSIVE
                ),
                reason=reason,
                request_ref=request_ref,
            ),
            reasons=(reason, *_UNSUPPORTED_REASONS.values()),
            as_of=now,
            created_at=created,
        )
    result = bundle.result
    trace_value = bundle.trace
    try:
        resolved = resolve_spot_backtest_result(bundle)
    except (ValueError, TypeError, KeyError, AttributeError):
        reason = "REPLAY_PROVENANCE_OR_PIN_MISMATCH"
        return _build(
            request,
            outcome=BiasAuditOutcomeV2.FAILED,
            checks=_empty_checks(
                replay_check_outcome=CheckOutcome.FAILED,
                reason=reason,
                request_ref=request_ref,
            ),
            reasons=(reason, *_UNSUPPORTED_REASONS.values()),
            as_of=now,
            created_at=created,
        )
    replay_result = _reference("C-027", result.result_id, "3", result.content_sha256)
    trace = result.trace
    (
        dataset,
        universe,
        revisions,
        sources,
        manifest,
        dataset_id,
        dataset_version,
        dataset_lineage_sha256,
        universe_id,
        universe_version,
    ) = _source_closure(result)
    chronology_valid = (
        result == resolved
        and trace_value.content_sha256 == trace.content_sha256
        and trace_value.replay_request == request.replay_inputs
        and result.strategy_version.artifact_id
        == request.parameters.strategy_version_id
        and result.strategy_version.content_sha256 == request.parameters.strategy_sha256
        and result.as_of == request.result_as_of
        and result.created_at == request.created_at
        and result.expires_at == request.expires_at
        and result.expires_at > now
        and result.created_at <= now
    )
    integrity_valid = (
        result.market_type == "SPOT"
        and result.outcome is BacktestOutcomeV3.OBSERVED
        and result.data_integrity is CheckOutcome.PASSED
    )
    point_in_time_valid = (
        integrity_valid
        and result.point_in_time_correct is CheckOutcome.PASSED
        and chronology_valid
    )
    if (
        not chronology_valid
        or not integrity_valid
        or result.point_in_time_correct is not CheckOutcome.PASSED
    ):
        reason = (
            "REPLAY_CHRONOLOGY_MISMATCH"
            if not chronology_valid
            else "REPLAY_INTEGRITY_OR_MARKET_TYPE_FAILED"
            if not integrity_valid
            else "REPLAY_POINT_IN_TIME_CHECK_FAILED"
        )
        failed_checks = tuple(
            BiasCheckObservationV2(
                check_type,
                CheckOutcome.FAILED
                if check_type in _REPLAY_CHECK_TYPES
                else CheckOutcome.INCONCLUSIVE,
                reason
                if check_type in _REPLAY_CHECK_TYPES
                else _UNSUPPORTED_REASONS[check_type],
                (request_ref, replay_result, trace)
                if check_type in _REPLAY_CHECK_TYPES
                else (),
            )
            for check_type in CHECK_TYPES
        )
        return _build(
            request,
            outcome=BiasAuditOutcomeV2.FAILED,
            checks=failed_checks,
            reasons=(reason, *_UNSUPPORTED_REASONS.values()),
            as_of=now,
            created_at=created,
            replay_result=replay_result,
            trace=trace,
            dataset=dataset,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            dataset_lineage_sha256=dataset_lineage_sha256,
            universe=universe,
            universe_id=universe_id,
            universe_version=universe_version,
            revisions=revisions,
            sources=sources,
            manifest=manifest,
            replay_as_of=result.as_of,
            replay_created_at=result.created_at,
            replay_expires_at=result.expires_at,
        )
    replay_evidence = (request_ref, replay_result, trace)
    check_outcome = CheckOutcome.PASSED if point_in_time_valid else CheckOutcome.FAILED
    checks = tuple(
        BiasCheckObservationV2(
            check_type,
            check_outcome
            if check_type in _REPLAY_CHECK_TYPES
            else CheckOutcome.INCONCLUSIVE,
            "VERIFIED_ARCHIVE_BACKED_POINT_IN_TIME_REPLAY"
            if check_type in _REPLAY_CHECK_TYPES and point_in_time_valid
            else "POINT_IN_TIME_REPLAY_CHECK_FAILED"
            if check_type in _REPLAY_CHECK_TYPES
            else _UNSUPPORTED_REASONS[check_type],
            replay_evidence
            if check_type in (BiasCheckType.POINT_IN_TIME, BiasCheckType.LOOK_AHEAD)
            else (),
        )
        for check_type in CHECK_TYPES
    )
    return _build(
        request,
        outcome=BiasAuditOutcomeV2.INCONCLUSIVE,
        checks=checks,
        reasons=tuple(_UNSUPPORTED_REASONS.values()),
        as_of=now,
        created_at=created,
        replay_result=replay_result,
        trace=trace,
        dataset=dataset,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        dataset_lineage_sha256=dataset_lineage_sha256,
        universe=universe,
        universe_id=universe_id,
        universe_version=universe_version,
        revisions=revisions,
        sources=sources,
        manifest=manifest,
        replay_as_of=result.as_of,
        replay_created_at=result.created_at,
        replay_expires_at=result.expires_at,
    )


__all__ = ["SpotBiasAuditInputError", "run_spot_bias_audit"]
