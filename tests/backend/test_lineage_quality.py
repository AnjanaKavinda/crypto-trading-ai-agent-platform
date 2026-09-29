from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from test_moving_averages import evidence
from trading_platform_api.lineage.codec import (
    LineageError,
    LineageKey,
    decode,
    encode,
    key_for,
)
from trading_platform_api.lineage.store import (
    SqlAlchemyLineageStore,
    append_validated_market_snapshot,
    references,
)
from trading_platform_api.market_data.contracts import (
    DataQualityStatus,
    DataSourceRecord,
)


class MemoryLineageStore(SqlAlchemyLineageStore):
    def __init__(self) -> None:
        self.appended: list[object] = []

    async def append(self, record: object) -> LineageKey:
        self.appended.append(record)
        return key_for(record)


def records_for_report(status: DataQualityStatus = DataQualityStatus.VALID):
    snapshot, observations, quality = evidence()
    first = observations[0]
    source = DataSourceRecord(
        source_record_id=first.source_record_id,
        provider_id="fixture-provider",
        provider_version="v1",
        provider_event_time=first.event_time,
        retrieval_time=first.ingestion_time,
        availability_time=observations[-1].availability_time,
        raw_schema_version="fixture-v1",
        adapter_version="fixture-adapter-v1",
        licensing_reference="fixture-test-data",
        content_sha256="a" * 64,
    )
    report = replace(quality, status=status)
    return (source,), observations, snapshot, report


def test_quality_report_roundtrips_as_closed_c003_and_links_snapshot() -> None:
    sources, observations, snapshot, report = records_for_report()
    assert decode(encode(report)) == report
    assert key_for(report) == LineageKey("C-003", str(report.report_id))
    assert tuple(item.key for item in references(report)) == (
        LineageKey("C-002", str(snapshot.snapshot_id)),
    )
    assert sources and observations


def test_valid_snapshot_persistence_orders_source_data_snapshot_quality() -> None:
    async def check() -> None:
        sources, observations, snapshot, report = records_for_report()
        store = MemoryLineageStore()
        keys = await append_validated_market_snapshot(
            store,
            sources=sources,
            observations=observations,
            snapshot=snapshot,
            quality=report,
        )
        assert tuple(keys) == tuple(key_for(record) for record in store.appended)
        assert store.appended == [*sources, *observations, snapshot, report]

    import asyncio

    asyncio.run(check())


@pytest.mark.parametrize(
    "change",
    [
        {"status": DataQualityStatus.DEGRADED},
        {"snapshot_id": uuid4()},
        {"required_data_cutoff": evidence()[0].as_of - timedelta(minutes=1)},
    ],
)
def test_invalid_quality_or_snapshot_is_rejected_before_any_append(change) -> None:
    async def check() -> None:
        sources, observations, snapshot, report = records_for_report()
        store = MemoryLineageStore()
        with pytest.raises(LineageError, match="VALID quality"):
            await append_validated_market_snapshot(
                store,
                sources=sources,
                observations=observations,
                snapshot=snapshot,
                quality=replace(report, **change),
            )
        assert store.appended == []

    import asyncio

    asyncio.run(check())


def test_unknown_quality_enum_value_fails_closed() -> None:
    document = encode(records_for_report()[3])
    import json

    decoded = json.loads(document)
    decoded["payload"]["status"] = "FUTURE_STATUS"
    with pytest.raises(LineageError, match="corrupt"):
        decode(json.dumps(decoded))
