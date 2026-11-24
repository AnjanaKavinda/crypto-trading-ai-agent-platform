"""Synthetic consumer behavior, never verified qualification/performance evidence."""

import json
from dataclasses import FrozenInstanceError, fields, replace
from datetime import timedelta
from uuid import UUID

import pytest
from test_qualification_result_v3 import change_gate
from test_qualification_result_v3 import values as validation_values
from test_strategy_evidence_package import _package
from test_wave4_contract_foundation import _v2_case
from trading_platform_api.contracts.serialization import MAX_DOCUMENT_BYTES
from trading_platform_api.lineage.codec import LineageError, decode, encode
from trading_platform_api.strategy.codec import SignalCodecError, decode_signal_contract
from trading_platform_api.strategy.contracts import (
    QualificationStatus,
)
from trading_platform_api.strategy.qualification_consumer_codec_v3 import (
    decode_qualification_consumer_v3,
    encode_qualification_consumer_v3,
)
from trading_platform_api.strategy.qualification_consumers_v3 import (
    SignalQualificationV3,
    SignalV3,
)
from trading_platform_api.validation.contracts_v2 import ValidationArtifactReferenceV2
from trading_platform_api.validation.qualification_result_v3 import (
    QualificationGateV3 as Gate,
)
from trading_platform_api.validation.qualification_result_v3 import (
    QualificationOutcomeV3 as Outcome,
)
from trading_platform_api.validation.qualification_result_v3 import (
    QualificationValidationResultV3 as Result,
)
from trading_platform_api.validation.qualification_result_v3 import gate_methods
from trading_platform_api.validation.qualification_study_v3 import (
    QualificationStudyProtocolV3,
)


def source_values():
    case, _, strategy, candidate = _v2_case()
    package = _package(case, candidate=candidate).package
    assert package is not None
    context = case[2].market_context
    v = validation_values()
    p = v["protocol"]
    args = {
        f.name: getattr(p, f.name)
        for f in fields(p)
        if f.init and f.name not in {"protocol_id", "content_sha256"}
    }
    args.update(
        strategy_version=ValidationArtifactReferenceV2(
            "C-021", strategy.strategy_version_id, "2", strategy.content_sha256
        ),
        strategy_semantic_version=strategy.semantic_version,
        asset=candidate.asset,
        instrument_id=candidate.instrument_id,
        timeframe=candidate.timeframe,
        valid_until=min(candidate.expires_at, package.expires_at),
    )
    protocol = QualificationStudyProtocolV3.build(**args)
    at = candidate.created_at + timedelta(seconds=10)
    expiry = min(candidate.expires_at, package.expires_at)
    quality = ValidationArtifactReferenceV2(
        "C-003",
        package.data_quality_report.artifact_id,
        package.data_quality_report.version,
        package.data_quality_report.content_sha256,
    )
    v.update(
        protocol=protocol,
        candidate=candidate,
        evidence_package=package,
        as_of=at,
        created_at=at,
        valid_until=expiry,
        gates=tuple(
            replace(
                g,
                sources=(quality,) if g.gate is Gate.DATA_INTEGRITY else g.sources,
                methods=gate_methods(protocol, g.gate),
                as_of=at,
                valid_until=expiry,
            )
            for g in v["gates"]
        ),
    )
    return v, strategy, context


def qualification(v):
    return SignalQualificationV3.build(
        validation=Result.build(**v),
        evaluated_at=v["as_of"] + timedelta(seconds=1),
        expires_at=v["valid_until"],
    )


def signal(q, s, context):
    return SignalV3.build(
        qualification=q,
        strategy=s,
        market_context=context,
        created_at=q.evaluated_at + timedelta(seconds=1),
        expires_at=min(q.expires_at, context.expires_at, context.regime.expires_at),
    )


