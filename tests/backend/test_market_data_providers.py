from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from trading_platform_api.market_data import (
    AuthenticationRequirement,
    CapabilitySupport,
    DatasetVersion,
    DataSourceRecord,
    MarketData,
    MarketDataProvider,
    MarketDataRequest,
    MarketSnapshot,
    MetricValue,
    ProviderAvailability,
    ProviderBatch,
    ProviderBatchStatus,
    ProviderCapability,
    ProviderContractError,
    ProviderDataKind,
    ProviderDescriptor,
    ProviderError,
    ProviderFailureCode,
    ProviderRegistry,
    RateLimitKnowledge,
    RateLimitPolicy,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
T1 = T0 + timedelta(seconds=1)
T2 = T0 + timedelta(seconds=2)
T3 = T0 + timedelta(seconds=3)
T4 = T0 + timedelta(seconds=4)
HASH = "a" * 64


def rate_limit(**overrides: object) -> RateLimitPolicy:
    values: dict[str, object] = {
        "knowledge": RateLimitKnowledge.KNOWN,
        "window_seconds": 60,
        "maximum_requests": 100,
        "burst_limit": 10,
    }
    values.update(overrides)
    return RateLimitPolicy(**values)  # type: ignore[arg-type]


def capability(**overrides: object) -> ProviderCapability:
    values: dict[str, object] = {
        "data_kind": ProviderDataKind.OHLCV,
        "support": CapabilitySupport.SUPPORTED,
        "historical_support": CapabilitySupport.SUPPORTED,
        "realtime_support": CapabilitySupport.SUPPORTED,
        "rate_limit": rate_limit(),
        "market_types": ("spot",),
        "asset_ids": ("BTC",),
        "instrument_ids": ("BTC-USDT-SPOT",),
        "freshness_target_seconds": 5,
    }
    values.update(overrides)
    return ProviderCapability(**values)  # type: ignore[arg-type]


def descriptor(**overrides: object) -> ProviderDescriptor:
    values: dict[str, object] = {
        "provider_id": "provider-a",
        "provider_version": "api-v1",
        "provider_type": "exchange-market-data",
        "availability": ProviderAvailability.AVAILABLE,
        "authentication": AuthenticationRequirement.NONE,
        "raw_schema_version": "raw-v1",
        "adapter_version": "adapter-v1",
        "licensing_reference": "licensing-decision-reference",
        "capabilities": (capability(),),
    }
    values.update(overrides)
    return ProviderDescriptor(**values)  # type: ignore[arg-type]


def request(**overrides: object) -> MarketDataRequest:
    values: dict[str, object] = {
        "request_id": uuid4(),
        "correlation_id": "correlation-1",
        "data_kind": ProviderDataKind.OHLCV,
        "instrument_id": "BTC-USDT-SPOT",
        "venue_id": "venue-a",
        "requested_at": T4,
        "as_of": T3,
        "range_start": T0,
        "range_end": T2,
        "maximum_records": 100,
    }
    values.update(overrides)
    return MarketDataRequest(**values)  # type: ignore[arg-type]


def source_record(**overrides: object) -> DataSourceRecord:
    values: dict[str, object] = {
        "source_record_id": uuid4(),
        "provider_id": "provider-a",
        "provider_version": "api-v1",
        "provider_event_time": T0,
        "retrieval_time": T1,
        "availability_time": T2,
        "raw_schema_version": "raw-v1",
        "adapter_version": "adapter-v1",
        "licensing_reference": "licensing-decision-reference",
        "content_sha256": HASH,
    }
    values.update(overrides)
    return DataSourceRecord(**values)  # type: ignore[arg-type]


def observation(source_id: UUID, **overrides: object) -> MarketData:
    values: dict[str, object] = {
        "market_data_id": uuid4(),
        "instrument_id": "BTC-USDT-SPOT",
        "venue_id": "venue-a",
        "observation_type": ProviderDataKind.OHLCV.value,
        "event_time": T0,
        "provider_time": T1,
        "ingestion_time": T2,
        "availability_time": T3,
        "source_record_id": source_id,
        "metrics": (
            MetricValue(metric_name="close", value=Decimal("100"), unit="USD"),
        ),
    }
    values.update(overrides)
    return MarketData(**values)  # type: ignore[arg-type]


def canonical_batch(**overrides: object) -> ProviderBatch:
    source = source_record()
    data = observation(source.source_record_id)
    values: dict[str, object] = {
        "request_id": uuid4(),
        "provider_id": "provider-a",
        "provider_version": "api-v1",
        "data_kind": ProviderDataKind.OHLCV,
        "status": ProviderBatchStatus.COMPLETE,
        "retrieved_at": T3,
        "fresh_until": T4,
        "source_records": (source,),
        "market_data": (data,),
    }
    values.update(overrides)
    return ProviderBatch(**values)  # type: ignore[arg-type]


class FakeProvider:
    def __init__(
        self,
        metadata: ProviderDescriptor,
        response: ProviderBatch | None = None,
    ) -> None:
        self._descriptor = metadata
        self._response = response

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    async def fetch(self, item: MarketDataRequest) -> ProviderBatch:
        if self._response is None:
            return ProviderBatch(
                request_id=item.request_id,
                provider_id=self.descriptor.provider_id,
                provider_version=self.descriptor.provider_version,
                data_kind=item.data_kind,
                status=ProviderBatchStatus.EMPTY,
                retrieved_at=item.requested_at,
                fresh_until=item.requested_at,
            )
        return self._response


def test_exact_enum_vocabularies() -> None:
    assert {item.value for item in ProviderDataKind} == {
        "OHLCV",
        "TRADE",
        "TICK",
        "ORDER_BOOK",
        "FUNDING",
        "OPEN_INTEREST",
        "LIQUIDATION",
        "DERIVATIVES",
        "ON_CHAIN",
        "FUNDAMENTAL",
        "NEWS",
        "SENTIMENT",
        "MACRO",
    }
    assert {item.value for item in CapabilitySupport} == {
        "SUPPORTED",
        "UNSUPPORTED",
        "UNKNOWN",
    }
    assert {item.value for item in AuthenticationRequirement} == {
        "NONE",
        "API_KEY",
        "OAUTH2",
        "SIGNED_REQUEST",
        "UNKNOWN",
    }
    assert {item.value for item in ProviderAvailability} == {
        "AVAILABLE",
        "DEGRADED",
        "UNAVAILABLE",
        "UNKNOWN",
    }
    assert {item.value for item in ProviderBatchStatus} == {
        "COMPLETE",
        "PARTIAL",
        "EMPTY",
        "STALE",
    }
    assert {item.value for item in ProviderFailureCode} == {
        "INVALID_REQUEST",
        "UNSUPPORTED_CAPABILITY",
        "RATE_LIMITED",
        "TIMEOUT",
        "UNAVAILABLE",
        "AUTHENTICATION_FAILED",
        "AUTHORIZATION_FAILED",
        "INVALID_RESPONSE",
        "STALE_RESPONSE",
        "LICENSING_RESTRICTED",
        "UNKNOWN",
    }


def test_boundary_values_are_frozen_slotted_and_tuple_based() -> None:
    values = (rate_limit(), capability(), descriptor(), request(), canonical_batch())
    for value in values:
        assert value.__dataclass_params__.frozen is True
        assert hasattr(value, "__slots__")
        with pytest.raises(FrozenInstanceError):
            setattr(value, fields(value)[0].name, object())
    tuple_fields = {
        item.name
        for value in values
        for item in fields(value)
        if isinstance(getattr(value, item.name), tuple)
    }
    assert tuple_fields.issuperset({"capabilities", "source_records", "market_data"})


@pytest.mark.parametrize("bad", [0, -1, 1.0, True])
def test_known_rate_limit_requires_positive_integers(bad: object) -> None:
    with pytest.raises(ProviderContractError, match="positive integer"):
        rate_limit(window_seconds=bad)


def test_known_rate_limit_requires_every_numeric_value() -> None:
    with pytest.raises(ProviderContractError, match="require window"):
        rate_limit(window_seconds=None)


def test_rate_limit_known_unknown_and_burst_consistency() -> None:
    unknown = RateLimitPolicy(RateLimitKnowledge.UNKNOWN)
    not_applicable = RateLimitPolicy(RateLimitKnowledge.NOT_APPLICABLE)
    assert unknown.maximum_requests is None
    assert not_applicable.window_seconds is None
    with pytest.raises(ProviderContractError, match="must not invent"):
        RateLimitPolicy(RateLimitKnowledge.UNKNOWN, maximum_requests=1)
    with pytest.raises(ProviderContractError, match="must not exceed"):
        rate_limit(maximum_requests=10, burst_limit=11)


@pytest.mark.parametrize(
    ("support", "historical", "realtime"),
    [
        (
            CapabilitySupport.UNSUPPORTED,
            CapabilitySupport.UNSUPPORTED,
            CapabilitySupport.UNSUPPORTED,
        ),
        (
            CapabilitySupport.UNKNOWN,
            CapabilitySupport.UNKNOWN,
            CapabilitySupport.UNKNOWN,
        ),
    ],
)
def test_unknown_or_unsupported_capability_cannot_claim_details(
    support: CapabilitySupport,
    historical: CapabilitySupport,
    realtime: CapabilitySupport,
) -> None:
    with pytest.raises(ProviderContractError, match="support details"):
        capability(
            support=support,
            historical_support=historical,
            realtime_support=realtime,
        )


def test_non_supported_capability_can_be_declared_without_invented_details() -> None:
    unknown = capability(
        support=CapabilitySupport.UNKNOWN,
        historical_support=CapabilitySupport.UNKNOWN,
        realtime_support=CapabilitySupport.UNKNOWN,
        rate_limit=RateLimitPolicy(RateLimitKnowledge.UNKNOWN),
        market_types=(),
        asset_ids=(),
        instrument_ids=(),
        freshness_target_seconds=None,
    )
    unsupported = capability(
        data_kind=ProviderDataKind.NEWS,
        support=CapabilitySupport.UNSUPPORTED,
        historical_support=CapabilitySupport.UNSUPPORTED,
        realtime_support=CapabilitySupport.UNSUPPORTED,
        rate_limit=RateLimitPolicy(RateLimitKnowledge.NOT_APPLICABLE),
        market_types=(),
        asset_ids=(),
        instrument_ids=(),
        freshness_target_seconds=None,
    )
    assert unknown.support is CapabilitySupport.UNKNOWN
    assert unsupported.support is CapabilitySupport.UNSUPPORTED


def test_supported_capability_requires_an_actual_access_mode() -> None:
    with pytest.raises(ProviderContractError, match="historical or real-time"):
        capability(
            historical_support=CapabilitySupport.UNKNOWN,
            realtime_support=CapabilitySupport.UNSUPPORTED,
        )


def test_capability_and_descriptor_reject_duplicates_and_bad_metadata() -> None:
    with pytest.raises(ProviderContractError, match="duplicates"):
        capability(asset_ids=("BTC", "BTC"))
    with pytest.raises(ProviderContractError, match="duplicates"):
        descriptor(capabilities=(capability(), capability()))
    with pytest.raises(ProviderContractError, match="surrounding whitespace"):
        descriptor(provider_id=" provider-a")
    with pytest.raises(ProviderContractError, match="sensitive data"):
        descriptor(
            licensing_reference="https://" + "user" + ":" + "password@example.invalid"
        )


def test_descriptor_capability_lookup_is_exact_and_non_selecting() -> None:
    metadata = descriptor()
    assert metadata.capability(ProviderDataKind.OHLCV) == metadata.capabilities[0]
    assert metadata.capability(ProviderDataKind.NEWS) is None
    with pytest.raises(ProviderContractError, match="ProviderDataKind"):
        metadata.capability("OHLCV")  # type: ignore[arg-type]


def test_request_normalizes_time_and_enforces_chronology() -> None:
    offset = timezone(timedelta(hours=5, minutes=30))
    value = request(
        requested_at=datetime(2026, 1, 1, 5, 30, 4, tzinfo=offset),
        as_of=datetime(2026, 1, 1, 5, 30, 3, tzinfo=offset),
        range_start=datetime(2026, 1, 1, 5, 30, tzinfo=offset),
        range_end=datetime(2026, 1, 1, 5, 30, 2, tzinfo=offset),
    )
    assert value.requested_at == T4
    assert value.range_start == T0
    with pytest.raises(ProviderContractError, match="as_of"):
        request(as_of=T4, requested_at=T3)
    with pytest.raises(ProviderContractError, match="range_start"):
        request(range_start=T2, range_end=T1)
    with pytest.raises(ProviderContractError, match="range_end"):
        request(range_end=T4, as_of=T3)


def test_request_rejects_partial_range_naive_time_and_unbounded_count() -> None:
    with pytest.raises(ProviderContractError, match="supplied together"):
        request(range_start=None, range_end=T2)
    with pytest.raises(ProviderContractError, match="timezone-aware"):
        request(requested_at=datetime(2026, 1, 1))
    with pytest.raises(ProviderContractError, match="must not exceed"):
        request(maximum_records=100_001)
    with pytest.raises(ProviderContractError, match="positive integer"):
        request(maximum_records=True)


def test_batch_requires_exact_canonical_types_and_provider_alignment() -> None:
    with pytest.raises(ProviderContractError, match="exact DataSourceRecord"):
        canonical_batch(source_records=(object(),))
    source = source_record(provider_id="provider-b")
    with pytest.raises(ProviderContractError, match="provider identity"):
        canonical_batch(
            source_records=(source,),
            market_data=(observation(source.source_record_id),),
        )


def test_batch_requires_complete_canonical_reference_alignment() -> None:
    source = source_record()
    other_source = uuid4()
    with pytest.raises(ProviderContractError, match="source must exist"):
        canonical_batch(
            source_records=(source,), market_data=(observation(other_source),)
        )
    with pytest.raises(ProviderContractError, match="observation type"):
        canonical_batch(
            source_records=(source,),
            market_data=(
                observation(source.source_record_id, observation_type="TRADE"),
            ),
        )


def test_batch_validates_snapshots_and_datasets_against_batch_evidence() -> None:
    source = source_record()
    data = observation(source.source_record_id)
    snapshot = MarketSnapshot(
        snapshot_id=uuid4(),
        as_of=T3,
        created_at=T4,
        instrument_id=data.instrument_id,
        venue_id=data.venue_id,
        market_data_ids=(data.market_data_id,),
        source_record_ids=(source.source_record_id,),
    )
    dataset = DatasetVersion(
        dataset_id="dataset-a",
        version="v1",
        created_at=T4,
        coverage_start=T0,
        coverage_end=T1,
        point_in_time_cutoff=T3,
        source_record_ids=(source.source_record_id,),
        canonical_schema_version="1",
        lineage_sha256=HASH,
    )
    result = canonical_batch(
        source_records=(source,),
        market_data=(data,),
        snapshots=(snapshot,),
        datasets=(dataset,),
    )
    assert result.snapshots == (snapshot,)
    assert result.datasets == (dataset,)
    with pytest.raises(ProviderContractError, match="snapshot source"):
        canonical_batch(
            source_records=(source,),
            market_data=(data,),
            snapshots=(
                MarketSnapshot(
                    snapshot_id=uuid4(),
                    as_of=T3,
                    created_at=T4,
                    instrument_id=data.instrument_id,
                    venue_id=data.venue_id,
                    market_data_ids=(data.market_data_id,),
                    source_record_ids=(uuid4(),),
                ),
            ),
        )


def test_batch_status_and_freshness_invariants() -> None:
    empty = ProviderBatch(
        request_id=uuid4(),
        provider_id="provider-a",
        provider_version="api-v1",
        data_kind=ProviderDataKind.OHLCV,
        status=ProviderBatchStatus.EMPTY,
        retrieved_at=T3,
        fresh_until=T3,
    )
    assert empty.market_data == ()
    with pytest.raises(ProviderContractError, match="must not contain payload"):
        canonical_batch(status=ProviderBatchStatus.EMPTY)
    source = source_record()
    with pytest.raises(ProviderContractError, match="canonical source evidence"):
        canonical_batch(source_records=(source,), market_data=())
    stale = canonical_batch(
        status=ProviderBatchStatus.STALE,
        retrieved_at=T4,
        fresh_until=T3,
    )
    assert stale.status is ProviderBatchStatus.STALE
    with pytest.raises(ProviderContractError, match="STALE"):
        canonical_batch(status=ProviderBatchStatus.STALE)
    with pytest.raises(ProviderContractError, match="expired freshness"):
        canonical_batch(retrieved_at=T4, fresh_until=T3)


def test_batch_rejects_duplicate_canonical_identities_and_warnings() -> None:
    source = source_record()
    data = observation(source.source_record_id)
    with pytest.raises(ProviderContractError, match="source record IDs"):
        canonical_batch(source_records=(source, source), market_data=(data,))
    with pytest.raises(ProviderContractError, match="market data IDs"):
        canonical_batch(source_records=(source,), market_data=(data, data))
    with pytest.raises(ProviderContractError, match="duplicates"):
        canonical_batch(warnings=("partial", "partial"))


@pytest.mark.parametrize("code", list(ProviderFailureCode))
def test_sanitized_provider_error_preserves_stable_failure_codes(
    code: ProviderFailureCode,
) -> None:
    error = ProviderError(code, "Safe provider failure.", retryable=False)
    assert error.code is code
    assert str(error) == f"{code.value}: Safe provider failure."


def test_provider_error_rejects_sensitive_or_contradictory_metadata() -> None:
    authority = "{}:{}@example.invalid".format("user", "password")
    basic_auth_url = "https://" + authority + "/path"
    for detail in (
        "token=abc123",
        "Bearer abc123",
        basic_auth_url,
        "unsafe\nresponse",
    ):
        with pytest.raises(ProviderContractError):
            ProviderError(
                ProviderFailureCode.INVALID_RESPONSE,
                detail,
                retryable=False,
            )
    with pytest.raises(ProviderContractError, match="requires retryable"):
        ProviderError(
            ProviderFailureCode.RATE_LIMITED,
            "Rate limited.",
            retryable=False,
            retry_after_seconds=1,
        )
    retryable = ProviderError(
        ProviderFailureCode.RATE_LIMITED,
        "Rate limited.",
        retryable=True,
        retry_after_seconds=0,
    )
    assert retryable.retry_after_seconds == 0


def test_fake_provider_satisfies_async_protocol_without_network_behavior() -> None:
    fake = FakeProvider(descriptor())
    item = request(range_start=None, range_end=None)

    assert isinstance(fake, MarketDataProvider)
    result = asyncio.run(fake.fetch(item))
    assert result.request_id == item.request_id
    assert result.status is ProviderBatchStatus.EMPTY


def test_registry_rejects_duplicate_or_non_provider_entries() -> None:
    first = FakeProvider(descriptor())
    duplicate = FakeProvider(descriptor())
    with pytest.raises(ProviderContractError, match="provider IDs"):
        ProviderRegistry((first, duplicate))
    with pytest.raises(ProviderContractError, match="protocol"):
        ProviderRegistry((object(),))  # type: ignore[arg-type]


def test_registry_lookup_is_exact_and_failure_is_sanitized() -> None:
    fake = FakeProvider(descriptor())
    registry = ProviderRegistry((fake,))
    assert registry.require("provider-a") is fake
    with pytest.raises(ProviderError) as captured:
        registry.require("missing-provider")
    assert captured.value.code is ProviderFailureCode.UNSUPPORTED_CAPABILITY
    assert captured.value.retryable is False


def test_registry_candidates_are_deterministic_without_automatic_preference() -> None:
    provider_b = FakeProvider(descriptor(provider_id="provider-b"))
    provider_a = FakeProvider(descriptor(provider_id="provider-a"))
    unknown = FakeProvider(
        descriptor(
            provider_id="provider-unknown",
            capabilities=(
                capability(
                    support=CapabilitySupport.UNKNOWN,
                    historical_support=CapabilitySupport.UNKNOWN,
                    realtime_support=CapabilitySupport.UNKNOWN,
                    rate_limit=RateLimitPolicy(RateLimitKnowledge.UNKNOWN),
                    market_types=(),
                    asset_ids=(),
                    instrument_ids=(),
                    freshness_target_seconds=None,
                ),
            ),
        )
    )
    degraded = FakeProvider(
        descriptor(
            provider_id="provider-degraded",
            availability=ProviderAvailability.DEGRADED,
        )
    )
    registry = ProviderRegistry((provider_b, unknown, degraded, provider_a))

    candidates = registry.candidates(
        ProviderDataKind.OHLCV,
        require_historical=True,
        require_realtime=True,
    )
    assert tuple(item.descriptor.provider_id for item in candidates) == (
        "provider-a",
        "provider-b",
    )
    assert registry.candidates(ProviderDataKind.NEWS) == ()


def test_public_exports_do_not_introduce_network_or_trading_surface() -> None:
    import trading_platform_api.market_data.providers as provider_module

    forbidden_names = {
        "AsyncClient",
        "ClientSession",
        "WebSocket",
        "place_order",
        "submit_order",
        "execute_trade",
        "api_key",
        "secret",
    }
    assert forbidden_names.isdisjoint(provider_module.__dict__)
    assert set(provider_module.__all__) == {
        "AuthenticationRequirement",
        "CapabilitySupport",
        "MarketDataProvider",
        "MarketDataRequest",
        "ProviderAvailability",
        "ProviderBatch",
        "ProviderBatchStatus",
        "ProviderCapability",
        "ProviderContractError",
        "ProviderDataKind",
        "ProviderDescriptor",
        "ProviderError",
        "ProviderFailureCode",
        "ProviderRegistry",
        "RateLimitKnowledge",
        "RateLimitPolicy",
    }
