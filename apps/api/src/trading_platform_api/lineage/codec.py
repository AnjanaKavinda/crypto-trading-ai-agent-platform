"""Closed contract codec and stable storage identities, not dynamic deserialization."""

import json
import types
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, get_args, get_origin, get_type_hints
from uuid import UUID

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
    EvidenceItemV2,
    VersionedAssessment,
)
from trading_platform_api.analysis.versioned_contracts_v4 import (
    AnalysisSnapshotV4,
    ConflictAssessmentV3,
    ConfluenceAssessmentV3,
)
from trading_platform_api.analysis.versioned_contracts_v5 import (
    AdversarialAssessmentV2,
    MarketContextV5,
)
from trading_platform_api.contracts.serialization import (
    CANONICAL_JSON_VERSION,
    MAX_DOCUMENT_BYTES,
    canonical_json_dumps,
    canonical_sha256,
    serialize_contract,
)
from trading_platform_api.market_data.contracts import (
    DataQualityReport,
    DataQualityReportV2,
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
    Strategy,
    StrategyEligibility,
    StrategyVersion,
)
from trading_platform_api.strategy.contracts_v2 import (
    NoTradeDecisionV2,
    SignalEvidencePackageV2,
    SignalQualificationV2,
    SignalV2,
    StrategyVersionV2,
)
from trading_platform_api.validation.contracts_v2 import (
    CostAssumptionSetV2,
    QualificationValidationResultV2,
)

MODELS = {
    "C-001": MarketData,
    "C-002": MarketSnapshot,
    "C-003": DataQualityReport,
    "C-091": DataSourceRecord,
    "C-092": DatasetVersion,
    "C-101": HistoricalUniverse,
    "C-102": ObservationRevision,
    "C-103": ReconstructionManifest,
    "C-005": MarketRegime,
    "C-007": AnalysisSnapshotV4,
    "C-008": EvidenceItemV2,
    "C-093": AgentIndependenceReport,
    "C-006": MarketContextV5,
    "C-009": ConfluenceAssessmentV3,
    "C-010": ConflictAssessmentV3,
    "C-012": TechnicalAssessment,
    "C-019": AdversarialAssessmentV2,
    "C-020": Strategy,
    "C-021": StrategyVersionV2,
    "C-022": StrategyEligibility,
    "C-023": SignalCandidate,
    "C-024": SignalEvidencePackageV2,
    "C-025": SignalQualificationV2,
    "C-026": NoTradeDecisionV2,
    "C-027": CostAssumptionSetV2,
    "C-028": QualificationValidationResultV2,
    "C-069": AnalyticalUncertainty,
    "C-070": SignalV2,
    "C-062": AgentResult,
    "C-066": AgentEvaluation,
    "C-067": ModelRoutingDecision,
}


class LineageError(ValueError):
    """Missing, conflicting, unsupported or corrupt durable evidence."""


@dataclass(frozen=True, slots=True)
class LineageKey:
    contract_id: str
    record_id: str
    version: str = "1"

    def __post_init__(self) -> None:
        if self.contract_id not in MODELS:
            raise LineageError("Unsupported lineage contract.")
        for value in (self.record_id, self.version):
            if (
                type(value) is not str
                or not value.strip()
                or value != value.strip()
                or len(value.encode("utf-8")) > 512
            ):
                raise LineageError("Invalid bounded lineage identity.")