def test_exact_qualification_and_signal_are_deterministic_closed_projections():
    v, s, context = source_values()
    q = qualification(v)
    out = signal(q, s, context)
    assert q == qualification(v)
    assert out == signal(q, s, context)
    assert q.status is QualificationStatus.QUALIFIED
    assert out.qualification_status is QualificationStatus.QUALIFIED
    assert out.lineage.validation.version == out.lineage.qualification.version == "3"
    assert out.lineage.candidate.version == "1"
    assert out.lineage.strategy_schema_version == "2"
    assert out.parameter_set == q.strategy_version
    assert out.parameter_set.version == s.semantic_version
    assert out.configuration.artifact_id == v["protocol"].protocol_id
    assert out.configuration.content_sha256 == v["protocol"].content_sha256
    assert out.regime_id == context.regime.regime_id
    assert out.conflict_ids == tuple(
        x.artifact_id for x in v["evidence_package"].conflicts
    )
    assert out.uncertainty_ids == tuple(
        x.artifact_id for x in v["evidence_package"].uncertainties
    )
    assert out.evidence_ids == v["candidate"].supporting_evidence_ids
    for value in (q, out):
        assert (
            not value.qualification_authorized
            and not value.approval_authorized
            and not value.execution_authorized
        )
        assert (
            decode_qualification_consumer_v3(encode_qualification_consumer_v3(value))
            == value
        )
        with pytest.raises(FrozenInstanceError):
            value.expires_at = value.expires_at + timedelta(seconds=1)
    with pytest.raises(ValueError, match="CONTENT_OR_IDENTITY"):
        replace(q, evaluated_at=q.evaluated_at + timedelta(microseconds=1))
    with pytest.raises(ValueError, match="CONTENT_OR_IDENTITY"):
        replace(out, created_at=out.created_at + timedelta(microseconds=1))


@pytest.mark.parametrize(
    "outcome,status",
    [
        (Outcome.FAIL, QualificationStatus.REJECTED),
        (Outcome.INSUFFICIENT_VALIDATION, QualificationStatus.INSUFFICIENT_EVIDENCE),
    ],
)
def test_failed_and_insufficient_validation_cannot_construct_signal(outcome, status):
    v, s, context = source_values()
    v = change_gate(
        v,
        Gate.OOS,
        outcome=outcome,
        reasons=("SYNTHETIC_BLOCKER",),
        **({"sources": ()} if outcome is Outcome.INSUFFICIENT_VALIDATION else {}),
    )
    q = qualification(v)
    assert q.status is status
    assert any("SYNTHETIC_BLOCKER" in g.reasons for g in q.validation.gates)
    with pytest.raises(ValueError, match="qualification PASS"):
        signal(q, s, context)


@pytest.mark.parametrize(
    "kind",
    [
        "strategy_id",
        "strategy_content",
        "context",
        "snapshot",
        "regime",
        "conflicts",
        "uncertainties",
    ],
)
def test_signal_rejects_unrelated_or_changed_source_closure(kind):
    v, s, context = source_values()
    q = qualification(v)
    with pytest.raises(ValueError):
        if kind == "strategy_id":
            s = replace(s, strategy_id=UUID(int=9))
        elif kind == "strategy_content":
            s = replace(s, content_sha256="b" * 64)
        elif kind == "context":
            context = replace(context, context_id=UUID(int=9))
        elif kind == "snapshot":
            context = replace(
                context,
                analysis_snapshot=replace(
                    context.analysis_snapshot, content_sha256="b" * 64
                ),
            )
        elif kind == "regime":
            context = replace(
                context, regime=replace(context.regime, regime_id=UUID(int=9))
            )
        elif kind == "conflicts":
            context = replace(context, conflicts=())
        else:
            context = replace(context, uncertainties=())
        signal(q, s, context)


@pytest.mark.parametrize("field", ["evaluated_at", "expires_at"])
def test_qualification_rejects_future_or_expired_sources(field):
    v, _, _ = source_values()
    args = dict(
        validation=Result.build(**v),
        evaluated_at=v["as_of"] + timedelta(seconds=1),
        expires_at=v["valid_until"],
    )
    args[field] = (
        v["as_of"] - timedelta(seconds=1)
        if field == "evaluated_at"
        else v["valid_until"] + timedelta(seconds=1)
    )
    with pytest.raises(ValueError, match="SOURCE_TIME_OR_EXPIRY"):
        SignalQualificationV3.build(**args)


