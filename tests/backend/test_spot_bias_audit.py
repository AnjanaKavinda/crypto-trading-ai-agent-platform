import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from trading_platform_api.lineage.codec import (
    LineageError,
    LineageKey,
    decode,
    encode,
    key_for,
)
from trading_platform_api.lineage.store import (
    LineageIntegrityError,
    SqlAlchemyLineageStore,
    references,
)
from trading_platform_api.validation.bias_contracts_v2 import (
    CHECK_TYPES,
    BiasAuditOutcomeV2,
    BiasCheckObservationV2,
    SpotBiasAuditResultV2,
)
from trading_platform_api.validation.contracts import CheckOutcome
from trading_platform_api.validation.contracts_v2 import ValidationArtifactReferenceV2
from trading_platform_api.validation.spot_bias_audit import run_spot_bias_audit

NOW = datetime(2026, 11, 15, 5, 0, tzinfo=UTC)
SHA = "a" * 64


def test_corrupt_persisted_lineage_document_is_an_integrity_failure() -> None:
    document = "{}"
    row = {
        "document": document,
        "document_sha256": sha256(document.encode()).hexdigest(),
    }

    async def execute(_statement):
        return SimpleNamespace(
            mappings=lambda: SimpleNamespace(one_or_none=lambda: row)
        )

    async def check() -> None:
        store = SqlAlchemyLineageStore(SimpleNamespace(execute=execute))
        with pytest.raises(LineageIntegrityError, match="document is invalid"):
            await store.get(LineageKey("C-103", SHA))

    asyncio.run(check())


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (
            LineageError("Exact lineage record is missing."),
            BiasAuditOutcomeV2.INCONCLUSIVE,
        ),
        (
            LineageIntegrityError("Stored document digest mismatch."),
            BiasAuditOutcomeV2.FAILED,
        ),
    ],
)
def test_wrapped_lineage_failure_preserves_integrity_classification(
    monkeypatch, error, outcome
) -> None:
    from test_spot_oos import case

    request, _, _, _ = case()

    async def resolve_unavailable(*args, **kwargs):
        raise error

    monkeypatch.setattr(SqlAlchemyLineageStore, "resolve", resolve_unavailable)

    async def check() -> None:
        async with AsyncSession() as session:
            result = await run_spot_bias_audit(
                request=request,
                session=session,
                strategy_registry=SimpleNamespace(resolve_version=resolve_unavailable),
                lineage_store=SqlAlchemyLineageStore(session),
                as_of=max(request.result_as_of, request.created_at),
                created_at=max(request.result_as_of, request.created_at),
            )
        assert result.outcome is outcome
        assert result.replay_result is None
        assert all(
            item.evidence_references == (result.request,) for item in result.checks
        )
        assert all(
            item.outcome is CheckOutcome.INCONCLUSIVE for item in result.checks[2:]
        )
        if outcome is BiasAuditOutcomeV2.FAILED:
            assert all(
                item.outcome is CheckOutcome.FAILED for item in result.checks[:2]
            )
            assert result.reasons[0] == "REPLAY_PIN_OR_PROVENANCE_MISMATCH"

    asyncio.run(check())


def _reference(kind: str, version: str) -> ValidationArtifactReferenceV2:
    identity = (
        uuid5(
            uuid5(
                NAMESPACE_URL,
                "trading-platform:C-094:2:spot-backtest-request-identity-v1",
            ),
            SHA,
        )
        if kind == "SPOT_BACKTEST_REQUEST"
        else uuid5(NAMESPACE_URL, f"{kind}:{version}")
    )
    return ValidationArtifactReferenceV2(kind, identity, version, SHA)


