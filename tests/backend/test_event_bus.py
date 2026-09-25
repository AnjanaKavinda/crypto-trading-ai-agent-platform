from __future__ import annotations

import asyncio
import inspect
from typing import get_type_hints
from uuid import uuid4

import pytest
from trading_platform_api.config import DeploymentEnvironment, OperatingMode
from trading_platform_api.events import (
    AggregateReference,
    DataClassification,
    EventConsumer,
    EventEnvelope,
    EventPublisher,
)


def _envelope() -> EventEnvelope[dict[str, str]]:
    return EventEnvelope(
        event_type="MarketSnapshotCreated",
        correlation_id="correlation-1",
        causation_id="request-1",
        producer="data-service",
        producer_version="build-1",
        environment=DeploymentEnvironment.TEST,
        mode=OperatingMode.RESEARCH,
        aggregate_ref=AggregateReference("C-002", "BTC-USD:1m"),
        payload_contract_id="C-002",
        payload_contract_version="1",
        audit_ref=uuid4(),
        data_classification=DataClassification.INTERNAL,
        idempotency_key="market-snapshot:BTC-USD:1m:1",
        payload={"snapshot_id": "snapshot-1"},
    )


class RecordingPublisher:
    def __init__(self) -> None:
        self.received: object | None = None

    async def publish(self, event: EventEnvelope[dict[str, str]]) -> None:
        self.received = event


class RecordingConsumer:
    def __init__(self) -> None:
        self.received: object | None = None

    async def consume(self, event: EventEnvelope[dict[str, str]]) -> None:
        self.received = event


class FailingPublisher:
    async def publish(self, event: EventEnvelope[dict[str, str]]) -> None:
        raise RuntimeError("publish failed")


class FailingConsumer:
    async def consume(self, event: EventEnvelope[dict[str, str]]) -> None:
        raise RuntimeError("consume failed")


def test_protocols_expose_exactly_one_public_operation() -> None:
    publisher_operations = {
        name for name in EventPublisher.__dict__ if not name.startswith("_")
    }
    consumer_operations = {
        name for name in EventConsumer.__dict__ if not name.startswith("_")
    }

    assert publisher_operations == {"publish"}
    assert consumer_operations == {"consume"}
    assert inspect.iscoroutinefunction(EventPublisher.publish)
    assert inspect.iscoroutinefunction(EventConsumer.consume)
    assert get_type_hints(EventPublisher.publish)["return"] is type(None)
    assert get_type_hints(EventConsumer.consume)["return"] is type(None)


def test_conforming_fakes_receive_the_same_validated_envelope() -> None:
    envelope = _envelope()
    publisher = RecordingPublisher()
    consumer = RecordingConsumer()

    assert isinstance(publisher, EventPublisher)
    assert isinstance(consumer, EventConsumer)

    asyncio.run(publisher.publish(envelope))
    asyncio.run(consumer.consume(envelope))

    assert publisher.received is envelope
    assert consumer.received is envelope


def test_publisher_failure_propagates_unchanged() -> None:
    with pytest.raises(RuntimeError, match="publish failed"):
        asyncio.run(FailingPublisher().publish(_envelope()))


def test_consumer_failure_propagates_unchanged() -> None:
    with pytest.raises(RuntimeError, match="consume failed"):
        asyncio.run(FailingConsumer().consume(_envelope()))