def test_signal_rejects_future_or_expired_sources_and_fixed_field_overrides():
    v, s, context = source_values()
    q = qualification(v)
    args = dict(
        qualification=q,
        strategy=s,
        market_context=context,
        created_at=q.evaluated_at + timedelta(seconds=1),
        expires_at=q.expires_at,
    )
    for change in (
        {"created_at": q.evaluated_at - timedelta(microseconds=1)},
        {"expires_at": q.expires_at + timedelta(seconds=1)},
    ):
        with pytest.raises(ValueError, match="SOURCE_TIME_OR_EXPIRY"):
            SignalV3.build(**(args | change))
    for change in (
        {"regime_id": UUID(int=9)},
        {"parameter_set": q.strategy_version},
        {"qualification_status": QualificationStatus.QUALIFIED_HIGH_EVIDENCE},
    ):
        with pytest.raises(TypeError):
            SignalV3.build(**(args | change))


def test_lineage_requires_exact_versions_and_identity():
    v, s, context = source_values()
    lineage = signal(qualification(v), s, context).lineage
    with pytest.raises(ValueError, match="LINEAGE"):
        replace(lineage, validation=replace(lineage.validation, version="2"))
    with pytest.raises(ValueError, match="LINEAGE"):
        replace(lineage, qualification_id=UUID(int=9))
    with pytest.raises(ValueError):
        replace(
            lineage,
            strategy_version=replace(lineage.strategy_version, version="not-semver"),
        )


@pytest.mark.parametrize("contract", ["qualification", "signal"])
@pytest.mark.parametrize(
    "change",
    ["schema", "wire", "unknown", "nested", "fixed", "digest", "decimal", "spacing"],
)
def test_codec_rejects_wrong_versions_tampering_and_noncanonical_values(
    contract, change
):
    v, s, context = source_values()
    q = qualification(v)
    obj = q if contract == "qualification" else signal(q, s, context)
    doc = json.loads(encode_qualification_consumer_v3(obj))
    payload = doc["payload"]
    if change == "schema":
        doc["schema_version"] = "2"
    elif change == "wire":
        doc["payload_version"] = "wire-2"
    elif change == "unknown":
        payload["extra"] = True
    elif change == "fixed":
        payload["execution_authorized"] = True
    elif change == "digest":
        payload["content_sha256"] = "b" * 64
    else:
        result = (
            payload["validation"]
            if contract == "qualification"
            else payload["qualification"]["validation"]
        )
        if change == "nested":
            result["protocol"]["extra"] = True
        elif change == "decimal":
            result["observed_conditional_win_rate"] = 0.8
    bad = (
        json.dumps(doc, sort_keys=True, separators=(",", ":"))
        if change != "spacing"
        else json.dumps(doc, indent=2)
    )
    with pytest.raises(ValueError):
        decode_qualification_consumer_v3(bad)


def test_legacy_readers_reject_new_consumers_and_unknown_discriminators():
    v, s, context = source_values()
    q = qualification(v)
    for obj in (q, signal(q, s, context)):
        with pytest.raises(LineageError):
            encode(obj)
        doc = encode_qualification_consumer_v3(obj)
        with pytest.raises(LineageError):
            decode(doc)
        with pytest.raises(SignalCodecError):
            decode_signal_contract(doc)
    with pytest.raises(ValueError):
        decode_qualification_consumer_v3(" " * (MAX_DOCUMENT_BYTES + 1))
    with pytest.raises(ValueError):
        decode_qualification_consumer_v3('{"contract_id":"C-999"}')


def test_context_document_keeps_typed_discriminators_and_rejects_tampering():
    v, s, context = source_values()
    out = signal(qualification(v), s, context)
    assert out.market_context == context
    stored = json.loads(out.market_context_document)
    assert stored["contract_id"] == "C-006"
    assert stored["schema_version"] == "5"
    assert all("assessment_contract_id" in x for x in stored["payload"]["assessments"])
    for document in (
        out.market_context_document.replace(
            '"schema_version":"5"', '"schema_version":"4"', 1
        ),
        json.dumps(stored, indent=2),
    ):
        with pytest.raises(ValueError):
            replace(out, market_context_document=document)