def key_for(record: object) -> LineageKey:
    if type(record) is MarketData:
        return LineageKey("C-001", str(record.market_data_id))
    if type(record) is MarketSnapshot:
        return LineageKey("C-002", str(record.snapshot_id))
    if type(record) is DataQualityReport:
        return LineageKey("C-003", str(record.report_id))
    if type(record) is DataQualityReportV2:
        return LineageKey("C-003", str(record.report_id), record.schema_version)
    if type(record) is MarketRegime:
        return LineageKey("C-005", str(record.regime_id), record.schema_version)
    if type(record) is AnalysisSnapshotV4:
        return LineageKey("C-007", str(record.snapshot_id), record.schema_version)
    if type(record) is EvidenceItemV2:
        return LineageKey("C-008", str(record.evidence_id), record.schema_version)
    if type(record) is AgentIndependenceReport:
        return LineageKey("C-093", str(record.report_id), record.schema_version)
    if type(record) is DataSourceRecord:
        return LineageKey("C-091", str(record.source_record_id))
    if type(record) is DatasetVersion:
        return LineageKey("C-092", record.dataset_id, record.version)
    if type(record) is HistoricalUniverse:
        return LineageKey("C-101", record.universe_id, record.version)
    if type(record) is ObservationRevision:
        return LineageKey("C-102", str(record.revision_id))
    if type(record) is ReconstructionManifest:
        return LineageKey("C-103", canonical_sha256(record))
    if type(record) is Strategy:
        return LineageKey("C-020", str(record.strategy_id), "1")
    if type(record) is StrategyVersion:
        return LineageKey("C-021", str(record.strategy_version_id), "1")
    if type(record) is StrategyVersionV2:
        return LineageKey("C-021", str(record.strategy_version_id), "2")
    if type(record) is SignalCandidate:
        return LineageKey("C-023", str(record.candidate_id), record.schema_version)
    if type(record) is SignalEvidencePackageV2:
        return LineageKey("C-024", str(record.package_id), record.schema_version)
    if type(record) is SignalQualificationV2:
        return LineageKey("C-025", str(record.qualification_id), record.schema_version)
    if type(record) is NoTradeDecisionV2:
        return LineageKey("C-026", str(record.decision_id), record.schema_version)
    if type(record) is QualificationValidationResultV2:
        return LineageKey("C-028", str(record.result_id), record.schema_version)
    if type(record) is SignalV2:
        return LineageKey("C-070", str(record.signal_id), record.schema_version)
    if type(record) is MarketContextV5:
        return LineageKey("C-006", str(record.context_id), record.schema_version)
    if type(record) is ConfluenceAssessmentV3:
        return LineageKey("C-009", str(record.assessment_id), record.schema_version)
    if type(record) is ConflictAssessmentV3:
        return LineageKey("C-010", str(record.assessment_id), record.schema_version)
    if type(record) is TechnicalAssessment:
        return LineageKey("C-012", str(record.assessment_id), "1")
    if type(record) is AdversarialAssessmentV2:
        return LineageKey("C-019", str(record.assessment_id), record.schema_version)
    if type(record) is StrategyEligibility:
        return LineageKey("C-022", str(record.eligibility_id), record.schema_version)
    if type(record) is CostAssumptionSetV2:
        return LineageKey("C-027", str(record.assumption_set_id), record.schema_version)
    if type(record) is AnalyticalUncertainty:
        return LineageKey("C-069", str(record.uncertainty_id), record.schema_version)
    if type(record) is AgentResult:
        return LineageKey("C-062", str(record.result_id), record.schema_version)
    if type(record) is AgentEvaluation:
        return LineageKey("C-066", str(record.evaluation_id), record.schema_version)
    if type(record) is ModelRoutingDecision:
        return LineageKey("C-067", str(record.request_id), record.schema_version)
    raise LineageError("Unsupported lineage contract type.")


def _restore_canonical_tuples(value: Any) -> Any:
    if type(value) is list:
        return tuple(_restore_canonical_tuples(item) for item in value)
    if type(value) is dict:
        return {key: _restore_canonical_tuples(item) for key, item in value.items()}
    return value


def encode(record: object) -> str:
    key_for(record)
    if type(record) is TechnicalAssessment:
        # C-012 v1 predates the fixed dataclass-field metadata convention. Keep
        # its established payload shape and carry the ClassVar contract identity
        # in the canonical envelope, without changing the shared C-012 schema.
        result = canonical_json_dumps(
            {
                "canonicalization_version": CANONICAL_JSON_VERSION,
                "contract_id": "C-012",
                "schema_version": "1",
                "payload_version": "wire-1",
                "payload": record,
            }
        )
    else:
        result = serialize_contract(record, payload_version="wire-1")
        if type(record) is MarketContextV5:
            envelope = _restore_canonical_tuples(json.loads(result))
            envelope["payload"]["assessments"] = tuple(
                {
                    "assessment_contract_id": item.contract_id,
                    "record": item,
                }
                for item in record.assessments
            )
            result = canonical_json_dumps(envelope)
    if len(result.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise LineageError("Lineage document exceeds the size limit.")
    return result


def _decode(kind: Any, value: Any) -> Any:
    origin = get_origin(kind)
    args = get_args(kind)
    if origin is types.UnionType:
        if value is None and type(None) in args:
            return None
        candidates = [item for item in args if item is not type(None)]
        if len(candidates) == 1:
            return _decode(candidates[0], value)
        decoded: list[Any] = []
        for candidate in candidates:
            try:
                decoded.append(_decode(candidate, value))
            except (ValueError, TypeError, KeyError, ArithmeticError):
                continue
        if len(decoded) != 1:
            raise LineageError("Contract union did not resolve uniquely.")
        return decoded[0]
    if origin is tuple and len(args) == 2 and args[1] is Ellipsis:
        if type(value) is not list:
            raise LineageError("Expected immutable sequence payload.")
        return tuple(_decode(args[0], item) for item in value)
    if kind in (str, int, bool):
        if type(value) is not kind:
            raise LineageError("Invalid scalar type.")
        return value
    if kind in (UUID, datetime, Decimal):
        if type(value) is not str:
            raise LineageError("Expected canonical scalar string.")
        return datetime.fromisoformat(value) if kind is datetime else kind(value)
    if kind is object:
        # PERSONAL_SPOT_RESEARCH persists C-062 only for its exact C-006v5
        # output. Do not deserialize arbitrary provider output dynamically.
        if (
            type(value) is dict
            and value.get("contract_id") == "C-006"
            and value.get("schema_version") == "5"
        ):
            return _decode(MarketContextV5, value)
        raise LineageError("Unsupported C-062 output contract.")
    if isinstance(kind, type) and type(value) is kind:
        return value
    if isinstance(kind, type) and issubclass(kind, Enum):
        if type(value) is not str:
            raise LineageError("Expected canonical enum string.")
        try:
            return kind(value)
        except ValueError as exc:
            raise LineageError("Unknown canonical enum value.") from exc
    if isinstance(kind, type) and is_dataclass(kind):
        if type(value) is not dict or set(value) != {f.name for f in fields(kind)}:
            raise LineageError("Contract payload fields do not match.")
        hints = get_type_hints(kind)
        return kind(
            **{
                f.name: _decode(hints[f.name], value[f.name])
                for f in fields(kind)
                if f.init
            }
        )
    raise LineageError("Unsupported contract value type.")


def decode_value(kind: type[Any], value: Any) -> Any:
    """Decode one nested value through the same closed contract type rules."""
    if not isinstance(kind, type):
        raise LineageError("A concrete registered value type is required.")
    try:
        decoded = _decode(kind, value)
        if canonical_json_dumps(decoded) != json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ):
            raise LineageError("Nested contract value is not canonical.")
        return decoded
    except (ValueError, TypeError, KeyError, RecursionError, ArithmeticError):
        raise LineageError("Invalid or corrupt nested contract value.") from None


