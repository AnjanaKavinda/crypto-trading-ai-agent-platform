"""Synthetic supplemental derivatives fixtures; no exchange calls."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from trading_platform_api.market_data.derivatives_supplemental import (
    SupplementalCoverageStatus,
    RawSupplementalDerivativeRecord,
    SupplementalDerivativesError,
    SupplementalDerivativesKind,
    SupplementalDerivativesPolicy,
    normalize_supplemental_derivatives,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
POLICY = SupplementalDerivativesPolicy(
    "BTCUSDT-PERP", "fixture-venue", "PERPETUAL", "BTCUSDT"
)


def observation(
    kind: SupplementalDerivativesKind,
    **changes: object,
) -> RawSupplementalDerivativeRecord:
    values: dict[str, object] = {
        "source_record_id": uuid4(),
        "market_data_id": uuid4(),
        "provider_event_id": f"event-{kind.value.lower()}",
        "kind": kind,
        "instrument_id": POLICY.instrument_id,
        "venue_id": POLICY.venue_id,
        "market_type": POLICY.market_type,
        "contract_id": POLICY.contract_id,
        "observation_time": T0,
        "provider_time": T0 + timedelta(seconds=1),
        "retrieval_time": T0 + timedelta(seconds=2),
        "ingestion_time": T0 + timedelta(seconds=3),
        "availability_time": T0 + timedelta(seconds=4),
        "metric_name": kind.value.lower(),
        "value": Decimal("0.01"),
        "unit": "provider-declared-unit",
        "coverage_status": SupplementalCoverageStatus.UNKNOWN,
        "coverage_scope": None,
        "window_start": None,
        "window_end": None,
        "provider_id": "synthetic-provider",
        "provider_version": "1",
        "raw_schema_version": "1",
        "adapter_version": "1",
        "licensing_reference": "synthetic-fixture",
        "raw_source_bytes": b"synthetic record",
    }
    if kind is SupplementalDerivativesKind.BASIS:
        values.update(
            reference_kind="SPOT_INDEX",
            reference_instrument_id="BTCUSDT",
            reference_time=T0,
            basis_period_seconds=86_400,
        )
    elif kind is SupplementalDerivativesKind.LIQUIDATION:
        values.update(
            observation_time=T0 + timedelta(hours=1),
            provider_time=T0 + timedelta(hours=1, seconds=1),
            retrieval_time=T0 + timedelta(hours=1, seconds=2),
            ingestion_time=T0 + timedelta(hours=1, seconds=3),
            availability_time=T0 + timedelta(hours=1, seconds=4),
            coverage_status=SupplementalCoverageStatus.SAMPLED,
            window_start=T0,
            window_end=T0 + timedelta(hours=1),
            provider_side_label="SELL",
            provider_side_semantics="provider's raw liquidation side label",
        )
    else:
        values.update(
            observation_time=T0 + timedelta(days=1),
            provider_time=T0 + timedelta(days=1, seconds=1),
            retrieval_time=T0 + timedelta(days=1, seconds=2),
            ingestion_time=T0 + timedelta(days=1, seconds=3),
            availability_time=T0 + timedelta(days=1, seconds=4),
            window_start=T0,
            window_end=T0 + timedelta(days=1),
            population="accounts",
            cohort="all_accounts",
            sample_count=80,
            population_count=100,
        )
    values.update(changes)
    return RawSupplementalDerivativeRecord(**values)  # type: ignore[arg-type]


def test_basis_preserves_reference_period_unit_and_source_digest() -> None:
    item = observation(SupplementalDerivativesKind.BASIS)
    result = normalize_supplemental_derivatives((item,), POLICY)
    record = result.records[0]
    assert record.reference_instrument_id == "BTCUSDT"
    assert record.reference_kind == "SPOT_INDEX"
    assert record.basis_period_seconds == 86_400
    assert record.value == Decimal("0.01")
    assert record.unit == "provider-declared-unit"
    assert record.coverage_status is SupplementalCoverageStatus.UNKNOWN
    assert record.content_sha256


def test_basis_requires_explicit_reference_and_period() -> None:
    item = observation(
        SupplementalDerivativesKind.BASIS,
        reference_time=None,
    )
    with pytest.raises(SupplementalDerivativesError, match="Basis requires"):
        normalize_supplemental_derivatives((item,), POLICY)


def test_liquidation_preserves_sampled_coverage_and_raw_side_label() -> None:
    item = observation(SupplementalDerivativesKind.LIQUIDATION)
    result = normalize_supplemental_derivatives((item,), POLICY)
    record = result.records[0]
    assert record.provider_side_label == "SELL"
    assert record.provider_side_semantics == "provider's raw liquidation side label"
    assert record.coverage_status is SupplementalCoverageStatus.SAMPLED
    assert record.coverage_scope is None


def test_liquidation_requires_side_semantics_and_window() -> None:
    item = observation(
        SupplementalDerivativesKind.LIQUIDATION,
        provider_side_semantics=None,
    )
    with pytest.raises(SupplementalDerivativesError, match="Liquidations require"):
        normalize_supplemental_derivatives((item,), POLICY)


def test_complete_coverage_requires_an_explicit_scope() -> None:
    item = observation(
        SupplementalDerivativesKind.LIQUIDATION,
        coverage_status=SupplementalCoverageStatus.COMPLETE_WITH_DECLARED_SCOPE,
        coverage_scope=None,
    )
    with pytest.raises(SupplementalDerivativesError, match="declared scope"):
        normalize_supplemental_derivatives((item,), POLICY)


def test_positioning_preserves_population_cohort_and_sample_counts() -> None:
    item = observation(SupplementalDerivativesKind.POSITIONING)
    record = normalize_supplemental_derivatives((item,), POLICY).records[0]
    assert record.population == "accounts"
    assert record.cohort == "all_accounts"
    assert record.sample_count == 80
    assert record.population_count == 100


def test_positioning_rejects_sample_larger_than_population() -> None:
    item = observation(
        SupplementalDerivativesKind.POSITIONING,
        sample_count=101,
    )
    with pytest.raises(SupplementalDerivativesError, match="coverage counts"):
        normalize_supplemental_derivatives((item,), POLICY)


def test_duplicate_identity_is_reported_and_conflicts_fail_closed() -> None:
    item = observation(SupplementalDerivativesKind.BASIS)
    result = normalize_supplemental_derivatives((item, item), POLICY)
    assert len(result.records) == 1
    assert result.duplicate_event_ids == (item.provider_event_id,)
    with pytest.raises(SupplementalDerivativesError, match="Conflicting"):
        normalize_supplemental_derivatives(
            (item, replace(item, value=Decimal("0.02"))), POLICY
        )


def test_empty_batch_is_explicit_and_bounds_are_enforced() -> None:
    assert normalize_supplemental_derivatives((), POLICY).records == ()
    item = observation(SupplementalDerivativesKind.BASIS)
    with pytest.raises(SupplementalDerivativesError, match="exceeds"):
        normalize_supplemental_derivatives(
            (item, item), replace(POLICY, maximum_records=1)
        )
