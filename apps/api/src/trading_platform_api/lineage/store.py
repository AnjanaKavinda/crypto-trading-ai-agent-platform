"""Append-only PostgreSQL store with caller-owned transaction boundaries."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from trading_platform_api.agents.contracts import (
    AgentEvaluation,
    AgentResult,
    ModelRoutingDecision,
)
from trading_platform_api.analysis.contracts import (
    AnalyticalUncertainty,
    MarketRegime,
    TechnicalAssessment,
)
from trading_platform_api.analysis.spot_meta_analysis import AgentIndependenceReport
from trading_platform_api.analysis.versioned_contracts import (
    AnalysisRecordReference,
    EvidenceItemV2,
)
from trading_platform_api.analysis.versioned_contracts_v4 import (
    AnalysisOutputReferenceV4,
    AnalysisSnapshotReferenceV4,
    AnalysisSnapshotV4,
    ConflictAssessmentV3,
    ConfluenceAssessmentV3,
)
from trading_platform_api.analysis.versioned_contracts_v5 import (
    AdversarialAssessmentV2,
    MarketContextV5,
)
from trading_platform_api.contracts.serialization import (
    canonical_sha256,
)
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
    spot_agent_handoff_bindings,
    strategy_evaluate_bindings,
    strategy_registry_links,
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
from trading_platform_api.strategy.contracts import (
    SignalCandidate,
    StrategyEligibility,
    StrategyVersion,
    VersionReference,
)
from trading_platform_api.strategy.contracts_v2 import (
    NoTradeDecisionV2,
    SignalEvidencePackageV2,
    SignalQualificationV2,
    SignalV2,
    StrategyVersionV2,
    _qualification_digest,
)
from trading_platform_api.validation.contracts import OOSResult
from trading_platform_api.validation.contracts_v2 import (
    CostAssumptionSetV2,
    QualificationValidationResultV2,
    ValidationArtifactReferenceV2,
)
from trading_platform_api.validation.contracts_v3 import BacktestResultV3
from trading_platform_api.validation.oos_contracts_v2 import OOSResultV2


@dataclass(frozen=True, slots=True)
class Reference:
    key: LineageKey
    evidence_sha256: str | None = None
    lineage_sha256: str | None = None


def _reference_content_sha256(record: object) -> str:
    if type(record) is AnalysisSnapshotV4:
        return record.content_sha256
    if type(record) is StrategyVersion or type(record) is StrategyVersionV2:
        from trading_platform_api.strategy.registry import (
            strategy_version_content_sha256,
        )

        return strategy_version_content_sha256(record)
    if type(record) is SignalEvidencePackageV2:
        return record.content_sha256
    if type(record) is SignalQualificationV2:
        return _qualification_digest(record)
    if type(record) is CostAssumptionSetV2:
        return record.content_sha256
    if type(record) is QualificationValidationResultV2:
        return record.content_sha256
    return canonical_sha256(record)


def _typed_contract_references(record: object) -> tuple[Reference, ...]:
    """Collect only explicit versioned contract references from strategy payloads."""
    result: dict[LineageKey, Reference] = {}
    pending = [record]
    visited: set[int] = set()
    while pending:
        if len(visited) >= 10_000:
            raise LineageError("Lineage reference traversal exceeded its budget.")
        value = pending.pop()
        if id(value) in visited:
            continue
        visited.add(id(value))
        if isinstance(value, VersionReference):
            if value.artifact_type.startswith("C-"):
                version = "2" if value.artifact_type == "C-021" else value.version
                key = LineageKey(value.artifact_type, str(value.artifact_id), version)
                result[key] = Reference(key, value.content_sha256)
            continue
        if isinstance(value, (AnalysisOutputReferenceV4, AnalysisRecordReference)):
            key = LineageKey(
                value.contract_id, str(value.record_id), value.lineage_version
            )
            result[key] = Reference(key, value.content_sha256)
            if (
                isinstance(value, AnalysisOutputReferenceV4)
                and value.method is not None
            ):
                pending.append(value.method)
            continue
        if isinstance(value, AnalysisSnapshotReferenceV4):
            key = LineageKey("C-007", str(value.snapshot_id), value.schema_version)
            result[key] = Reference(key, value.content_sha256)
            continue
        if isinstance(value, ValidationArtifactReferenceV2):
            if value.artifact_type.startswith("C-"):
                key = LineageKey(
                    value.artifact_type,
                    str(value.artifact_id),
                    "2" if value.artifact_type == "C-027" else value.version,
                )
                result[key] = Reference(key, value.content_sha256)
            continue
        if is_dataclass(value):
            pending.extend(getattr(value, item.name) for item in fields(value))
        elif isinstance(value, (tuple, list)):
            pending.extend(value)
    return tuple(result.values())


def references(record: object) -> tuple[Reference, ...]:
    if type(record) in (OOSResult, OOSResultV2):
        raise LineageError(
            "C-071/C-029 retention is not authorized by the validation "
            "runtime boundary."
        )
    if (
        type(record).__module__
        == "trading_platform_api.validation.walk_forward_contracts_v2"
        and type(record).__name__ == "WalkForwardResultV2"
    ):
        raise LineageError(
            "C-071/C-029 retention is not authorized by the validation "
            "runtime boundary."
        )
    if type(record) is BacktestResultV3:
        raise LineageError(
            "C-027v3 persistence requires a governed simulation trace resolver."
        )
    result: list[Reference] = []
    if type(record) is AgentResult:
        result.append(
            Reference(
                LineageKey("C-067", str(record.routing_decision.request_id), "1"),
                canonical_sha256(record.routing_decision),
            )
        )
        if type(record.output) is MarketContextV5:
            result.append(
                Reference(
                    LineageKey("C-006", str(record.output.context_id), "5"),
                    canonical_sha256(record.output),
                )
            )
    if type(record) is AgentEvaluation:
        result.extend(
            (
                Reference(LineageKey("C-062", str(record.result_id), "1")),
                Reference(
                    LineageKey("C-067", str(record.routing_decision_ref.entity_id), "1")
                ),
            )
        )
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
    if type(record) is MarketContextV5:
        result.append(
            Reference(
                LineageKey("C-005", str(record.regime.regime_id), "1"),
                canonical_sha256(record.regime),
            )
        )
        result.append(
            Reference(
                LineageKey("C-009", str(record.confluence.assessment_id), "3"),
                canonical_sha256(record.confluence),
            )
        )
        result.extend(
            Reference(
                LineageKey("C-010", str(item.assessment_id), "3"),
                canonical_sha256(item),
            )
            for item in record.conflicts
        )
        result.append(
            Reference(
                LineageKey("C-019", str(record.adversarial.assessment_id), "2"),
                canonical_sha256(record.adversarial),
            )
        )
        result.extend(
            Reference(
                LineageKey("C-069", str(item.uncertainty_id), "1"),
                canonical_sha256(item),
            )
            for item in record.uncertainties
        )
        result.extend(
            Reference(
                LineageKey("C-012", str(item.assessment_id), "1"),
                canonical_sha256(item),
            )
            for item in record.assessments
            if type(item) is TechnicalAssessment
        )
        result.extend(
            Reference(LineageKey("C-008", str(item), "2"))
            for item in record.evidence_ids
        )
    if type(record) is StrategyEligibility:
        result.extend(
            (
                Reference(LineageKey("C-021", str(record.strategy_version_id), "2")),
                Reference(LineageKey("C-006", str(record.market_context_id), "5")),
                Reference(LineageKey("C-003", str(record.data_quality_report_id), "2")),
                Reference(LineageKey("C-005", str(record.regime_id), "1")),
            )
        )
    if type(record) is QualificationValidationResultV2:
        result.extend(
            (
                Reference(
                    LineageKey("C-023", str(record.candidate_id), "1"),
                    record.candidate_sha256,
                ),
                Reference(
                    LineageKey("C-024", str(record.evidence_package_id), "2"),
                    record.evidence_package_sha256,
                ),
                Reference(LineageKey("C-021", str(record.strategy_version_id), "2")),
                Reference(
                    LineageKey(
                        "C-027",
                        str(record.cost_assumptions.assumption_set_id),
                        "2",
                    ),
                    record.cost_assumptions.content_sha256,
                ),
            )
        )
    if type(record) is SignalQualificationV2:
        result.append(
            Reference(
                LineageKey("C-028", str(record.validation.result_id), "2"),
                record.validation.content_sha256,
            )
        )
    if type(record) is SignalCandidate:
        result.extend(
            (
                Reference(LineageKey("C-022", str(record.eligibility_id), "1")),
                Reference(LineageKey("C-006", str(record.market_context_id), "5")),
                Reference(LineageKey("C-007", str(record.analysis_snapshot_id), "4")),
                Reference(LineageKey("C-003", str(record.data_quality_report_id), "2")),
            )
        )
        result.extend(
            Reference(LineageKey("C-008", str(item), "2"))
            for item in (
                *record.supporting_evidence_ids,
                *record.contradictory_evidence_ids,
            )
        )
    if type(record) in (
        StrategyVersionV2,
        SignalEvidencePackageV2,
        StrategyEligibility,
        SignalQualificationV2,
        NoTradeDecisionV2,
        QualificationValidationResultV2,
        CostAssumptionSetV2,
        SignalV2,
        MarketContextV5,
        AdversarialAssessmentV2,
        SignalCandidate,
    ):
        result.extend(_typed_contract_references(record))
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


def _occurred_at(record: object) -> datetime | None:
    for attribute in (
        "occurred_at",
        "created_at",
        "evaluated_at",
        "decided_at",
        "as_of",
    ):
        value = getattr(record, attribute, None)
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise LineageError("Artifact occurrence time must be timezone-aware.")
            return value.astimezone(UTC)
    return None


class SqlAlchemyLineageStore:
    _PERSONAL_SPOT_ANALYSIS_TYPES = (
        DataQualityReportV2,
        MarketRegime,
        AnalysisSnapshotV4,
        EvidenceItemV2,
        AgentIndependenceReport,
        ConfluenceAssessmentV3,
        ConflictAssessmentV3,
        TechnicalAssessment,
        AdversarialAssessmentV2,
        AnalyticalUncertainty,
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
            if key.contract_id in {"C-020", "C-021"}:
                from trading_platform_api.strategy.registry_store import (
                    SqlAlchemyStrategyRegistryStore,
                )

                registry = SqlAlchemyStrategyRegistryStore(self._session)
                record_id = UUID(key.record_id)
                record = (
                    await registry.get_strategy(record_id)
                    if key.contract_id == "C-020"
                    else await registry.get_version(record_id)
                )
                if record is None or key_for(record) != key:
                    raise LineageError("Exact strategy registry reference is missing.")
                return record
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
        decoded_record = decode(document)
        if (
            key_for(decoded_record) != key
            or canonical_sha256(decoded_record) != row["evidence_sha256"]
        ):
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
        registry_rows = (
            (
                await self._session.execute(
                    select(strategy_registry_links)
                    .where(_where(key, strategy_registry_links))
                    .limit(2001)
                )
            )
            .mappings()
            .all()
        )
        if len(registry_rows) > 2000:
            raise LineageError("Stored strategy registry edges exceed the read budget.")
        actual_keys.update(
            LineageKey(
                row["target_contract_id"],
                row["target_record_id"],
                row["target_version"],
            )
            for row in registry_rows
        )
        if actual_keys != {reference.key for reference in references(decoded_record)}:
            raise LineageError("Stored lineage edges do not match the record.")
        return decoded_record

    async def _check_references(
        self, record: object, resolved: dict[LineageKey, object] | None = None
    ) -> tuple[Reference, ...]:
        refs = references(record)
        for ref in refs:
            target = await self.get(ref.key) if resolved is None else resolved[ref.key]
            if (
                ref.evidence_sha256 is not None
                and _reference_content_sha256(target) != ref.evidence_sha256
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
        if type(record) in self._PERSONAL_SPOT_ANALYSIS_TYPES or type(record) in (
            AgentResult,
            AgentEvaluation,
            ModelRoutingDecision,
        ):
            raise LineageError(
                "Analysis and agent handoff writes require their bounded Spot persistence paths."
            )
        return await self._append(record)

    async def append_personal_spot_analysis_record(self, record: object) -> LineageKey:
        """Append one record for the explicitly approved personal Spot closure."""
        if type(record) not in self._PERSONAL_SPOT_ANALYSIS_TYPES:
            raise LineageError("Record is outside the bounded Spot analysis closure.")
        return await self._append(record)

    async def get_evaluate_binding(
        self, *, profile: str, request_digest: str, request_document: str
    ) -> str | None:
        if profile != "PERSONAL_SPOT_RESEARCH" or len(request_digest) != 64:
            raise LineageError("Invalid strategy evaluate binding identity.")
        result = await self._session.execute(
            select(strategy_evaluate_bindings).where(
                strategy_evaluate_bindings.c.profile == profile,
                strategy_evaluate_bindings.c.request_digest == request_digest,
            )
        )
        row = result.mappings().one_or_none()
        if row is None:
            return None
        if row["request_document"] != request_document:
            raise LineageError("Evaluate request digest collision detected.")
        return row["outcome_document"]

    async def lock_evaluate_binding(self, *, profile: str, request_digest: str) -> None:
        """Serialize one exact evaluate key until its transaction finishes."""
        if profile != "PERSONAL_SPOT_RESEARCH" or len(request_digest) != 64:
            raise LineageError("Invalid strategy evaluate lock identity.")
        lock_key = f"{profile}:{request_digest}"
        await self._session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(lock_key, 0)))
        )

    async def append_spot_agent_handoff(
        self,
        *,
        context: MarketContextV5,
        result: AgentResult,
        evaluation: AgentEvaluation,
        correlation_id: UUID,
        trace_id: UUID,
        created_at: datetime,
    ) -> None:
        """Append the exact producer-owned C-006/C-062/C-066/C-067 closure."""
        route = result.routing_decision
        if (
            type(context) is not MarketContextV5
            or type(result) is not AgentResult
            or type(evaluation) is not AgentEvaluation
            or type(correlation_id) is not UUID
            or type(trace_id) is not UUID
            or not isinstance(created_at, datetime)
            or created_at.tzinfo is None
            or result.context_id != context.context_id
            or type(result.output) is not MarketContextV5
            or canonical_sha256(result.output) != canonical_sha256(context)
            or evaluation.result_id != result.result_id
            or evaluation.result_contract_id != "C-062"
            or evaluation.result_schema_version != "1"
            or evaluation.result_status is not result.status
            or evaluation.outcome.value != "COMPLETED"
            or evaluation.schema_state.value != "VALID"
            or evaluation.agent_id != result.agent_id
            or evaluation.agent_version != result.agent_version
            or evaluation.provider_id != route.provider_id
            or evaluation.model_id != route.model_id
            or evaluation.model_version != route.model_version
            or evaluation.prompt_id != route.prompt_id
            or evaluation.prompt_version != route.prompt_version
            or evaluation.output_contract_id != "C-006"
            or evaluation.output_schema_version != "5"
            or evaluation.task_id != result.task_id
            or evaluation.context_id != context.context_id
            or evaluation.correlation_id != correlation_id
            or evaluation.trace_id != trace_id
            or evaluation.routing_decision_ref.contract_id != "C-067"
            or evaluation.routing_decision_ref.schema_version != "1"
            or evaluation.routing_decision_ref.entity_id != route.request_id
            or evaluation.routing_decision_ref.content_sha256 != canonical_sha256(route)
        ):
            raise LineageError(
                "Spot agent handoff does not bind exact producer outputs."
            )
        context_key = key_for(context)
        result_key = key_for(result)
        evaluation_key = key_for(evaluation)
        routing_key = key_for(route)
        for record in (context, route, result, evaluation):
            await self._append(record)
        values = {
            "context_contract_id": context_key.contract_id,
            "context_record_id": context_key.record_id,
            "context_version": context_key.version,
            "context_sha256": _reference_content_sha256(context),
            "result_contract_id": result_key.contract_id,
            "result_record_id": result_key.record_id,
            "result_version": result_key.version,
            "result_sha256": _reference_content_sha256(result),
            "evaluation_contract_id": evaluation_key.contract_id,
            "evaluation_record_id": evaluation_key.record_id,
            "evaluation_version": evaluation_key.version,
            "evaluation_sha256": _reference_content_sha256(evaluation),
            "routing_contract_id": routing_key.contract_id,
            "routing_record_id": routing_key.record_id,
            "routing_version": routing_key.version,
            "routing_sha256": _reference_content_sha256(route),
            "correlation_id": str(correlation_id),
            "trace_id": str(trace_id),
            "created_at": created_at.astimezone(UTC),
        }
        await self._session.execute(
            insert(spot_agent_handoff_bindings)
            .values(**values)
            .on_conflict_do_nothing()
        )
        stored = await self.get_spot_agent_handoff(context_key)
        if stored != (result, evaluation, correlation_id, trace_id):
            raise LineageError("Conflicting exact Spot agent handoff exists.")

    async def get_spot_agent_handoff(
        self, context_key: LineageKey
    ) -> tuple[AgentResult, AgentEvaluation, UUID, UUID] | None:
        """Resolve one exact immutable handoff by the requested C-006 identity."""
        if context_key.contract_id != "C-006" or context_key.version != "5":
            raise LineageError("Spot handoff lookup requires exact C-006v5 identity.")
        row = (
            (
                await self._session.execute(
                    select(spot_agent_handoff_bindings).where(
                        spot_agent_handoff_bindings.c.context_contract_id
                        == context_key.contract_id,
                        spot_agent_handoff_bindings.c.context_record_id
                        == context_key.record_id,
                        spot_agent_handoff_bindings.c.context_version
                        == context_key.version,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        result_key = LineageKey(
            row["result_contract_id"], row["result_record_id"], row["result_version"]
        )
        evaluation_key = LineageKey(
            row["evaluation_contract_id"],
            row["evaluation_record_id"],
            row["evaluation_version"],
        )
        routing_key = LineageKey(
            row["routing_contract_id"], row["routing_record_id"], row["routing_version"]
        )
        resolved = await self.resolve(
            (context_key, result_key, evaluation_key, routing_key)
        )
        context = resolved[context_key]
        result = resolved[result_key]
        evaluation = resolved[evaluation_key]
        routing = resolved[routing_key]
        if (
            type(context) is not MarketContextV5
            or type(result) is not AgentResult
            or type(evaluation) is not AgentEvaluation
            or type(routing) is not ModelRoutingDecision
            or _reference_content_sha256(context) != row["context_sha256"]
            or _reference_content_sha256(result) != row["result_sha256"]
            or _reference_content_sha256(evaluation) != row["evaluation_sha256"]
            or _reference_content_sha256(routing) != row["routing_sha256"]
            or result.routing_decision != routing
            or type(result.output) is not MarketContextV5
            or canonical_sha256(result.output) != canonical_sha256(context)
            or evaluation.result_id != result.result_id
            or evaluation.task_id != result.task_id
            or evaluation.context_id != context.context_id
            or evaluation.result_status is not result.status
            or evaluation.outcome.value != "COMPLETED"
            or evaluation.schema_state.value != "VALID"
            or evaluation.agent_id != result.agent_id
            or evaluation.agent_version != result.agent_version
            or evaluation.provider_id != routing.provider_id
            or evaluation.model_id != routing.model_id
            or evaluation.model_version != routing.model_version
            or evaluation.prompt_id != routing.prompt_id
            or evaluation.prompt_version != routing.prompt_version
            or evaluation.output_contract_id != "C-006"
            or evaluation.output_schema_version != "5"
            or evaluation.routing_decision_ref.entity_id != routing.request_id
            or str(evaluation.correlation_id) != row["correlation_id"]
            or str(evaluation.trace_id) != row["trace_id"]
        ):
            raise LineageError("Stored Spot agent handoff failed exact verification.")
        return (
            result,
            evaluation,
            UUID(row["correlation_id"]),
            UUID(row["trace_id"]),
        )

    async def list_strategy_artifact_records(
        self,
        *,
        contract_id: str | None,
        schema_version: str | None,
        limit: int,
        after: tuple[datetime, str, str, str] | None,
    ) -> tuple[tuple[LineageKey, object, datetime], ...]:
        supported = {"C-023", "C-024", "C-025", "C-026", "C-028", "C-070"}
        if (
            contract_id is not None and contract_id not in supported
        ) or not 1 <= limit <= 100:
            raise LineageError("Invalid bounded strategy artifact query.")
        filters: list[ColumnElement[bool]] = [
            records.c.contract_id.in_(supported),
            records.c.occurred_at.is_not(None),
        ]
        if contract_id is not None:
            filters.append(records.c.contract_id == contract_id)
        if schema_version is not None:
            filters.append(records.c.version == schema_version)
        if after is not None:
            at, after_contract_id, after_version, record_id = after
            if at.tzinfo is None or at.utcoffset() is None:
                raise LineageError("Artifact page cursor time must be timezone-aware.")
            filters.append(
                or_(
                    records.c.occurred_at > at,
                    and_(
                        records.c.occurred_at == at,
                        or_(
                            records.c.contract_id > after_contract_id,
                            and_(
                                records.c.contract_id == after_contract_id,
                                or_(
                                    records.c.version > after_version,
                                    and_(
                                        records.c.version == after_version,
                                        records.c.record_id > record_id,
                                    ),
                                ),
                            ),
                        ),
                    ),
                )
            )
        rows = (
            (
                await self._session.execute(
                    select(records)
                    .where(*filters)
                    .order_by(
                        records.c.occurred_at,
                        records.c.contract_id,
                        records.c.version,
                        records.c.record_id,
                    )
                    .limit(limit)
                )
            )
            .mappings()
            .all()
        )
        output: list[tuple[LineageKey, object, datetime]] = []
        for row in rows:
            key = LineageKey(row["contract_id"], row["record_id"], row["version"])
            record = await self.get(key)
            occurred_at = row["occurred_at"]
            if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
                raise LineageError("Stored strategy artifact time is invalid.")
            output.append((key, record, occurred_at.astimezone(UTC)))
        return tuple(output)

    async def append_evaluate_binding(
        self,
        *,
        profile: str,
        request_digest: str,
        request_document: str,
        outcome_document: str,
        created_at: datetime,
    ) -> str:
        """Insert or return the immutable outcome for one canonical request."""
        if (
            profile != "PERSONAL_SPOT_RESEARCH"
            or len(request_digest) != 64
            or not request_document
            or not outcome_document
            or len(request_document.encode("utf-8")) > 1_000_000
            or len(outcome_document.encode("utf-8")) > 1_000_000
            or created_at.tzinfo is None
        ):
            raise LineageError("Invalid bounded strategy evaluate binding.")
        statement = (
            insert(strategy_evaluate_bindings)
            .values(
                profile=profile,
                request_digest=request_digest,
                request_document=request_document,
                outcome_document=outcome_document,
                created_at=created_at,
            )
            .on_conflict_do_nothing()
            .returning(strategy_evaluate_bindings.c.request_digest)
        )
        inserted = (await self._session.execute(statement)).scalar_one_or_none()
        if inserted is not None:
            return outcome_document
        stored = await self.get_evaluate_binding(
            profile=profile,
            request_digest=request_digest,
            request_document=request_document,
        )
        if stored is None:
            raise LineageError("Evaluate result binding disappeared after insert.")
        return stored

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
                occurred_at=_occurred_at(record),
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
        registry_targets = {
            key for key in unique if key.contract_id in {"C-020", "C-021"}
        }
        lineage_targets = unique - registry_targets
        if lineage_targets:
            await self._session.execute(
                insert(links),
                [
                    dict(
                        **_identity(key),
                        target_contract_id=target.contract_id,
                        target_record_id=target.record_id,
                        target_version=target.version,
                    )
                    for target in lineage_targets
                ],
            )
        if registry_targets:
            await self._session.execute(
                insert(strategy_registry_links),
                [
                    dict(
                        **_identity(key),
                        target_contract_id=target.contract_id,
                        target_record_id=target.record_id,
                        target_version=target.version,
                        strategy_id=UUID(target.record_id)
                        if target.contract_id == "C-020"
                        else None,
                        strategy_version_id=UUID(target.record_id)
                        if target.contract_id == "C-021"
                        else None,
                    )
                    for target in registry_targets
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
