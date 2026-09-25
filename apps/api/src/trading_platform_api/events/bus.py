from __future__ import annotations

from typing import Protocol, TypeVar, runtime_checkable

from trading_platform_api.events.models import EventEnvelope


PayloadT = TypeVar("PayloadT")


@runtime_checkable
class EventPublisher(Protocol[PayloadT]):
    async def publish(self, event: EventEnvelope[PayloadT]) -> None: ...


@runtime_checkable
class EventConsumer(Protocol[PayloadT]):
    async def consume(self, event: EventEnvelope[PayloadT]) -> None: ...
