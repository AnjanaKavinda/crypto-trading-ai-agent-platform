"""ADR-0030 structural consumers; construction is not verified issuance."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import TypeVar, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from trading_platform_api.analysis.versioned_contracts_v5 import MarketContextV5
from trading_platform_api.contracts.serialization import (
    canonical_json_dumps,
    canonical_sha256,
)
from trading_platform_api.lineage.codec import decode as decode_lineage
from trading_platform_api.lineage.codec import decode_value
from trading_platform_api.lineage.codec import encode as encode_lineage
from trading_platform_api.strategy.contracts import (
    QualificationStatus,
    SignalDirection,
    SignalLifecycleState,
    StrategyContractError,
    VersionReference,
    _digest,
)
from trading_platform_api.strategy.contracts_v2 import StrategyVersionV2
from trading_platform_api.strategy.registry import (
    strategy_version_content_sha256,
    validate_semantic_version,
)
from trading_platform_api.validation.qualification_result_codec_v3 import (
    encode_qualification_result_v3,
)
from trading_platform_api.validation.qualification_result_v3 import (
    QualificationOutcomeV3,
    QualificationValidationResultV3,
)
from trading_platform_api.validation.qualification_study_v3 import _time

_T = TypeVar("_T")

_QUALIFICATION_NAMESPACE = uuid5(
    NAMESPACE_URL, "trading-platform:C-025:3:consumer-identity-v1"
)
_SIGNAL_NAMESPACE = uuid5(
    NAMESPACE_URL, "trading-platform:C-070:3:consumer-identity-v1"
)


def _checked(kind: type[_T], value: object) -> _T:
    if type(value) is not kind:
        raise StrategyContractError(f"exact {kind.__name__} required.")
    return cast(_T, decode_value(kind, json.loads(canonical_json_dumps(value))))


def _context_from_document(document: str) -> MarketContextV5:
    if type(document) is not str:
        raise StrategyContractError("canonical C-006v5 document required.")
    context = decode_lineage(document)
    if type(context) is not MarketContextV5 or encode_lineage(context) != document:
        raise StrategyContractError("exact canonical C-006v5 required.")
    return context


def _reference(
    kind: str, identity: UUID, version: str, digest: str
) -> VersionReference:
    return VersionReference(kind, identity, version, digest)


def _identity(
    identity: object, digest: str, payload: dict[str, object], namespace: UUID
) -> None:
    _digest("content_sha256", digest)
    if (
        type(identity) is not UUID
        or digest != canonical_sha256(payload)
        or identity != uuid5(namespace, digest)
    ):
        raise StrategyContractError("CONSUMER_CONTENT_OR_IDENTITY_MISMATCH")


def _qualification_payload(
    validation: QualificationValidationResultV3,
    evaluated_at: datetime,
    expires_at: datetime,
) -> dict[str, object]:
    if type(validation) is not QualificationValidationResultV3:
        raise StrategyContractError("C-025v3 requires exact C-028v3.")
    encode_qualification_result_v3(validation)
    evaluated, expires = (
        _time("evaluated_at", evaluated_at),
        _time("expires_at", expires_at),
    )
    c, e, p = validation.candidate, validation.evidence_package, validation.protocol
    if (
        not validation.created_at
        <= evaluated
        < expires
        <= min(validation.valid_until, c.expires_at, e.expires_at, p.valid_until)
    ):
        raise StrategyContractError("QUALIFICATION_SOURCE_TIME_OR_EXPIRY_MISMATCH")
    status = {
        QualificationOutcomeV3.PASS: QualificationStatus.QUALIFIED,
        QualificationOutcomeV3.FAIL: QualificationStatus.REJECTED,
        QualificationOutcomeV3.INSUFFICIENT_VALIDATION: QualificationStatus.INSUFFICIENT_EVIDENCE,
    }[validation.outcome]
    return dict(
        validation=validation,
        candidate=_reference("C-023", c.candidate_id, "1", canonical_sha256(c)),
        strategy_version=_reference(
            "C-021",
            p.strategy_version.artifact_id,
            p.strategy_semantic_version,
            p.strategy_version.content_sha256,
        ),
        evidence_package=_reference("C-024", e.package_id, "2", e.content_sha256),
        evidence_package_valid_until=e.expires_at,
        status=status,
        evaluated_at=evaluated,
        expires_at=expires,
        qualification_authorized=False,
        approval_authorized=False,
        execution_authorized=False,
        contract_id="C-025",
        schema_version="3",
        identity_method="qualification-consumer-identity-v1",
    )


@dataclass(frozen=True, slots=True)
class SignalQualificationV3:
    """Declared research status; not authenticated qualification or authority."""

    qualification_id: UUID
    validation: QualificationValidationResultV3
    evaluated_at: datetime
    expires_at: datetime
    content_sha256: str
    candidate: VersionReference = field(init=False)
    strategy_version: VersionReference = field(init=False)
    evidence_package: VersionReference = field(init=False)
    evidence_package_valid_until: datetime = field(init=False)
    status: QualificationStatus = field(init=False)
    qualification_authorized: bool = field(default=False, init=False)
    approval_authorized: bool = field(default=False, init=False)
    execution_authorized: bool = field(default=False, init=False)
    contract_id: str = field(default="C-025", init=False)
    schema_version: str = field(default="3", init=False)
    identity_method: str = field(
        default="qualification-consumer-identity-v1", init=False
    )

    def __post_init__(self) -> None:
        payload = _qualification_payload(
            self.validation, self.evaluated_at, self.expires_at
        )
        for name, value in payload.items():
            object.__setattr__(self, name, value)
        _identity(
            self.qualification_id,
            self.content_sha256,
            payload,
            _QUALIFICATION_NAMESPACE,
        )

    @property
    def reference(self) -> VersionReference:
        return _reference("C-025", self.qualification_id, "3", self.content_sha256)

    @classmethod
    def build(
        cls,
        *,
        validation: QualificationValidationResultV3,
        evaluated_at: datetime,
        expires_at: datetime,
    ) -> SignalQualificationV3:
        payload = _qualification_payload(validation, evaluated_at, expires_at)
        digest = canonical_sha256(payload)
        return cls(
            uuid5(_QUALIFICATION_NAMESPACE, digest),
            validation,
            evaluated_at,
            expires_at,
            digest,
        )


@dataclass(frozen=True, slots=True)
class SignalLineageV3:
    candidate_id: UUID
    candidate: VersionReference
    strategy_version_id: UUID
    strategy_version: VersionReference
    evidence_package_id: UUID
    evidence_package: VersionReference
    qualification_id: UUID
    qualification: VersionReference
    validation_id: UUID
    validation: VersionReference
    strategy_schema_version: str = field(default="2", init=False)

    def __post_init__(self) -> None:
        for name, kind, version in (
            ("candidate", "C-023", "1"),
            ("strategy_version", "C-021", None),
            ("evidence_package", "C-024", "2"),
            ("qualification", "C-025", "3"),
            ("validation", "C-028", "3"),
        ):
            reference = getattr(self, name)
            identity_name = (
                "strategy_version_id" if name == "strategy_version" else name + "_id"
            )
            if type(reference) is not VersionReference:
                raise StrategyContractError("exact lineage reference required.")
            reference.__post_init__()
            if (
                reference.artifact_type != kind
                or (version is not None and reference.version != version)
                or type(getattr(self, identity_name)) is not UUID
                or reference.artifact_id != getattr(self, identity_name)
            ):
                raise StrategyContractError("LINEAGE_IDENTITY_OR_VERSION_MISMATCH")
        validate_semantic_version(self.strategy_version.version)


def _signal_payload(
    qualification: SignalQualificationV3,
    strategy: StrategyVersionV2,
    market_context: MarketContextV5,
    created_at: datetime,
    expires_at: datetime,
) -> dict[str, object]:
    q = _checked(SignalQualificationV3, qualification)
    s = _checked(StrategyVersionV2, strategy)
    if type(market_context) is not MarketContextV5:
        raise StrategyContractError("exact MarketContextV5 required.")
    context_document = encode_lineage(market_context)
    context = _context_from_document(context_document)
    c, e, v = q.validation.candidate, q.validation.evidence_package, q.validation
    at, expires = _time("created_at", created_at), _time("expires_at", expires_at)
    strategy_digest = strategy_version_content_sha256(s)
    conflicts = tuple(
        _reference("C-010", x.assessment_id, x.schema_version, canonical_sha256(x))
        for x in context.conflicts
    )
    uncertainties = tuple(
        _reference("C-069", x.uncertainty_id, x.schema_version, canonical_sha256(x))
        for x in context.uncertainties
    )
    if (
        q.status is not QualificationStatus.QUALIFIED
        or v.outcome is not QualificationOutcomeV3.PASS
    ):
        raise StrategyContractError("C-070v3 requires declared qualification PASS.")
    if (
        s.strategy_id != c.strategy_id
        or s.strategy_version_id != c.strategy_version_id
        or s.content_sha256 != strategy_digest
        or q.strategy_version
        != _reference(
            "C-021", s.strategy_version_id, s.semantic_version, strategy_digest
        )
        or c.asset not in s.supported_assets
        or c.instrument_id not in s.supported_instruments
        or c.timeframe not in s.supported_timeframes
        or (context.context_id, context.asset, context.instrument_id)
        != (c.market_context_id, c.asset, c.instrument_id)
        or e.market_context
        != _reference("C-006", context.context_id, "5", canonical_sha256(context))
        or (
            context.analysis_snapshot.snapshot_id,
            context.analysis_snapshot.schema_version,
            context.analysis_snapshot.content_sha256,
        )
        != (
            e.analysis_snapshot.artifact_id,
            e.analysis_snapshot.version,
            e.analysis_snapshot.content_sha256,
        )
        or (
            context.regime.asset,
            context.regime.instrument_id,
            context.regime.timeframe,
        )
        != (c.asset, c.instrument_id, c.timeframe)
        or e.conflicts != conflicts
        or e.uncertainties != uncertainties
    ):
        raise StrategyContractError("SIGNAL_STRATEGY_CONTEXT_OR_EVIDENCE_MISMATCH")
    if (
        not max(
            q.evaluated_at,
            v.created_at,
            s.created_at,
            context.as_of,
            context.regime.as_of,
        )
        <= at
        < expires
        <= min(
            q.expires_at,
            v.valid_until,
            c.expires_at,
            e.expires_at,
            context.expires_at,
            context.regime.expires_at,
        )
    ):
        raise StrategyContractError("SIGNAL_SOURCE_TIME_OR_EXPIRY_MISMATCH")
    protocol_ref = v.protocol.reference
    lineage = SignalLineageV3(
        c.candidate_id,
        q.candidate,
        c.strategy_version_id,
        q.strategy_version,
        e.package_id,
        q.evidence_package,
        q.qualification_id,
        q.reference,
        v.result_id,
        _reference("C-028", v.result_id, "3", v.content_sha256),
    )
    return dict(
        qualification=q,
        strategy=s,
        market_context_document=context_document,
        lineage=lineage,
        strategy_id=s.strategy_id,
        strategy_version_id=s.strategy_version_id,
        parameter_set=q.strategy_version,
        configuration=_reference(
            protocol_ref.artifact_type,
            protocol_ref.artifact_id,
            protocol_ref.version,
            protocol_ref.content_sha256,
        ),
        qualification_status=q.status,
        market_context_id=c.market_context_id,
        analysis_snapshot_id=c.analysis_snapshot_id,
        asset=c.asset,
        instrument_id=c.instrument_id,
        timeframe=c.timeframe,
        direction=c.direction,
        evidence_ids=c.supporting_evidence_ids,
        data_quality_report_id=c.data_quality_report_id,
        regime_id=context.regime.regime_id,
        conflict_ids=tuple(x.artifact_id for x in e.conflicts),
        uncertainty_ids=tuple(x.artifact_id for x in e.uncertainties),
        lifecycle=SignalLifecycleState.QUALIFIED,
        created_at=at,
        expires_at=expires,
        qualification_authorized=False,
        approval_authorized=False,
        execution_authorized=False,
        contract_id="C-070",
        schema_version="3",
        identity_method="signal-consumer-identity-v1",
    )


@dataclass(frozen=True, slots=True)
class SignalV3:
    """Structural C-070v3; no verified issuer or production reader is enabled."""

    signal_id: UUID
    qualification: SignalQualificationV3
    strategy: StrategyVersionV2
    market_context_document: str
    created_at: datetime
    expires_at: datetime
    content_sha256: str
    lineage: SignalLineageV3 = field(init=False)
    strategy_id: UUID = field(init=False)
    strategy_version_id: UUID = field(init=False)
    parameter_set: VersionReference = field(init=False)
    configuration: VersionReference = field(init=False)
    qualification_status: QualificationStatus = field(init=False)
    market_context_id: UUID = field(init=False)
    analysis_snapshot_id: UUID = field(init=False)
    asset: str = field(init=False)
    instrument_id: str = field(init=False)
    timeframe: str = field(init=False)
    direction: SignalDirection = field(init=False)
    evidence_ids: tuple[UUID, ...] = field(init=False)
    data_quality_report_id: UUID = field(init=False)
    regime_id: UUID = field(init=False)
    conflict_ids: tuple[UUID, ...] = field(init=False)
    uncertainty_ids: tuple[UUID, ...] = field(init=False)
    lifecycle: SignalLifecycleState = field(init=False)
    qualification_authorized: bool = field(default=False, init=False)
    approval_authorized: bool = field(default=False, init=False)
    execution_authorized: bool = field(default=False, init=False)
    contract_id: str = field(default="C-070", init=False)
    schema_version: str = field(default="3", init=False)
    identity_method: str = field(default="signal-consumer-identity-v1", init=False)

    def __post_init__(self) -> None:
        payload = _signal_payload(
            self.qualification,
            self.strategy,
            _context_from_document(self.market_context_document),
            self.created_at,
            self.expires_at,
        )
        for name, value in payload.items():
            object.__setattr__(self, name, value)
        _identity(self.signal_id, self.content_sha256, payload, _SIGNAL_NAMESPACE)

    @property
    def market_context(self) -> MarketContextV5:
        return _context_from_document(self.market_context_document)

    @classmethod
    def build(
        cls,
        *,
        qualification: SignalQualificationV3,
        strategy: StrategyVersionV2,
        market_context: MarketContextV5,
        created_at: datetime,
        expires_at: datetime,
    ) -> SignalV3:
        payload = _signal_payload(
            qualification, strategy, market_context, created_at, expires_at
        )
        digest = canonical_sha256(payload)
        return cls(
            uuid5(_SIGNAL_NAMESPACE, digest),
            qualification,
            strategy,
            cast(str, payload["market_context_document"]),
            created_at,
            expires_at,
            digest,
        )