def decode(document: str) -> object:
    try:
        if (
            type(document) is not str
            or len(document.encode("utf-8")) > MAX_DOCUMENT_BYTES
        ):
            raise LineageError("Invalid bounded lineage document.")
        envelope = json.loads(document)
        if type(envelope) is not dict or set(envelope) != {
            "canonicalization_version",
            "contract_id",
            "schema_version",
            "payload_version",
            "payload",
        }:
            raise LineageError("Invalid lineage envelope.")
        contract_id = envelope["contract_id"]
        schema_version = envelope["schema_version"]
        if contract_id == "C-003":
            model = {
                "1": DataQualityReport,
                "2": DataQualityReportV2,
            }.get(schema_version)
            if model is None:
                raise LineageError("Unsupported C-003 schema version.")
        else:
            model = MODELS[contract_id]
            if contract_id == "C-021":
                model = {"1": StrategyVersion, "2": StrategyVersionV2}.get(
                    schema_version
                )
                if model is None:
                    raise LineageError("Unsupported C-021 schema version.")
            expected_version = {
                "C-005": "1",
                "C-007": "4",
                "C-008": "2",
                "C-093": "1",
                "C-006": "5",
                "C-009": "3",
                "C-010": "3",
                "C-012": "1",
                "C-019": "2",
                "C-020": "1",
                "C-021": schema_version,
                "C-022": "1",
                "C-023": "1",
                "C-024": "2",
                "C-025": "2",
                "C-026": "2",
                "C-027": "2",
                "C-028": "2",
                "C-069": "1",
                "C-070": "2",
                "C-062": "1",
                "C-066": "1",
                "C-067": "1",
            }.get(contract_id)
            if expected_version is not None and schema_version != expected_version:
                raise LineageError("Unsupported analysis contract version.")
        payload = dict(envelope["payload"])
        if contract_id == "C-006":
            assessment_types = {
                getattr(item, "contract_id", None): item
                for item in get_args(VersionedAssessment)
            }
            decoded_assessments = []
            for item in payload.get("assessments", []):
                if type(item) is not dict or set(item) != {
                    "assessment_contract_id",
                    "record",
                }:
                    raise LineageError("C-006 assessment type identity is missing.")
                assessment_type = assessment_types.get(item["assessment_contract_id"])
                if assessment_type is None:
                    raise LineageError("Unsupported C-006 assessment type.")
                decoded_assessments.append(_decode(assessment_type, item["record"]))
            payload["assessments"] = decoded_assessments
        if contract_id == "C-012":
            # C-012 v1 stores contract_id as a ClassVar, so it is envelope
            # metadata and must not be injected into its dataclass payload.
            if payload.get("schema_version") != schema_version:
                raise LineageError("C-012 payload schema version is mismatched.")
        else:
            payload.update(
                contract_id=contract_id,
                schema_version=schema_version,
            )
        record = _decode(model, payload)
        if encode(record) != document:
            raise LineageError("Unsupported version or noncanonical lineage document.")
        return record
    except (ValueError, TypeError, KeyError, RecursionError, ArithmeticError):
        raise LineageError("Invalid or corrupt lineage document.") from None
