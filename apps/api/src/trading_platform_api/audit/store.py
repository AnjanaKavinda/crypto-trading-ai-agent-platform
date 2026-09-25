from __future__ import annotations

from typing import Protocol

from trading_platform_api.audit.models import AuditEvent
from trading_platform_api.audit.table import AuditEventRow


class AuditSession(Protocol):
    def add(self, instance: object) -> None: ...

    async def flush(self) -> None: ...


class AuditEventStore(Protocol):
    async def append(self, event: AuditEvent) -> None: ...


class SqlAlchemyAuditEventStore:
    def __init__(self, session: AuditSession) -> None:
        self._session = session

    async def append(self, event: AuditEvent) -> None:
        if not isinstance(event, AuditEvent):
            raise TypeError("event must be a validated AuditEvent.")
        self._session.add(AuditEventRow.from_event(event))
        await self._session.flush()
