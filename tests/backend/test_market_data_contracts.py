from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from trading_platform_api.market_data import (
    DataQualityReport,
    DataQualityStatus,
    DatasetVersion,
    DatasetVersionReference,
    DataSourceRecord,
    DerivativesData,
    EventData,
    FeatureSet,
    FeatureValue,
    FundamentalData,
    MacroData,
    MarketData,
    MarketDataContractError,
    MarketSnapshot,
    MetricValue,
    OnChainData,
    SentimentData,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
T1 = T0 + timedelta(seconds=1)
T2 = T0 + timedelta(seconds=2)
T3 = T0 + timedelta(seconds=3)
T4 = T0 + timedelta(seconds=4)
HASH_A = "a" * 64
HASH_B = "b" * 64


def metric(name: str = "close") -> MetricValue:
    return MetricValue(metric_name=name, value=Decimal("100.25"), unit="USD")


def source_record(**overrides: object) -> DataSourceRecord:
    values: dict[str, object] = {
        "source_record_id": uuid4(),
        "provider_id": "provider-a",
        "provider_version": "1.0",
        "provider_event_time": T0,
        "retrieval_time": T1,
        "availability_time": T2,
        "raw_schema_version": "raw-v1",
        "adapter_version": "adapter-v1",
        "licensing_reference": "license-record-1",
        "content_sha256": HASH_A,
    }
    values.update(overrides)
    return DataSourceRecord(**values)  # type: ignore[arg-type]


def market_data(**overrides: object) -> MarketData:
    values: dict[str, object] = {
        "market_data_id": uuid4(),
        "instrument_id": "BTC-USDT-SPOT",
        "venue_id": "venue-a",
        "observation_type": "OHLCV",
        "event_time": T0,
        "provider_time": T1,
        "ingestion_time": T2,
        "availability_time": T3,
        "source_record_id": uuid4(),
        "metrics": (metric(),),
    }
    values.update(overrides)
    return MarketData(**values)  # type: ignore[arg-type]


def dataset_version(**overrides: object) -> DatasetVersion:
    values: dict[str, object] = {
        "dataset_id": "btc-hourly",
        "version": "v1",
        "created_at": T4,
        "coverage_start": T0,
        "coverage_end": T1,
        "point_in_time_cutoff": T3,
        "source_record_ids": (uuid4(),),
        "canonical_schema_version": "market-v1",
        "lineage_sha256": HASH_B,
    }
    values.update(overrides)
    return DatasetVersion(**values)  # type: ignore[arg-type]


def snapshot(**overrides: object) -> MarketSnapshot:
    values: dict[str, object] = {
        "snapshot_id": uuid4(),
        "as_of": T3,
        "created_at": T4,
        "instrument_id": "BTC-USDT-SPOT",
        "venue_id": "venue-a",
        "market_data_ids": (uuid4(),),
        "source_record_ids": (uuid4(),),
    }
    values.update(overrides)
    return MarketSnapshot(**values)  # type: ignore[arg-type]


def quality_report(**overrides: object) -> DataQualityReport:
    values: dict[str, object] = {
        "report_id": uuid4(),
        "snapshot_id": uuid4(),
        "assessed_at": T4,
        "required_data_cutoff": T3,
        "completeness": Decimal("1"),
        "freshness": Decimal("1"),
        "accuracy": Decimal("0.9"),
        "consistency": Decimal("0.9"),
        "source_reliability": Decimal("0.8"),
        "coverage": Decimal("1"),
        "continuity": Decimal("0.95"),
        "status": DataQualityStatus.VALID,
    }
    values.update(overrides)
    return DataQualityReport(**values)  # type: ignore[arg-type]


def feature_set(**overrides: object) -> FeatureSet:
    values: dict[str, object] = {
        "feature_set_id": uuid4(),
        "market_snapshot_id": uuid4(),
        "calculated_at": T4,
        "as_of": T3,
        "definition_set_version": "feature-set-v1",
        "features": (
            FeatureValue(
                feature_id="return-1h",
                feature_name="one_hour_return",
                value=Decimal("0.01"),
                unit="ratio",
                definition_version="v1",
            ),
        ),
        "source_record_ids": (uuid4(),),
    }
    values.update(overrides)
    return FeatureSet(**values)  # type: ignore[arg-type]


def test_all_canonical_contract_ids_and_schema_versions() -> None:
    contracts = (
        market_data(),
        snapshot(),
        quality_report(),
        feature_set(),
        source_record(),
        dataset_version(),
    )
    assert [(item.contract_id, item.schema_version) for item in contracts] == [
        ("C-001", "1"),
        ("C-002", "1"),
        ("C-003", "1"),
        ("C-004", "1"),
        ("C-091", "1"),
        ("C-092", "1"),
    ]


@pytest.mark.parametrize(
    "instance",
    [
        market_data(),
        snapshot(),
        quality_report(),
        feature_set(),
        source_record(),
        dataset_version(),
    ],
)
def test_canonical_contracts_are_frozen(instance: object) -> None:
    with pytest.raises(FrozenInstanceError):
        instance.schema_version = "2"  # type: ignore[attr-defined]


def test_aware_datetimes_are_normalized_to_utc() -> None:
    offset_time = datetime(
        2026, 1, 1, 5, 30, tzinfo=timezone(timedelta(hours=5, minutes=30))
    )
    value = source_record(
        provider_event_time=offset_time,
        retrieval_time=offset_time,
        availability_time=offset_time,
    )
    assert value.provider_event_time == T0
    assert value.provider_event_time.tzinfo is UTC


@pytest.mark.parametrize(
    ("factory", "field_name"),
    [
        (source_record, "provider_event_time"),
        (market_data, "event_time"),
        (dataset_version, "coverage_start"),
        (snapshot, "as_of"),
        (quality_report, "assessed_at"),
        (feature_set, "as_of"),
    ],
)
def test_naive_datetimes_are_rejected(factory: object, field_name: str) -> None:
    with pytest.raises(MarketDataContractError, match="timezone-aware"):
        factory(**{field_name: datetime(2026, 1, 1)})  # type: ignore[operator]


@pytest.mark.parametrize(
    "bad_value", [1, 1.0, True, Decimal("NaN"), Decimal("Infinity")]
)
def test_metric_values_require_finite_decimals(bad_value: object) -> None:
    with pytest.raises(MarketDataContractError):
        MetricValue(metric_name="price", value=bad_value, unit="USD")  # type: ignore[arg-type]


@pytest.mark.parametrize("field_name", ["metric_name", "unit"])
def test_metric_values_require_stable_names_and_units(field_name: str) -> None:
    values = {"metric_name": "price", "value": Decimal("1"), "unit": "USD"}
    values[field_name] = " "
    with pytest.raises(MarketDataContractError, match="blank"):
        MetricValue(**values)  # type: ignore[arg-type]


def test_market_data_rejects_duplicate_metrics_and_invalid_chronology() -> None:
    with pytest.raises(MarketDataContractError, match="duplicates"):
        market_data(metrics=(metric(), metric()))
    with pytest.raises(MarketDataContractError, match="event_time"):
        market_data(event_time=T2, provider_time=T1)


def test_source_record_requires_ordered_provenance_and_sha256() -> None:
    with pytest.raises(MarketDataContractError, match="retrieval_time"):
        source_record(retrieval_time=T3, availability_time=T2)
    with pytest.raises(MarketDataContractError, match="SHA-256"):
        source_record(content_sha256="not-a-hash")
    with pytest.raises(MarketDataContractError, match="lowercase"):
        source_record(content_sha256="A" * 64)


def test_dataset_version_enforces_reproducible_lineage() -> None:
    duplicate = uuid4()
    with pytest.raises(MarketDataContractError, match="duplicates"):
        dataset_version(source_record_ids=(duplicate, duplicate))
    with pytest.raises(MarketDataContractError, match="coverage_start"):
        dataset_version(coverage_start=T2, coverage_end=T1)
    with pytest.raises(MarketDataContractError, match="coverage_end"):
        dataset_version(coverage_end=T4, point_in_time_cutoff=T3)
    with pytest.raises(MarketDataContractError, match="point_in_time_cutoff"):
        dataset_version(point_in_time_cutoff=T4, created_at=T3)
    with pytest.raises(MarketDataContractError, match="SHA-256"):
        dataset_version(lineage_sha256="invalid")


def test_embedded_data_is_data_only_and_point_in_time_safe() -> None:
    source_id = uuid4()
    embedded_types = (
        FundamentalData,
        OnChainData,
        DerivativesData,
        SentimentData,
        MacroData,
    )
    for embedded_type in embedded_types:
        value = embedded_type(
            observation_time=T0,
            availability_time=T2,
            source_record_id=source_id,
            metrics=(metric(),),
        )
        assert value.availability_time == T2
        field_names = {item.name for item in fields(value)}
        assert not field_names.intersection(
            {
                "confidence",
                "probability",
                "direction",
                "recommendation",
                "signal",
                "order",
            }
        )


def test_snapshot_accepts_available_embedded_data_and_exact_dataset_reference() -> None:
    source_id = uuid4()
    event = EventData(
        event_id="event-1",
        event_type="economic-release",
        event_time=T0,
        availability_time=T2,
        source_record_id=source_id,
    )
    value = snapshot(
        source_record_ids=(source_id,),
        event_data=(event,),
        dataset_version=DatasetVersionReference(dataset_id="dataset-1", version="v1"),
    )
    assert value.event_data == (event,)
    assert value.dataset_version == DatasetVersionReference("dataset-1", "v1")


def test_snapshot_rejects_future_unavailable_or_unlisted_embedded_sources() -> None:
    source_id = uuid4()
    future = EventData(
        event_id="event-1",
        event_type="economic-release",
        event_time=T0,
        availability_time=T4,
        source_record_id=source_id,
    )
    with pytest.raises(MarketDataContractError, match="unavailable"):
        snapshot(source_record_ids=(source_id,), event_data=(future,))

    available = EventData(
        event_id="event-2",
        event_type="economic-release",
        event_time=T0,
        availability_time=T2,
        source_record_id=source_id,
    )
    with pytest.raises(MarketDataContractError, match="source_record_ids"):
        snapshot(event_data=(available,))


def test_snapshot_rejects_duplicate_references_and_embedded_values() -> None:
    duplicate = uuid4()
    with pytest.raises(MarketDataContractError, match="duplicates"):
        snapshot(market_data_ids=(duplicate, duplicate))

    first = FundamentalData(T0, T2, duplicate, (metric("supply"),))
    with pytest.raises(MarketDataContractError, match="fundamental_data"):
        snapshot(
            source_record_ids=(duplicate,),
            fundamental_data=(first, first),
        )


@pytest.mark.parametrize("status", list(DataQualityStatus))
def test_all_canonical_quality_states_are_accepted(status: DataQualityStatus) -> None:
    assert quality_report(status=status).status is status


def test_arbitrary_quality_state_is_rejected() -> None:
    with pytest.raises(MarketDataContractError, match="DataQualityStatus"):
        quality_report(status="UNKNOWN")


@pytest.mark.parametrize(
    "value", [Decimal("-0.01"), Decimal("1.01"), Decimal("NaN"), 1, True]
)
def test_quality_dimensions_fail_closed_outside_decimal_unit_interval(
    value: object,
) -> None:
    with pytest.raises(MarketDataContractError):
        quality_report(completeness=value)


def test_quality_evidence_collections_are_tuples_and_unique() -> None:
    with pytest.raises(MarketDataContractError, match="tuple"):
        quality_report(missing_fields=["close"])
    with pytest.raises(MarketDataContractError, match="duplicates"):
        quality_report(source_conflicts=("provider-a", "provider-a"))
    with pytest.raises(MarketDataContractError, match="VALID"):
        quality_report(missing_fields=("close",))


def test_feature_set_enforces_lineage_chronology_and_unique_features() -> None:
    feature = FeatureValue(
        "return-1h", "one_hour_return", Decimal("0.1"), "ratio", "v1"
    )
    with pytest.raises(MarketDataContractError, match="as_of"):
        feature_set(as_of=T4, calculated_at=T3)
    with pytest.raises(MarketDataContractError, match="feature IDs"):
        feature_set(features=(feature, feature))
    duplicate_source = uuid4()
    with pytest.raises(MarketDataContractError, match="duplicates"):
        feature_set(source_record_ids=(duplicate_source, duplicate_source))


@pytest.mark.parametrize(
    "factory",
    [
        lambda: market_data(metrics=[metric()]),
        lambda: dataset_version(source_record_ids=[uuid4()]),
        lambda: snapshot(market_data_ids=[uuid4()]),
        lambda: feature_set(
            features=[FeatureValue("f", "f", Decimal("1"), "ratio", "v1")]
        ),
    ],
)
def test_mutable_list_collections_are_rejected(factory: object) -> None:
    with pytest.raises(MarketDataContractError, match="tuple"):
        factory()  # type: ignore[operator]


def test_contracts_expose_no_runtime_or_trading_methods() -> None:
    prohibited = {
        "connect",
        "fetch",
        "ingest",
        "persist",
        "publish",
        "calculate",
        "analyze",
        "signal",
        "approve",
        "submit_order",
        "execute",
    }
    for contract_type in (
        MarketData,
        MarketSnapshot,
        DataQualityReport,
        FeatureSet,
        DataSourceRecord,
        DatasetVersion,
    ):
        assert prohibited.isdisjoint(set(dir(contract_type)))
