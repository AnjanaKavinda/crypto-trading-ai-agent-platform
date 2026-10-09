"""Local Spot-research read-model metadata and exact lineage resolution."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Any, cast

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    Table,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession

from trading_platform_api.lineage.archive_storage import ImmutableObjectStore
from trading_platform_api.lineage.codec import LineageKey
from trading_platform_api.lineage.store import (
    SqlAlchemyLineageStore,
    append_validated_market_snapshot,
)
from trading_platform_api.lineage.tables import metadata, records
from trading_platform_api.market_data.contracts import (
    DataQualityReport,
    DataQualityStatus,
    DataSourceRecord,
    MarketData,
    MarketSnapshot,
)
from trading_platform_api.market_data.providers import ProviderBatch
from trading_platform_api.market_data.quality import DataQualityPolicy, MetricBound
from trading_platform_api.persistence.session import transactional_session

MAX_READ_CANDLES = 100
SUPPORTED_INSTRUMENTS = frozenset(
    {
        "BTC-USDT-SPOT",
        "ETH-USDT-SPOT",
        "BNB-USDT-SPOT",
        "SOL-USDT-SPOT",
        "XRP-USDT-SPOT",
    }
)
SUPPORTED_TIMEFRAMES = frozenset({"1m", "5m", "15m", "1h", "4h", "1d"})

spot_research_snapshots = Table(
    "spot_research_snapshots",
    metadata,
    Column("snapshot_id", String(36), primary_key=True),
    Column("snapshot_contract_id", String(5), nullable=False),
    Column("snapshot_version", String(512), nullable=False),
    Column("report_id", String(36), nullable=False, unique=True),
    Column("report_contract_id", String(5), nullable=False),
    Column("report_version", String(512), nullable=False),
    Column("instrument_id", String(64), nullable=False),
    Column("venue_id", String(64), nullable=False),
    Column("timeframe", String(8), nullable=False),
    Column("as_of", DateTime(timezone=True), nullable=False),
    Column("candle_count", Integer, nullable=False),
    Column("adapter_version", String(128), nullable=False),
    Column("provider_batch_status", String(16), nullable=False),
    Column("warning_count", Integer, nullable=False),
    Column("policy_version", String(128), nullable=False),
    Column("policy_sha256", String(64), nullable=False),
    Column("policy_document", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "instrument_id IN "
        "('BTC-USDT-SPOT','ETH-USDT-SPOT','BNB-USDT-SPOT',"
        "'SOL-USDT-SPOT','XRP-USDT-SPOT')",
        name="ck_spot_research_instrument",
    ),
    CheckConstraint(
        "venue_id = 'BINANCE-SPOT'",
        name="ck_spot_research_venue",
    ),
    CheckConstraint(
        "timeframe IN ('1m','5m','15m','1h','4h','1d')",
        name="ck_spot_research_timeframe",
    ),
    CheckConstraint(
        f"candle_count >= 2 AND candle_count <= {MAX_READ_CANDLES}",
        name="ck_spot_research_candle_count",
    ),
    CheckConstraint(
        "adapter_version = 'binance-spot-adapter-v1'",
        name="ck_spot_research_adapter",
    ),
    CheckConstraint(
        "snapshot_contract_id = 'C-002' AND snapshot_version = '1' "
        "AND report_contract_id = 'C-003' AND report_version = '1'",
        name="ck_spot_research_contract_versions",
    ),
    CheckConstraint(
        "provider_batch_status = 'COMPLETE' AND warning_count = 0",
        name="ck_spot_research_complete_batch",
    ),
    CheckConstraint(
        "length(btrim(policy_version)) > 0 AND policy_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_spot_research_policy_identity",
    ),
    ForeignKeyConstraint(
        ["snapshot_contract_id", "snapshot_id", "snapshot_version"],
        [records.c.contract_id, records.c.record_id, records.c.version],
        name="fk_spot_research_snapshot_lineage",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["report_contract_id", "report_id", "report_version"],
        [records.c.contract_id, records.c.record_id, records.c.version],
        name="fk_spot_research_report_lineage",
        ondelete="RESTRICT",
    ),
)

_TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


class SpotResearchStoreError(RuntimeError):
    """Sanitized local read-model or lineage failure."""


class SpotResearchSnapshotNotFound(SpotResearchStoreError):
    """No matching persisted Spot snapshot is available."""


@dataclass(frozen=True, slots=True)
class StoredSpotSnapshot:
    snapshot: MarketSnapshot
    quality: DataQualityReport
    observations: tuple[MarketData, ...]
    sources: tuple[DataSourceRecord, ...]
    policy: DataQualityPolicy
    policy_sha256: str
    timeframe: str
    adapter_version: str


def policy_document(policy: DataQualityPolicy) -> dict[str, Any]:
    return {
        "policy_version": policy.policy_version,
        "data_kind": policy.data_kind.value,
        "instrument_id": policy.instrument_id,
        "venue_id": policy.venue_id,
        "required_data_cutoff": policy.required_data_cutoff.isoformat(),
        "coverage_start": policy.coverage_start.isoformat(),
        "coverage_end": policy.coverage_end.isoformat(),
        "interval_seconds": policy.interval_seconds,
        "freshness_seconds": policy.freshness_seconds,
        "maximum_missing_intervals": policy.maximum_missing_intervals,
        "required_metrics": list(policy.required_metrics),
        "metric_bounds": [
            {
                "name": bound.name,
                "minimum": str(bound.minimum),
                "maximum": str(bound.maximum),
            }
            for bound in policy.metric_bounds
        ],
        "require_independent_comparison": policy.require_independent_comparison,
    }


def policy_digest(document: dict[str, Any]) -> str:
    encoded = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def decode_policy(document: object) -> DataQualityPolicy:
    try:
        if type(document) is not dict or set(document) != {
            "policy_version",
            "data_kind",
            "instrument_id",
            "venue_id",
            "required_data_cutoff",
            "coverage_start",
            "coverage_end",
            "interval_seconds",
            "freshness_seconds",
            "maximum_missing_intervals",
            "required_metrics",
            "metric_bounds",
            "require_independent_comparison",
        }:
            raise ValueError
        from trading_platform_api.market_data.providers import ProviderDataKind

        bounds = document["metric_bounds"]
        if type(bounds) is not list:
            raise ValueError
        return DataQualityPolicy(
            policy_version=document["policy_version"],
            data_kind=ProviderDataKind(document["data_kind"]),
            instrument_id=document["instrument_id"],
            venue_id=document["venue_id"],
            required_data_cutoff=datetime.fromisoformat(
                document["required_data_cutoff"]
            ),
            coverage_start=datetime.fromisoformat(document["coverage_start"]),
            coverage_end=datetime.fromisoformat(document["coverage_end"]),
            interval_seconds=document["interval_seconds"],
            freshness_seconds=document["freshness_seconds"],
            maximum_missing_intervals=document["maximum_missing_intervals"],
            required_metrics=tuple(document["required_metrics"]),
            metric_bounds=tuple(
                MetricBound(
                    name=item["name"],
                    minimum=Decimal(item["minimum"]),
                    maximum=Decimal(item["maximum"]),
                )
                for item in bounds
                if type(item) is dict and set(item) == {"name", "minimum", "maximum"}
            ),
            require_independent_comparison=document["require_independent_comparison"],
        )
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        raise SpotResearchStoreError(
            "Persisted OHLCV quality-policy metadata is invalid."
        ) from exc


class SqlAlchemySpotResearchStore:
    """Persist and resolve accepted snapshots using caller-owned sessions."""

    def __init__(
        self,
        session_factory,
        *,
        archive_store: ImmutableObjectStore | None = None,
    ):
        self._session_factory = session_factory
        self._archive_store = archive_store

    async def persist(
        self,
        *,
        batch: ProviderBatch,
        quality: DataQualityReport,
        policy: DataQualityPolicy,
        timeframe: str,
    ) -> None:
        if (
            type(batch) is not ProviderBatch
            or type(quality) is not DataQualityReport
            or quality.status is not DataQualityStatus.VALID
            or len(batch.snapshots) != 1
            or not batch.market_data
            or not batch.source_records
            or batch.provider_id != "binance-spot-public"
            or batch.provider_version != "spot-api-2026-09"
            or batch.data_kind.value != "OHLCV"
            or len(batch.market_data) > MAX_READ_CANDLES
            or timeframe not in SUPPORTED_TIMEFRAMES
            or policy.interval_seconds != _TIMEFRAME_SECONDS[timeframe]
            or policy.instrument_id != batch.snapshots[0].instrument_id
            or policy.venue_id != batch.snapshots[0].venue_id
            or policy.required_data_cutoff != batch.snapshots[0].as_of
            or batch.status.value != "COMPLETE"
            or batch.warnings
            or any(
                source.adapter_version != "binance-spot-adapter-v1"
                or source.provider_id != batch.provider_id
                or source.provider_version != batch.provider_version
                for source in batch.source_records
            )
        ):
            raise SpotResearchStoreError("Snapshot failed persistence eligibility.")

        policy_data = policy_document(policy)
        digest = policy_digest(policy_data)
        snapshot = batch.snapshots[0]
        async with transactional_session(self._session_factory) as session:
            if not isinstance(session, AsyncSession):
                raise SpotResearchStoreError("A PostgreSQL async session is required.")
            lineage = SqlAlchemyLineageStore(session, archive_store=self._archive_store)
            await append_validated_market_snapshot(
                lineage,
                sources=batch.source_records,
                observations=batch.market_data,
                snapshot=snapshot,
                quality=quality,
            )
            await session.execute(
                insert(spot_research_snapshots).values(
                    snapshot_id=str(snapshot.snapshot_id),
                    snapshot_contract_id="C-002",
                    snapshot_version="1",
                    report_id=str(quality.report_id),
                    report_contract_id="C-003",
                    report_version="1",
                    instrument_id=snapshot.instrument_id,
                    venue_id=snapshot.venue_id,
                    timeframe=timeframe,
                    as_of=snapshot.as_of,
                    candle_count=len(batch.market_data),
                    adapter_version="binance-spot-adapter-v1",
                    provider_batch_status=batch.status.value,
                    warning_count=len(batch.warnings),
                    policy_version=policy.policy_version,
                    policy_sha256=digest,
                    policy_document=policy_data,
                    created_at=datetime.now(UTC),
                )
            )

    async def read_latest(
        self,
        *,
        instrument_id: str,
        timeframe: str,
        as_of: datetime | None,
        maximum_candles: int,
    ) -> StoredSpotSnapshot:
        if (
            instrument_id not in SUPPORTED_INSTRUMENTS
            or timeframe not in SUPPORTED_TIMEFRAMES
            or type(maximum_candles) is not int
            or not 2 <= maximum_candles <= MAX_READ_CANDLES
            or (
                as_of is not None
                and (as_of.tzinfo is None or as_of.utcoffset() is None)
            )
        ):
            raise SpotResearchStoreError("Invalid bounded Spot research selector.")

        async with transactional_session(self._session_factory) as session:
            if not isinstance(session, AsyncSession):
                raise SpotResearchStoreError("A PostgreSQL async session is required.")
            query = (
                select(spot_research_snapshots)
                .where(
                    spot_research_snapshots.c.instrument_id == instrument_id,
                    spot_research_snapshots.c.timeframe == timeframe,
                )
                .order_by(
                    spot_research_snapshots.c.as_of.desc(),
                    spot_research_snapshots.c.snapshot_id.desc(),
                )
                .limit(1)
            )
            if as_of is not None:
                query = query.where(spot_research_snapshots.c.as_of <= as_of)
            row = (await session.execute(query)).mappings().one_or_none()
            if row is None:
                raise SpotResearchSnapshotNotFound(
                    "No matching accepted Spot snapshot is available."
                )
            count = row["candle_count"]
            if type(count) is not int or count > maximum_candles:
                raise SpotResearchStoreError(
                    "The selected snapshot exceeds the requested candle limit."
                )
            policy = decode_policy(row["policy_document"])
            document = policy_document(policy)
            digest = policy_digest(document)
            if (
                digest != row["policy_sha256"]
                or policy.policy_version != row["policy_version"]
                or policy.interval_seconds != _TIMEFRAME_SECONDS[timeframe]
                or policy.instrument_id != instrument_id
                or policy.venue_id != row["venue_id"]
                or row["adapter_version"] != "binance-spot-adapter-v1"
                or row["provider_batch_status"] != "COMPLETE"
                or row["warning_count"] != 0
            ):
                raise SpotResearchStoreError(
                    "Persisted Spot snapshot metadata failed verification."
                )
            lineage = SqlAlchemyLineageStore(session, archive_store=self._archive_store)
            keys = (
                LineageKey("C-002", row["snapshot_id"]),
                LineageKey("C-003", row["report_id"]),
            )
            resolved = await lineage.resolve(
                keys, maximum_records=2 * maximum_candles + 2
            )
            snapshot = resolved[keys[0]]
            quality = resolved[keys[1]]
            if (
                type(snapshot) is not MarketSnapshot
                or type(quality) is not DataQualityReport
                or quality.status is not DataQualityStatus.VALID
                or snapshot.instrument_id != instrument_id
                or snapshot.venue_id != row["venue_id"]
                or snapshot.as_of != row["as_of"]
                or quality.snapshot_id != snapshot.snapshot_id
                or quality.required_data_cutoff != snapshot.as_of
                or len(snapshot.market_data_ids) != count
            ):
                raise SpotResearchStoreError(
                    "Persisted Spot snapshot lineage does not match its read model."
                )
            raw_observations = tuple(
                resolved[LineageKey("C-001", str(item_id))]
                for item_id in snapshot.market_data_ids
            )
            raw_sources = tuple(
                resolved[LineageKey("C-091", str(source_id))]
                for source_id in snapshot.source_record_ids
            )
            if not all(
                type(item) is MarketData for item in raw_observations
            ) or not all(type(item) is DataSourceRecord for item in raw_sources):
                raise SpotResearchStoreError(
                    "Persisted Spot snapshot contains unsupported lineage records."
                )
            observations = cast(tuple[MarketData, ...], raw_observations)
            sources = cast(tuple[DataSourceRecord, ...], raw_sources)
            return StoredSpotSnapshot(
                snapshot=snapshot,
                quality=quality,
                observations=observations,
                sources=sources,
                policy=policy,
                policy_sha256=digest,
                timeframe=timeframe,
                adapter_version=row["adapter_version"],
            )
