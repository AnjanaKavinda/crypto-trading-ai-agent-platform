"""Focused C-107 identity, closed input and local admission checks."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from trading_platform_api.config import (
    AppSettings,
    DeploymentEnvironment,
    OperatingMode,
)
from trading_platform_api.journal_api import JournalRequest, SnapshotJournalRequest
from trading_platform_api.learning.decision_journal import (
    ResearchDecisionJournalEntry,
    SnapshotDecisionJournalEntry,
    SnapshotObservation,
    SourceObservation,
)
from trading_platform_api.lineage.codec import LineageError, decode, encode
from trading_platform_api.main import create_app
from trading_platform_api.strategy.contracts import VersionReference

NOW = datetime(2026, 11, 25, tzinfo=UTC)
ORIGIN = "http://127.0.0.1:5173"


def entry():
    return ResearchDecisionJournalEntry(
        uuid4(),
        "a" * 64,
        VersionReference("C-026", uuid4(), "2", "b" * 64),
        VersionReference("C-006", uuid4(), "5", "c" * 64),
        SourceObservation(
            "NO_TRADE",
            ("MISSING_DATA",),
            NOW - timedelta(hours=2),
            NOW - timedelta(hours=1),
            None,
        ),
        "ABSTAIN",
        NOW,
        NOW,
    )


def body():
    return {
        "request_id": str(uuid4()),
        "source": {
            "contract_id": "C-026",
            "artifact_id": str(uuid4()),
            "schema_version": "2",
            "content_sha256": "b" * 64,
        },
        "declared_action": "ABSTAIN",
        "declared_at": NOW.isoformat(),
    }


def client(mode=OperatingMode.RESEARCH):
    return TestClient(
        create_app(
            settings=AppSettings(DeploymentEnvironment.TEST, mode),
            allowed_origin=ORIGIN,
        )
    )


def test_closed_codec_identity_authority_and_expired_source():
    value = entry()
    assert decode(encode(value)) == value
    assert value.entry_id.version == 5
    assert not any(
        (
            value.execution_authorized,
            value.approval_authorized,
            value.qualification_authorized,
            value.trade_facts_verified,
        )
    )
    assert replace(value, note="changed").entry_id != value.entry_id
    for mutate in [
        lambda x: x["payload"].update(execution_authorized=True),
        lambda x: x["payload"].update(extra="invalid"),
        lambda x: x.update(schema_version="2"),
        lambda x: x["payload"].update(content_sha256="f" * 64),
    ]:
        document = json.loads(encode(value))
        mutate(document)
        with pytest.raises(LineageError):
            decode(json.dumps(document))
    for changes in [
        {"declared_at": NOW + timedelta(seconds=1)},
        {"declared_action": "EXECUTE"},
        {"note": "x" * 2001},
        {"supersedes": VersionReference("C-107", uuid4(), "1", "a" * 64)},
    ]:
        with pytest.raises(ValueError):
            replace(value, **changes)


def test_request_normalization_and_closed_fields():
    data = body()
    request = JournalRequest.model_validate(data)
    equivalent = {
        **data,
        "declared_at": NOW.astimezone().isoformat(),
        "note": "",
        "supersedes": None,
        "correction_reason": None,
    }
    assert request.digest() == JournalRequest.model_validate(equivalent).digest()
    for extra in [
        {"recorded_at": NOW.isoformat()},
        {"execution_authorized": True},
        {"market_context": data["source"]},
        {"declared_at": "2026-11-25T00:00:00"},
        {"declared_action": "APPROVE"},
        {"note": "x" * 2001},
    ]:
        with pytest.raises(ValueError):
            JournalRequest.model_validate({**data, **extra})


def test_local_write_admission_body_bound_and_no_store():
    with client() as c:
        path = "/api/research/decision-journal"
        for headers, payload, status in [
            ({}, body(), 403),
            ({"Origin": "http://evil.example"}, body(), 403),
            ({"Origin": ORIGIN}, {**body(), "execution_authorized": True}, 422),
        ]:
            r = c.post(path, json=payload, headers=headers)
            assert r.status_code == status, r.text
            assert r.headers["cache-control"] == "no-store"
        assert (
            c.post(path, content="text", headers={"Origin": ORIGIN}).status_code == 415
        )
        assert (
            c.post(
                path,
                content=" " * 16385,
                headers={"Origin": ORIGIN, "Content-Type": "application/json"},
            ).status_code
            == 413
        )
        assert c.post(path, json=body(), headers={"Origin": ORIGIN}).status_code == 503
        assert c.get(path + "?limit=101").status_code == 422
        assert (
            c.get(
                path
                + "/"
                + str(uuid4())
                + "?schema_version=2&content_sha256="
                + "a" * 64
            ).status_code
            == 422
        )
    with client(OperatingMode.PAPER) as c:
        assert c.post(path, json=body(), headers={"Origin": ORIGIN}).status_code == 403


# --- C-107v2: declarations against the viewed snapshot (E2c2) ---------------
# Synthetic identifiers and digests only; no market data is fabricated here.


def snapshot_entry(**changes):
    values = dict(
        request_id=uuid4(),
        request_sha256="a" * 64,
        source=VersionReference("C-002", uuid4(), "1", "b" * 64),
        quality_report=VersionReference("C-003", uuid4(), "1", "c" * 64),
        snapshot_observation=SnapshotObservation(
            instrument_id="BTC-USDT-SPOT",
            timeframe="4h",
            as_of=NOW - timedelta(hours=1),
            last_candle_open_time=NOW - timedelta(hours=5),
            candle_count=50,
            fresh_until=NOW + timedelta(hours=3),
        ),
        declared_action="ABSTAIN",
        declared_at=NOW,
        recorded_at=NOW,
    )
    values.update(changes)
    return SnapshotDecisionJournalEntry(**values)


def snapshot_body(**changes):
    value = {
        "request_id": str(uuid4()),
        "instrument_id": "BTC-USDT-SPOT",
        "timeframe": "4h",
        "snapshot_id": str(uuid4()),
        "quality_report_id": str(uuid4()),
        "declared_action": "EXTERNAL_TRADE_INTENT",
        "declared_at": NOW.isoformat(),
    }
    value.update(changes)
    return value


def test_snapshot_entry_codec_identity_and_fail_closed_rules():
    value = snapshot_entry()
    assert decode(encode(value)) == value
    assert (value.contract_id, value.schema_version) == ("C-107", "2")
    assert value.snapshot_observation.quality_status == "VALID"
    assert value.entry_id.version == 5
    assert value.entry_id != replace(value, note="changed").entry_id
    assert not any(
        (
            value.execution_authorized,
            value.approval_authorized,
            value.qualification_authorized,
            value.trade_facts_verified,
        )
    )
    for mutate in [
        lambda x: x["payload"].update(execution_authorized=True),
        lambda x: x["payload"]["snapshot_observation"].update(quality_status="STALE"),
        lambda x: x.update(schema_version="3"),
        lambda x: x["payload"].update(content_sha256="f" * 64),
    ]:
        document = json.loads(encode(value))
        mutate(document)
        with pytest.raises(LineageError):
            decode(json.dumps(document))
    # Recorded after the snapshot went stale, future declaration, wrong
    # source/report contracts, v1 correction parent, unsupported action.
    for changes in [
        {"recorded_at": NOW + timedelta(hours=3, seconds=1)},
        {"declared_at": NOW + timedelta(seconds=1)},
        {"source": VersionReference("C-026", uuid4(), "2", "b" * 64)},
        {"quality_report": VersionReference("C-003", uuid4(), "2", "c" * 64)},
        {
            "supersedes": VersionReference("C-107", uuid4(), "1", "a" * 64),
            "correction_reason": "fix",
        },
        {"supersedes": VersionReference("C-107", uuid4(), "2", "a" * 64)},
        {"declared_action": "EXECUTE"},
    ]:
        with pytest.raises(ValueError):
            snapshot_entry(**changes)
    with pytest.raises(ValueError):
        SnapshotObservation("BTC-USDT-SPOT", "2h", NOW, NOW, 50, NOW)
    # Exactly at the freshness boundary is still fresh (same rule as STALE).
    assert snapshot_entry(recorded_at=NOW + timedelta(hours=3))


def test_snapshot_request_is_closed_and_server_owns_resolution():
    request = SnapshotJournalRequest.model_validate(snapshot_body())
    assert (
        request.digest()
        == SnapshotJournalRequest.model_validate(
            snapshot_body(
                request_id=str(request.request_id),
                snapshot_id=str(request.snapshot_id),
                quality_report_id=str(request.quality_report_id),
                declared_at=NOW.astimezone().isoformat(),
                note="",
                supersedes=None,
                correction_reason=None,
            )
        ).digest()
    )
    for changes in [
        {"recorded_at": NOW.isoformat()},
        {"content_sha256": "b" * 64},
        {"timeframe": "2h"},
        {"instrument_id": "DOGE-USDT-SPOT"},
        {"declared_action": "APPROVE"},
        {
            "supersedes": {
                "contract_id": "C-107",
                "artifact_id": str(uuid4()),
                "schema_version": "1",
                "content_sha256": "a" * 64,
            },
            "correction_reason": "fix",
        },
    ]:
        with pytest.raises(ValueError):
            SnapshotJournalRequest.model_validate(snapshot_body(**changes))


def test_snapshot_write_admission_and_schema_reads():
    path = "/api/research/decision-journal"
    with client() as c:
        assert c.post(path, json=snapshot_body()).status_code == 403
        r = c.post(
            path,
            json=snapshot_body(execution_authorized=True),
            headers={"Origin": ORIGIN},
        )
        assert r.status_code == 422 and r.headers["cache-control"] == "no-store"
        assert (
            c.post(path, json=snapshot_body(), headers={"Origin": ORIGIN}).status_code
            == 503
        )
        assert (
            c.get(
                f"{path}/{uuid4()}?schema_version=3&content_sha256={'a' * 64}"
            ).status_code
            == 422
        )
