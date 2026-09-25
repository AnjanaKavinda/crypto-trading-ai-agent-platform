from __future__ import annotations

import asyncio

import pytest
from trading_platform_api.audit import (
    AuditEvent,
    AuditEventType,
    SqlAlchemyAuditEventStore,
)
from trading_platform_api.audit.table import AuditEventRow


def _event() -> AuditEvent:
    return AuditEvent(
        event_type=AuditEventType.SECURITY_EVENT,
        actor="safety-service",
        action="reject-transition",
        source="safety-control-plane",
        result="REJECTED",
        correlation_id="correlation-1",
        trace_id="trace-1",
        subject_type="StateTransition",
        subject_id="transition-1",
    )


class FakeSession:
    def __init__(
        self,
        *,
        add_error: BaseException | None = None,
        flush_error: BaseException | None = None,
    ) -> None:
        self.add_error = add_error
        self.flush_error = flush_error
        self.added: list[object] = []
        self.flush_count = 0
        self.commit_count = 0
        self.rollback_count = 0
        self.close_count = 0

    def add(self, instance: object) -> None:
        if self.add_error is not None:
            raise self.add_error
        self.added.append(instance)

    async def flush(self) -> None:
        self.flush_count += 1
        if self.flush_error is not None:
            raise self.flush_error


def test_append_adds_one_row_and_flushes_without_owning_transaction() -> None:
    session = FakeSession()
    event = _event()

    asyncio.run(SqlAlchemyAuditEventStore(session).append(event))

    assert len(session.added) == 1
    row = session.added[0]
    assert isinstance(row, AuditEventRow)
    assert row.audit_id == event.audit_id
    assert row.event_type == event.event_type.value
    assert row.correlation_id == event.correlation_id
    assert session.flush_count == 1
    assert session.commit_count == 0
    assert session.rollback_count == 0
    assert session.close_count == 0


@pytest.mark.parametrize("failure_stage", ["add", "flush"])
def test_append_failures_propagate_unchanged(failure_stage: str) -> None:
    original_error = RuntimeError(f"{failure_stage} failed")
    session = FakeSession(
        add_error=original_error if failure_stage == "add" else None,
        flush_error=original_error if failure_stage == "flush" else None,
    )

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(SqlAlchemyAuditEventStore(session).append(_event()))

    assert exc_info.value is original_error
    assert session.commit_count == 0
    assert session.rollback_count == 0
    assert session.close_count == 0


def test_store_rejects_unvalidated_input() -> None:
    session = FakeSession()
    with pytest.raises(TypeError, match="validated AuditEvent"):
        asyncio.run(SqlAlchemyAuditEventStore(session).append(object()))  # type: ignore[arg-type]
    assert session.added == []
    assert session.flush_count == 0


def test_store_surface_is_append_only() -> None:
    forbidden = {"update", "delete", "merge", "upsert", "overwrite"}
    store_attributes = {name.lower() for name in dir(SqlAlchemyAuditEventStore)}
    assert forbidden.isdisjoint(store_attributes)