def _result() -> SpotBiasAuditResultV2:
    request = _reference("SPOT_BACKTEST_REQUEST", "1")
    checks = tuple(
        BiasCheckObservationV2(
            check_type,
            CheckOutcome.INCONCLUSIVE,
            "REPLAY_UNAVAILABLE",
            (request,),
        )
        for check_type in CHECK_TYPES
    )
    return SpotBiasAuditResultV2.build(
        outcome=BiasAuditOutcomeV2.INCONCLUSIVE,
        method="spot-bias-audit-observation-v1",
        method_version="1",
        request=request,
        replay_result=None,
        trace=None,
        strategy_version=_reference("C-021", "2"),
        dataset=None,
        dataset_id=None,
        dataset_version=None,
        dataset_lineage_sha256=None,
        universe=None,
        universe_id=None,
        universe_version=None,
        revisions=(),
        sources=(),
        manifest=None,
        request_as_of=NOW - timedelta(seconds=2),
        request_created_at=NOW - timedelta(seconds=1),
        request_expires_at=NOW + timedelta(hours=1),
        replay_as_of=None,
        replay_created_at=None,
        replay_expires_at=None,
        as_of=NOW,
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        checks=checks,
        reasons=("TRUSTED_REPLAY_UNAVAILABLE",),
    )


def test_schema_two_identity_and_closed_codec_are_deterministic() -> None:
    result = _result()

    assert result.result_id == _result().result_id
    assert result.schema_version == "2"
    assert tuple(item.check_type for item in result.checks) == CHECK_TYPES
    assert decode(encode(result)) == result
    assert key_for(result) == LineageKey("C-094", str(result.result_id), "2")
    with pytest.raises(LineageError, match="retention is not authorized"):
        references(result)


def test_schema_two_rejects_missing_or_duplicate_checks_and_unbound_pass() -> None:
    value = _result()
    with pytest.raises(ValueError, match="nine ordered checks"):
        replace(value, checks=value.checks[:-1])
    duplicated = (*value.checks[:-1], value.checks[0])
    with pytest.raises(ValueError, match="nine ordered checks"):
        replace(value, checks=duplicated)


@pytest.mark.parametrize("index", [0, 2])
@pytest.mark.parametrize(
    "reference_kind", ["missing", "unrelated", "extra", "reordered"]
)
def test_schema_two_rejects_unbound_inconclusive_check_evidence(
    index, reference_kind
) -> None:
    value = _result()
    unrelated = _reference("C-021", "2")
    references_by_kind = {
        "missing": (),
        "unrelated": (unrelated,),
        "extra": (value.request, unrelated),
        "reordered": (unrelated, value.request),
    }
    checks = list(value.checks)
    checks[index] = replace(
        checks[index], evidence_references=references_by_kind[reference_kind]
    )
    with pytest.raises(ValueError, match="exact available request/result/trace"):
        replace(value, checks=tuple(checks))


def test_schema_two_rejects_passing_replay_checks_without_result_pin() -> None:
    value = _result()
    checks = list(value.checks)
    checks[0] = replace(checks[0], outcome=CheckOutcome.PASSED)
    with pytest.raises(ValueError, match="cannot pass without replay"):
        SpotBiasAuditResultV2.build(
            outcome=BiasAuditOutcomeV2.INCONCLUSIVE,
            method=value.method,
            method_version=value.method_version,
            request=value.request,
            replay_result=None,
            trace=None,
            strategy_version=value.strategy_version,
            dataset=None,
            dataset_id=None,
            dataset_version=None,
            dataset_lineage_sha256=None,
            universe=None,
            universe_id=None,
            universe_version=None,
            revisions=(),
            sources=(),
            manifest=None,
            request_as_of=value.request_as_of,
            request_created_at=value.request_created_at,
            request_expires_at=value.request_expires_at,
            replay_as_of=None,
            replay_created_at=None,
            replay_expires_at=None,
            as_of=value.as_of,
            created_at=value.created_at,
            expires_at=value.expires_at,
            checks=tuple(checks),
            reasons=("UNSUPPORTED_CHECKS_REMAIN",),
        )
