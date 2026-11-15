from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

import pytest
from trading_platform_api.lineage.codec import (
    LineageError,
    LineageKey,
    decode,
    encode,
    key_for,
)
from trading_platform_api.lineage.store import references
from trading_platform_api.validation.bias_contracts_v2 import (
    CHECK_TYPES,
    BiasAuditOutcomeV2,
    BiasCheckObservationV2,
    SpotBiasAuditResultV2,
)
from trading_platform_api.validation.contracts import CheckOutcome
from trading_platform_api.validation.contracts_v2 import ValidationArtifactReferenceV2

NOW = datetime(2026, 11, 15, 5, 0, tzinfo=UTC)
SHA = "a" * 64


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
    return ValidationArtifactReferenceV2(
        kind, identity, version, SHA
    )


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
