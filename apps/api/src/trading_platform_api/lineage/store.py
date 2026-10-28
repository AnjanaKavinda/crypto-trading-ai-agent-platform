"""Append-only PostgreSQL store with caller-owned transaction boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from trading_platform_api.analysis.contracts import MarketRegime
from trading_platform_api.analysis.spot_meta_analysis import AgentIndependenceReport
from trading_platform_api.analysis.versioned_contracts import EvidenceItemV2
from trading_platform_api.analysis.versioned_contracts_v4 import AnalysisSnapshotV4
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.lineage.archive_storage import ImmutableObjectStore
from trading_platform_api.lineage.codec import (
    LineageError,
    LineageKey,
    decode,
    encode,
    key_for,
)
from trading_platform_api.lineage.policy import is_personal_spot_ohlcv
from trading_platform_api.lineage.tables import (
    links,
    market_payloads,
    payload_events,
    records,
)
from trading_platform_api.market_data.contracts import (
    DataQualityReport,
    DataQualityReportV2,
    DataQualityStatus,
    DatasetVersion,
    DataSourceRecord,
    MarketData,
    MarketSnapshot,
)
from trading_platform_api.market_data.history_contracts import (
    HistoricalUniverse,
    ObservationRevision,
    ReconstructionManifest,
)


@dataclass(frozen=True, slots=True)
class Reference:
    key: LineageKey
    evidence_sha256: str | None = None
    lineage_sha256: str | None = None


def references(record: object) -> tuple[Reference, ...]:
    result: list[Reference] = []
    if type(record) is DataQualityReport:
        result.append(Reference(LineageKey("C-002", str(record.snapshot_id))))
    elif type(record) is DataQualityReportV2:
        result.append(Reference(LineageKey("C-002", str(record.snapshot_id))))
        result.extend(
            Reference(
                LineageKey(
                    item.evidence_reference.contract_id,
                    item.evidence_reference.record_id,
                    item.evidence_reference.version,
                ),
                item.evidence_reference.evidence_sha256,
            )
            for item in record.dimensions
            if item.evidence_reference is not None
        )
    if type(record) is MarketRegime:
        result.extend(
            Reference(LineageKey("C-008", str(item), "2"))
            for item in record.evidence_ids
        )
    if type(record) is EvidenceItemV2:
        result.extend(
            Reference(LineageKey("C-001", str(item))) for item in record.observation_ids
        )
        result.extend(
            Reference(LineageKey("C-091", str(item)))
            for item in record.source_record_ids
        )
    if type(record) is AnalysisSnapshotV4:
        for binding in record.bindings:
            result.append(
                Reference(
                    LineageKey(
                        binding.market_snapshot.contract_id,
                        binding.market_snapshot.record_id,
                        binding.market_snapshot.lineage_version,
                    ),
                    binding.market_snapshot.content_sha256,
                )
            )
            result.append(
                Reference(
                    LineageKey(
                        binding.data_quality_report.contract_id,
                        binding.data_quality_report.record_id,
                        binding.data_quality_report.lineage_version,
                    ),
                    binding.data_quality_report.content_sha256,
                )
            )
            for observation_source in binding.observations:
                for reference in (
                    observation_source.observation,
                    observation_source.source,
                ):
                    result.append(
                        Reference(
                            LineageKey(
                                reference.contract_id,
                                reference.record_id,
                                reference.lineage_version,
                            ),
                            reference.content_sha256,
                        )
                    )
            for source in binding.source_records:
                result.append(
                    Reference(
                        LineageKey(
                            source.contract_id,
                            source.record_id,
                            source.lineage_version,
                        ),
                        source.content_sha256,
                    )
                )
            result.append(
                Reference(
                    LineageKey(
                        binding.regime.contract_id,
                        str(binding.regime.record_id),
                        binding.regime.lineage_version,
                    ),
                    binding.regime.content_sha256,
                )
            )
            result.extend(
                Reference(
                    LineageKey(
                        item.contract_id, str(item.record_id), item.lineage_version
                    ),
                    item.content_sha256,
                )
                for item in binding.evidence
            )
    if type(record) is AgentIndependenceReport:
        result.extend(
            (
                Reference(
                    LineageKey(
                        "C-002",
                        str(record.snapshot_id),
                        record.snapshot_lineage_version,
                    ),
                    record.snapshot_sha256,
                ),
                Reference(
                    LineageKey(
                        "C-007",
                        str(record.manifest_id),
                        record.manifest_lineage_version,
                    ),
                ),
                Reference(
                    LineageKey("C-005", str(record.regime_id), "1"),
                    record.regime_sha256,
                ),
                Reference(
                    LineageKey(
                        "C-003",
                        str(record.quality_report_id),
                        record.quality_report_lineage_version,
                    ),
                    record.quality_report_sha256,
                ),
            )
        )
    if type(record) is MarketData:
        result.append(Reference(LineageKey("C-091", str(record.source_record_id))))
    if isinstance(record, (MarketSnapshot, DatasetVersion, HistoricalUniverse)):
        result.extend(
            Reference(LineageKey("C-091", str(item)))
            for item in record.source_record_ids
        )
    if type(record) is MarketSnapshot:
        result.extend(
            Reference(LineageKey("C-001", str(item))) for item in record.market_data_ids
        )
        if record.dataset_version is not None:
            result.append(
                Reference(
                    LineageKey(
                        "C-092",
                        record.dataset_version.dataset_id,
                        record.dataset_version.version,
                    )
                )
            )
    if type(record) is ObservationRevision:
        result.append(
            Reference(key_for(record.observation), canonical_sha256(record.observation))
        )
        if record.supersedes_revision_id is not None:
            result.append(
                Reference(LineageKey("C-102", str(record.supersedes_revision_id)))
            )
    if type(record) is ReconstructionManifest:
        result.extend(
            Reference(LineageKey("C-102", str(pin.evidence_id)), pin.content_sha256)
            for pin in record.revision_pins
        )
        result.extend(
            Reference(LineageKey("C-091", str(pin.evidence_id)), pin.content_sha256)
            for pin in record.source_pins
        )
        result.append(
            Reference(
                LineageKey("C-101", record.universe_id, record.universe_version),
                record.universe_sha256,
            )
        )
        result.append(
            Reference(
                LineageKey(
                    "C-092",
                    record.dataset_version.dataset_id,
                    record.dataset_version.version,
                ),
                lineage_sha256=record.dataset_lineage_sha256,
            )
        )
    if len(result) > 2000:
        raise LineageError("Lineage references exceed the bounded read budget.")
    return tuple(result)


async def append_validated_market_snapshot(
    store: SqlAlchemyLineageStore,
    *,
    sources: tuple[DataSourceRecord, ...],
    observations: tuple[MarketData, ...],
    snapshot: MarketSnapshot,
    quality: DataQualityReport,
) -> tuple[LineageKey, ...]:
    """Append a bounded VALID market snapshot and its exact quality report.

    The caller owns the transaction. A VALID verdict, exact ordered snapshot
    membership and exact source membership are required before any writes.
    The quality assessor remains the authority for producing the report.
    """
    if (
        not isinstance(store, SqlAlchemyLineageStore)
        or type(sources) is not tuple
        or not sources
        or len(sources) > 501
        or not all(type(item) is DataSourceRecord for item in sources)
        or type(observations) is not tuple
        or not observations
        or len(observations) > 501
        or not all(type(item) is MarketData for item in observations)
        or type(snapshot) is not MarketSnapshot
        or type(quality) is not DataQualityReport
    ):
        raise LineageError("Invalid bounded validated-market snapshot input.")
    source_ids = tuple(item.source_record_id for item in sources)
    if (
        quality.status is not DataQualityStatus.VALID
        or quality.snapshot_id != snapshot.snapshot_id
        or quality.required_data_cutoff != snapshot.as_of
        or tuple(item.market_data_id for item in observations)
        != snapshot.market_data_ids
        or source_ids != snapshot.source_record_ids
        or not {item.source_record_id for item in observations}.issubset(
            set(source_ids)
        )
        or any(
            item.instrument_id != snapshot.instrument_id
            or item.venue_id != snapshot.venue_id
            for item in observations
        )
    ):
        raise LineageError(
            "Only an exact matching VALID quality snapshot can be persisted."
        )
    records_to_append = (*sources, *observations, snapshot, quality)
    # This helper already owns one caller-managed transaction for an entirely
    # validated batch. Avoid a savepoint per record: a 501-candle snapshot can
    # contain more than one thousand lineage records, and the extra SAVEPOINT /
    # RELEASE round trips can consume the bounded persistence deadline without
    # adding isolation beyond the enclosing all-or-nothing transaction.
    return tuple(
        [
            await store._append(record, use_savepoint=False)
            for record in records_to_append
        ]
    )


def _identity(key: LineageKey) -> dict[str, str]:
    return dict(
        contract_id=key.contract_id, record_id=key.record_id, version=key.version
    )


def _where(key: LineageKey, table=records):
    return and_(*(table.c[name] == value for name, value in _identity(key).items()))


class SqlAlchemyLineageStore:
    _PERSONAL_SPOT_ANALYSIS_TYPES = (
        DataQualityReportV2,
        MarketRegime,
        AnalysisSnapshotV4,
        EvidenceItemV2,
        AgentIndependenceReport,
    )

    def __init__(
        self,
        session: AsyncSession,
        *,
        archive_store: ImmutableObjectStore | None = None,
    ):
        self._session = session
        self._archive_store = archive_store

    async def get(self, key: LineageKey) -> object:
        row = (
            (await self._session.execute(select(records).where(_where(key))))
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise LineageError("Exact lineage record is missing.")
        document = row["document"]
        if document is None and key.contract_id == "C-001":
            payload = (
                (
                    await self._session.execute(
                        select(market_payloads).where(_where(key, market_payloads))
                    )
                )
                .mappings()
                .one_or_none()
            )
            if payload is not None:
                document = payload["document"]
                if (
                    payload["document_sha256"] != row["document_sha256"]
                    or payload["evidence_sha256"] != row["evidence_sha256"]
                ):
                    raise LineageError("Hot payload differs from its lineage anchor.")
            elif self._archive_store is not None:
                from trading_platform_api.lineage.archival import (
                    read_archived_market_document,
                )

                document = await read_archived_market_document(
                    self._session,
                    key,
                    self._archive_store,
                    document_sha256=row["document_sha256"],
                    evidence_sha256=row["evidence_sha256"],
                )
            else:
                raise LineageError(
                    "Market payload is not available in configured storage."
                )
        if document is None:
            raise LineageError("Lineage payload is missing.")
        if sha256(document.encode("utf-8")).hexdigest() != row["document_sha256"]:
            raise LineageError("Stored document digest mismatch.")
        record = decode(document)
        if key_for(record) != key or canonical_sha256(record) != row["evidence_sha256"]:
            raise LineageError("Stored identity or evidence digest mismatch.")
        actual = (
            (
                await self._session.execute(
                    select(links).where(_where(key, links)).limit(2001)
                )
            )
            .mappings()
            .all()
        )
        if len(actual) > 2000:
            raise LineageError("Stored lineage edges exceed the read budget.")
        actual_keys = {
            LineageKey(
                row["target_contract_id"],
                row["target_record_id"],
                row["target_version"],
            )
            for row in actual
        }
        if actual_keys != {reference.key for reference in references(record)}:
            raise LineageError("Stored lineage edges do not match the record.")
        return record

    async def _check_references(
        self, record: object, resolved: dict[LineageKey, object] | None = None
    ) -> tuple[Reference, ...]:
        refs = references(record)
        for ref in refs:
            target = await self.get(ref.key) if resolved is None else resolved[ref.key]
            if (
                ref.evidence_sha256 is not None
                and canonical_sha256(target) != ref.evidence_sha256
            ):
                raise LineageError("Referenced immutable content differs.")
            if ref.lineage_sha256 is not None and (
                type(target) is not DatasetVersion
                or target.lineage_sha256 != ref.lineage_sha256
            ):
                raise LineageError("Referenced dataset lineage differs.")
            if (
                type(record) is ObservationRevision
                and type(target) is ObservationRevision
            ):
                child, parent = record.observation, target.observation
                if (
                    (
                        record.provider_id,
                        record.observation_key,
                        child.instrument_id,
                        child.venue_id,
                        child.observation_type,
                        child.event_time,
                    )
                    != (
                        target.provider_id,
                        target.observation_key,
                        parent.instrument_id,
                        parent.venue_id,
                        parent.observation_type,
                        parent.event_time,
                    )
                    or target.availability_time > record.availability_time
                    or target.publication_time > record.publication_time
                    or target.ingestion_time > record.ingestion_time
                ):
                    raise LineageError("Incompatible revision ancestry.")
            if type(record) is AgentIndependenceReport:
                manifest_key = LineageKey(
                    "C-007", str(record.manifest_id), record.manifest_lineage_version
                )
                manifest = (
                    await self.get(manifest_key)
                    if resolved is None
                    else resolved[manifest_key]
                )
                if type(manifest) is not AnalysisSnapshotV4 or not any(
                    binding.binding_id == record.binding_id
                    and canonical_sha256(binding) == record.binding_sha256
                    for binding in manifest.bindings
                ):
                    raise LineageError("C-093 binding reference differs from C-007.")
        return refs

    async def append(self, record: object) -> LineageKey:
        """Insert or verify an identical retry; never commit the caller's session."""
        if type(record) in self._PERSONAL_SPOT_ANALYSIS_TYPES:
            raise LineageError(
                "Analysis lineage writes require the bounded Spot persistence path."
            )
        return await self._append(record)

    async def append_personal_spot_analysis_record(self, record: object) -> LineageKey:
        """Append one record for the explicitly approved personal Spot closure."""
        if type(record) not in self._PERSONAL_SPOT_ANALYSIS_TYPES:
            raise LineageError("Record is outside the bounded Spot analysis closure.")
        return await self._append(record)

    async def _append(
        self, record: object, *, use_savepoint: bool = True
    ) -> LineageKey:
        """Shared immutable insert implementation behind the bounded entry points."""
        key = key_for(record)
        document = encode(record)
        refs = await self._check_references(record)
        if use_savepoint:
            async with self._session.begin_nested():
                await self._insert(key, record, document, refs)
        else:
            await self._insert(key, record, document, refs)
        return key

    async def _insert(
        self,
        key: LineageKey,
        record: object,
        document: str,
        refs: tuple[Reference, ...],
    ) -> None:
        """Insert one prevalidated record within the caller's transaction."""
        document_sha256 = sha256(document.encode("utf-8")).hexdigest()
        evidence_sha256 = canonical_sha256(record)
        is_market_payload = is_personal_spot_ohlcv(record)
        statement = (
            insert(records)
            .values(
                **_identity(key),
                document=None if is_market_payload else document,
                document_sha256=document_sha256,
                evidence_sha256=evidence_sha256,
            )
            .on_conflict_do_nothing()
            .returning(records.c.record_id)
        )
        inserted = (await self._session.execute(statement)).scalar_one_or_none()
        if inserted is None:
            if encode(await self.get(key)) != document:
                raise LineageError("Immutable identity already has different content.")
            return
        if is_market_payload:
            await self._session.execute(
                insert(market_payloads).values(
                    **_identity(key),
                    document=document,
                    document_sha256=document_sha256,
                    evidence_sha256=evidence_sha256,
                )
            )
            event_material = "|".join(
                (
                    key.contract_id,
                    key.record_id,
                    key.version,
                    "HOT_WRITTEN",
                    document_sha256,
                )
            )
            await self._session.execute(
                insert(payload_events).values(
                    event_id=sha256(event_material.encode("utf-8")).hexdigest(),
                    **_identity(key),
                    event_type="HOT_WRITTEN",
                    object_key=None,
                    payload_sha256=document_sha256,
                    occurred_at=datetime.now(UTC),
                )
            )
        unique = {ref.key for ref in refs}
        if unique:
            await self._session.execute(
                insert(links),
                [
                    dict(
                        **_identity(key),
                        target_contract_id=target.contract_id,
                        target_record_id=target.record_id,
                        target_version=target.version,
                    )
                    for target in unique
                ],
            )

    async def resolve(
        self, keys: tuple[LineageKey, ...], *, maximum_records: int = 2000
    ) -> dict[LineageKey, object]:
        """Resolve an exact bounded dependency graph and revalidate reference hashes."""
        if type(keys) is not tuple or not all(type(key) is LineageKey for key in keys):
            raise LineageError("Exact immutable keys are required.")
        if (
            type(maximum_records) is not int
            or not 1 <= maximum_records <= 2000
            or len(keys) > maximum_records
        ):
            raise LineageError("Invalid resolution budget.")
        pending = list(keys)
        result: dict[LineageKey, object] = {}
        while pending:
            key = pending.pop()
            if key in result:
                continue
            if len(result) >= maximum_records:
                raise LineageError("Lineage resolution budget exceeded.")
            record = await self.get(key)
            refs = references(record)
            result[key] = record
            pending.extend(ref.key for ref in refs if ref.key not in result)
        for record in result.values():
            await self._check_references(record, resolved=result)
        return result
