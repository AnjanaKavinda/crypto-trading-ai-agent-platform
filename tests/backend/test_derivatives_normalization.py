"""Synthetic derivatives fixtures; no exchange calls or profitability claims."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from uuid import uuid4

import pytest
from trading_platform_api.market_data.derivatives import (
    DerivativesNormalizationError,
    DerivativesPolicy,
    OpenInterestUnit,
    RawDerivativesObservation,
    normalize_derivatives,
)
from trading_platform_api.market_data.providers import ProviderDataKind

T0 = datetime(2026, 1, 1, tzinfo=UTC)
POLICY = DerivativesPolicy("BTCUSDT-PERP", "fixture-venue", "PERPETUAL", "BTCUSDT")


def observation(
    kind: ProviderDataKind = ProviderDataKind.FUNDING,
    **changes: object,
) -> RawDerivativesObservation:
    values: dict[str, object] = {
        "source_record_id": uuid4(),
        "market_data_id": uuid4(),
        "provider_event_id": "event-1",
        "instrument_id": POLICY.instrument_id,
        "venue_id": POLICY.venue_id,
        "market_type": POLICY.market_type,
        "contract_id": POLICY.contract_id,
        "data_kind": kind,
        "observation_time": T0,
        "value": Decimal("0.0001")
        if kind is ProviderDataKind.FUNDING
        else Decimal("200"),
        "open_interest_unit": (
            None if kind is ProviderDataKind.FUNDING else OpenInterestUnit.CONTRACTS
        ),
        "funding_interval_seconds": 28800 if kind is ProviderDataKind.FUNDING else None,
        "provider_id": "synthetic-provider",
        "provider_version": "1",
        "raw_schema_version": "1",
        "adapter_version": "1",
        "licensing_reference": "synthetic-fixture",
        "raw_source_bytes": b"synthetic record",
        "retrieval_time": T0 + timedelta(seconds=1),
        "ingestion_time": T0 + timedelta(seconds=2),
        "availability_time": T0 + timedelta(seconds=3),
    }
    values.update(changes)
    return RawDerivativesObservation(**values)  # type: ignore[arg-type]


def test_funding_and_oi_preserve_units_provenance_and_contract_identity() -> None:
    funding = observation()
    oi = observation(ProviderDataKind.OPEN_INTEREST, provider_event_id="event-2")
    result = normalize_derivatives((funding, oi), POLICY)
    assert len(result.market_data) == len(result.derivatives_data) == 2
    assert (
        result.source_records[0].content_sha256
        == sha256(funding.raw_source_bytes).hexdigest()
    )
    assert result.market_data[0].metrics[0].unit == "fraction_per_interval"
    assert result.market_data[0].metrics[1].value == Decimal("28800")
    assert result.market_data[1].metrics[0].unit == "contracts"
    assert result.identities[1].contract_id == "BTCUSDT"
    assert result.market_data[1].source_record_id == oi.source_record_id


@pytest.mark.parametrize(
    "changes",
    [
        {"open_interest_unit": None},
        {"value": Decimal("-1")},
        {"value": Decimal("NaN")},
        {"funding_interval_seconds": 8},
        {"contract_id": "OTHER"},
        {"retrieval_time": T0 - timedelta(seconds=1)},
        {"raw_source_bytes": b""},
    ],
)
def test_open_interest_rejects_ambiguous_or_invalid_input(
    changes: dict[str, object],
) -> None:
    item = observation(ProviderDataKind.OPEN_INTEREST, **changes)
    with pytest.raises(DerivativesNormalizationError):
        normalize_derivatives((item,), POLICY)


@pytest.mark.parametrize(
    "changes",
    [
        {"funding_interval_seconds": None},
        {"funding_interval_seconds": 0},
        {"funding_interval_seconds": True},
        {"open_interest_unit": OpenInterestUnit.BASE_ASSET},
        {"value": Decimal("Infinity")},
    ],
)
def test_funding_rejects_missing_interval_or_invalid_value(
    changes: dict[str, object],
) -> None:
    with pytest.raises(DerivativesNormalizationError):
        normalize_derivatives((observation(**changes),), POLICY)


def test_exact_duplicate_is_reported_but_conflict_is_rejected() -> None:
    item = observation()
    result = normalize_derivatives((item, item), POLICY)
    assert len(result.market_data) == 1
    assert result.duplicate_event_ids == ("event-1",)
    with pytest.raises(DerivativesNormalizationError, match="Conflicting"):
        normalize_derivatives((item, replace(item, value=Decimal("0.01"))), POLICY)


def test_gap_is_not_fabricated_and_empty_batch_is_explicit() -> None:
    assert normalize_derivatives((), POLICY).market_data == ()
    first = observation()
    later = observation(
        provider_event_id="event-2",
        observation_time=T0 + timedelta(days=10),
        retrieval_time=T0 + timedelta(days=10, seconds=1),
        ingestion_time=T0 + timedelta(days=10, seconds=2),
        availability_time=T0 + timedelta(days=10, seconds=3),
    )
    result = normalize_derivatives((first, later), POLICY)
    assert len(result.market_data) == 2
    with pytest.raises(DerivativesNormalizationError, match="Out-of-order"):
        normalize_derivatives((later, first), POLICY)


def test_market_types_and_batch_limits_are_enforced() -> None:
    with pytest.raises(DerivativesNormalizationError):
        DerivativesPolicy("a", "v", "SPOT", "a")
    with pytest.raises(DerivativesNormalizationError, match="exceeds"):
        normalize_derivatives(
            (observation(), observation()), replace(POLICY, maximum_records=1)
        )
    with pytest.raises(DerivativesNormalizationError, match="Funding"):
        normalize_derivatives(
            (replace(observation(), market_type="DATED_FUTURE"),),
            replace(POLICY, market_type="DATED_FUTURE"),
        )
    with pytest.raises(DerivativesNormalizationError, match="kind"):
        normalize_derivatives(
            (replace(observation(), data_kind="FUNDING"),),  # type: ignore[arg-type]
            POLICY,
        )
