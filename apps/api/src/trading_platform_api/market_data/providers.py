from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from trading_platform_api.market_data.contracts import (
    DatasetVersion,
    DataSourceRecord,
    MarketData,
    MarketSnapshot,
)


class ProviderContractError(ValueError):
    """Raised when provider-boundary metadata is structurally invalid."""


class ProviderDataKind(StrEnum):
    OHLCV = "OHLCV"
    TRADE = "TRADE"
    TICK = "TICK"
    ORDER_BOOK = "ORDER_BOOK"
    FUNDING = "FUNDING"
    OPEN_INTEREST = "OPEN_INTEREST"
    LIQUIDATION = "LIQUIDATION"
    DERIVATIVES = "DERIVATIVES"
    ON_CHAIN = "ON_CHAIN"
    FUNDAMENTAL = "FUNDAMENTAL"
    NEWS = "NEWS"
    SENTIMENT = "SENTIMENT"
    MACRO = "MACRO"


class CapabilitySupport(StrEnum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


class AuthenticationRequirement(StrEnum):
    NONE = "NONE"
    API_KEY = "API_KEY"  # pragma: allowlist secret
    OAUTH2 = "OAUTH2"
    SIGNED_REQUEST = "SIGNED_REQUEST"
    UNKNOWN = "UNKNOWN"


class ProviderAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class ProviderBatchStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    EMPTY = "EMPTY"
    STALE = "STALE"


class RateLimitKnowledge(StrEnum):
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ProviderFailureCode(StrEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    UNSUPPORTED_CAPABILITY = "UNSUPPORTED_CAPABILITY"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    UNAVAILABLE = "UNAVAILABLE"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    AUTHORIZATION_FAILED = "AUTHORIZATION_FAILED"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    STALE_RESPONSE = "STALE_RESPONSE"
    LICENSING_RESTRICTED = "LICENSING_RESTRICTED"
    UNKNOWN = "UNKNOWN"


MAX_PROVIDER_TEXT_LENGTH = 512
MAX_REQUEST_RECORDS = 100_000
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)(api[-_ ]?key|authorization|password|secret|token)\s*[:=]"
)
_BEARER_VALUE = re.compile(r"(?i)\bbearer\s+\S+")
_URI_USERINFO = re.compile(r"://[^/\s:@]+:[^/\s@]+@")


def _text(field_name: str, value: object, *, maximum: int = 255) -> str:
    if not isinstance(value, str):
        raise ProviderContractError(f"{field_name} must be a string.")
    if not value.strip():
        raise ProviderContractError(f"{field_name} must not be blank.")
    if value != value.strip():
        raise ProviderContractError(
            f"{field_name} must not contain surrounding whitespace."
        )
    if len(value) > maximum:
        raise ProviderContractError(
            f"{field_name} must not exceed {maximum} characters."
        )
    if any(ord(character) < 32 for character in value):
        raise ProviderContractError(f"{field_name} must not contain control text.")
    return value


def _safe_detail(field_name: str, value: object) -> str:
    detail = _text(field_name, value, maximum=MAX_PROVIDER_TEXT_LENGTH)
    if (
        _SENSITIVE_ASSIGNMENT.search(detail)
        or _BEARER_VALUE.search(detail)
        or _URI_USERINFO.search(detail)
    ):
        raise ProviderContractError(f"{field_name} must not contain sensitive data.")
    return detail


def _positive_int(field_name: str, value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ProviderContractError(f"{field_name} must be a positive integer.")
    return value


def _non_negative_int(field_name: str, value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ProviderContractError(f"{field_name} must be a non-negative integer.")
    return value


def _utc(field_name: str, value: object) -> datetime:
    if not isinstance(value, datetime):
        raise ProviderContractError(f"{field_name} must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProviderContractError(f"{field_name} must be timezone-aware.")
    return value.astimezone(UTC)


def _uuid(field_name: str, value: object) -> UUID:
    if not isinstance(value, UUID):
        raise ProviderContractError(f"{field_name} must be a UUID.")
    return value


def _tuple(field_name: str, value: object) -> tuple[object, ...]:
    if not isinstance(value, tuple):
        raise ProviderContractError(f"{field_name} must be a tuple.")
    return value


def _text_tuple(field_name: str, value: object) -> tuple[str, ...]:
    items = _tuple(field_name, value)
    result = tuple(
        _text(f"{field_name}[{index}]", item) for index, item in enumerate(items)
    )
    if len(set(result)) != len(result):
        raise ProviderContractError(f"{field_name} must not contain duplicates.")
    return result


def _unique(field_name: str, values: tuple[object, ...]) -> None:
    if len(set(values)) != len(values):
        raise ProviderContractError(f"{field_name} must not contain duplicates.")


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    knowledge: RateLimitKnowledge
    window_seconds: int | None = None
    maximum_requests: int | None = None
    burst_limit: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.knowledge, RateLimitKnowledge):
            raise ProviderContractError("knowledge must be a RateLimitKnowledge value.")
        values = (self.window_seconds, self.maximum_requests, self.burst_limit)
        if self.knowledge is RateLimitKnowledge.KNOWN:
            if any(value is None for value in values):
                raise ProviderContractError(
                    "Known rate limits require window, maximum and burst values."
                )
            window_seconds = self.window_seconds
            maximum_requests = self.maximum_requests
            burst_limit = self.burst_limit
            assert window_seconds is not None
            assert maximum_requests is not None
            assert burst_limit is not None
            _positive_int("window_seconds", window_seconds)
            _positive_int("maximum_requests", maximum_requests)
            _positive_int("burst_limit", burst_limit)
            if burst_limit > maximum_requests:
                raise ProviderContractError(
                    "burst_limit must not exceed maximum_requests."
                )
        elif any(value is not None for value in values):
            raise ProviderContractError(
                "Unknown or inapplicable rate limits must not invent values."
            )


@dataclass(frozen=True, slots=True)
class ProviderCapability:
    data_kind: ProviderDataKind
    support: CapabilitySupport
    historical_support: CapabilitySupport
    realtime_support: CapabilitySupport
    rate_limit: RateLimitPolicy
    market_types: tuple[str, ...] = ()
    asset_ids: tuple[str, ...] = ()
    instrument_ids: tuple[str, ...] = ()
    freshness_target_seconds: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.data_kind, ProviderDataKind):
            raise ProviderContractError("data_kind must be a ProviderDataKind value.")
        for field_name in ("support", "historical_support", "realtime_support"):
            if not isinstance(getattr(self, field_name), CapabilitySupport):
                raise ProviderContractError(
                    f"{field_name} must be a CapabilitySupport value."
                )
        if not isinstance(self.rate_limit, RateLimitPolicy):
            raise ProviderContractError("rate_limit must be a RateLimitPolicy.")
        for field_name in ("market_types", "asset_ids", "instrument_ids"):
            _text_tuple(field_name, getattr(self, field_name))
        if self.freshness_target_seconds is not None:
            _positive_int("freshness_target_seconds", self.freshness_target_seconds)

        detail_present = any(
            (
                self.market_types,
                self.asset_ids,
                self.instrument_ids,
                self.freshness_target_seconds is not None,
                self.rate_limit.knowledge is RateLimitKnowledge.KNOWN,
            )
        )
        if self.support is CapabilitySupport.UNSUPPORTED:
            if (
                self.historical_support is not CapabilitySupport.UNSUPPORTED
                or self.realtime_support is not CapabilitySupport.UNSUPPORTED
                or detail_present
            ):
                raise ProviderContractError(
                    "Unsupported capability must not contain support details."
                )
        elif self.support is CapabilitySupport.UNKNOWN:
            if (
                self.historical_support is not CapabilitySupport.UNKNOWN
                or self.realtime_support is not CapabilitySupport.UNKNOWN
                or detail_present
            ):
                raise ProviderContractError(
                    "Unknown capability must not contain support details."
                )
        elif not any(
            state is CapabilitySupport.SUPPORTED
            for state in (self.historical_support, self.realtime_support)
        ):
            raise ProviderContractError(
                "Supported capability requires historical or real-time support."
            )


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    provider_id: str
    provider_version: str
    provider_type: str
    availability: ProviderAvailability
    authentication: AuthenticationRequirement
    raw_schema_version: str
    adapter_version: str
    licensing_reference: str
    capabilities: tuple[ProviderCapability, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "provider_id",
            "provider_version",
            "provider_type",
            "raw_schema_version",
            "adapter_version",
        ):
            _text(field_name, getattr(self, field_name))
        _safe_detail("licensing_reference", self.licensing_reference)
        if not isinstance(self.availability, ProviderAvailability):
            raise ProviderContractError(
                "availability must be a ProviderAvailability value."
            )
        if not isinstance(self.authentication, AuthenticationRequirement):
            raise ProviderContractError(
                "authentication must be an AuthenticationRequirement value."
            )
        values = _tuple("capabilities", self.capabilities)
        if not values or not all(
            isinstance(item, ProviderCapability) for item in values
        ):
            raise ProviderContractError(
                "capabilities must contain ProviderCapability values."
            )
        _unique(
            "capability data kinds",
            tuple(item.data_kind for item in self.capabilities),
        )

    def capability(self, data_kind: ProviderDataKind) -> ProviderCapability | None:
        if not isinstance(data_kind, ProviderDataKind):
            raise ProviderContractError("data_kind must be a ProviderDataKind value.")
        return next(
            (item for item in self.capabilities if item.data_kind is data_kind), None
        )


@dataclass(frozen=True, slots=True)
class MarketDataRequest:
    request_id: UUID
    correlation_id: str
    data_kind: ProviderDataKind
    instrument_id: str
    venue_id: str
    requested_at: datetime
    as_of: datetime
    maximum_records: int
    range_start: datetime | None = None
    range_end: datetime | None = None

    def __post_init__(self) -> None:
        _uuid("request_id", self.request_id)
        _text("correlation_id", self.correlation_id, maximum=128)
        if not isinstance(self.data_kind, ProviderDataKind):
            raise ProviderContractError("data_kind must be a ProviderDataKind value.")
        _text("instrument_id", self.instrument_id)
        _text("venue_id", self.venue_id)
        requested_at = _utc("requested_at", self.requested_at)
        as_of = _utc("as_of", self.as_of)
        if as_of > requested_at:
            raise ProviderContractError("as_of must not be after requested_at.")
        maximum_records = _positive_int("maximum_records", self.maximum_records)
        if maximum_records > MAX_REQUEST_RECORDS:
            raise ProviderContractError(
                f"maximum_records must not exceed {MAX_REQUEST_RECORDS}."
            )
        if (self.range_start is None) != (self.range_end is None):
            raise ProviderContractError(
                "range_start and range_end must be supplied together."
            )
        range_start = self.range_start
        range_end = self.range_end
        if range_start is not None and range_end is not None:
            range_start = _utc("range_start", range_start)
            range_end = _utc("range_end", range_end)
            if range_start > range_end:
                raise ProviderContractError("range_start must not be after range_end.")
            if range_end > as_of:
                raise ProviderContractError("range_end must not be after as_of.")
            object.__setattr__(self, "range_start", range_start)
            object.__setattr__(self, "range_end", range_end)
        object.__setattr__(self, "requested_at", requested_at)
        object.__setattr__(self, "as_of", as_of)


@dataclass(frozen=True, slots=True)
class ProviderBatch:
    request_id: UUID
    provider_id: str
    provider_version: str
    data_kind: ProviderDataKind
    status: ProviderBatchStatus
    retrieved_at: datetime
    fresh_until: datetime
    source_records: tuple[DataSourceRecord, ...] = ()
    market_data: tuple[MarketData, ...] = ()
    snapshots: tuple[MarketSnapshot, ...] = ()
    datasets: tuple[DatasetVersion, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _uuid("request_id", self.request_id)
        _text("provider_id", self.provider_id)
        _text("provider_version", self.provider_version)
        if not isinstance(self.data_kind, ProviderDataKind):
            raise ProviderContractError("data_kind must be a ProviderDataKind value.")
        if not isinstance(self.status, ProviderBatchStatus):
            raise ProviderContractError("status must be a ProviderBatchStatus value.")
        retrieved_at = _utc("retrieved_at", self.retrieved_at)
        fresh_until = _utc("fresh_until", self.fresh_until)
        _text_tuple("warnings", self.warnings)

        typed_collections = (
            ("source_records", self.source_records, DataSourceRecord),
            ("market_data", self.market_data, MarketData),
            ("snapshots", self.snapshots, MarketSnapshot),
            ("datasets", self.datasets, DatasetVersion),
        )
        for field_name, values, expected_type in typed_collections:
            items = _tuple(field_name, values)
            if not all(type(item) is expected_type for item in items):
                raise ProviderContractError(
                    f"{field_name} must contain exact {expected_type.__name__} values."
                )

        _unique(
            "source record IDs",
            tuple(item.source_record_id for item in self.source_records),
        )
        _unique(
            "market data IDs",
            tuple(item.market_data_id for item in self.market_data),
        )
        _unique("snapshot IDs", tuple(item.snapshot_id for item in self.snapshots))
        _unique(
            "dataset identities",
            tuple((item.dataset_id, item.version) for item in self.datasets),
        )

        source_ids = {item.source_record_id for item in self.source_records}
        market_ids = {item.market_data_id for item in self.market_data}
        for source in self.source_records:
            if (
                source.provider_id != self.provider_id
                or source.provider_version != self.provider_version
            ):
                raise ProviderContractError(
                    "Every source record must match the batch provider identity."
                )
        for observation in self.market_data:
            if observation.source_record_id not in source_ids:
                raise ProviderContractError(
                    "Every market-data source must exist in source_records."
                )
            if observation.observation_type != self.data_kind.value:
                raise ProviderContractError(
                    "Market-data observation type must match data_kind."
                )
        for snapshot in self.snapshots:
            if not set(snapshot.source_record_ids).issubset(source_ids):
                raise ProviderContractError(
                    "Every snapshot source must exist in source_records."
                )
            if not set(snapshot.market_data_ids).issubset(market_ids):
                raise ProviderContractError(
                    "Every snapshot observation must exist in market_data."
                )
        for dataset in self.datasets:
            if not set(dataset.source_record_ids).issubset(source_ids):
                raise ProviderContractError(
                    "Every dataset source must exist in source_records."
                )

        has_payload = any(
            (self.source_records, self.market_data, self.snapshots, self.datasets)
        )
        has_data = any((self.market_data, self.snapshots, self.datasets))
        if self.status is ProviderBatchStatus.EMPTY and has_payload:
            raise ProviderContractError("EMPTY batch must not contain payload.")
        if self.status is not ProviderBatchStatus.EMPTY and not (
            self.source_records and has_data
        ):
            raise ProviderContractError(
                "Non-empty batch status requires canonical source evidence."
            )
        if self.status is ProviderBatchStatus.STALE:
            if fresh_until >= retrieved_at:
                raise ProviderContractError(
                    "STALE batch requires fresh_until before retrieved_at."
                )
        elif fresh_until < retrieved_at:
            raise ProviderContractError(
                "Fresh batch status cannot use an expired freshness boundary."
            )
        object.__setattr__(self, "retrieved_at", retrieved_at)
        object.__setattr__(self, "fresh_until", fresh_until)


class ProviderError(RuntimeError):
    """Sanitized provider failure; raw responses and credentials are forbidden."""

    def __init__(
        self,
        code: ProviderFailureCode,
        detail: str,
        *,
        retryable: bool,
        retry_after_seconds: int | None = None,
    ) -> None:
        if not isinstance(code, ProviderFailureCode):
            raise ProviderContractError("code must be a ProviderFailureCode value.")
        safe_detail = _safe_detail("detail", detail)
        if not isinstance(retryable, bool):
            raise ProviderContractError("retryable must be a boolean.")
        if retry_after_seconds is not None:
            _non_negative_int("retry_after_seconds", retry_after_seconds)
            if not retryable:
                raise ProviderContractError(
                    "retry_after_seconds requires retryable=true."
                )
        self.code = code
        self.detail = safe_detail
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"{code.value}: {safe_detail}")


@runtime_checkable
class MarketDataProvider(Protocol):
    @property
    def descriptor(self) -> ProviderDescriptor: ...

    async def fetch(self, request: MarketDataRequest) -> ProviderBatch: ...


@dataclass(frozen=True, slots=True)
class ProviderRegistry:
    providers: tuple[MarketDataProvider, ...] = ()

    def __post_init__(self) -> None:
        values = _tuple("providers", self.providers)
        if not all(isinstance(item, MarketDataProvider) for item in values):
            raise ProviderContractError(
                "providers must implement the MarketDataProvider protocol."
            )
        descriptors = tuple(item.descriptor for item in self.providers)
        if not all(isinstance(item, ProviderDescriptor) for item in descriptors):
            raise ProviderContractError(
                "Every provider must expose a ProviderDescriptor."
            )
        _unique("provider IDs", tuple(item.provider_id for item in descriptors))

    def require(self, provider_id: str) -> MarketDataProvider:
        normalized_id = _text("provider_id", provider_id)
        provider = next(
            (
                item
                for item in self.providers
                if item.descriptor.provider_id == normalized_id
            ),
            None,
        )
        if provider is None:
            raise ProviderError(
                ProviderFailureCode.UNSUPPORTED_CAPABILITY,
                "Requested provider is not registered.",
                retryable=False,
            )
        return provider

    def candidates(
        self,
        data_kind: ProviderDataKind,
        *,
        require_historical: bool = False,
        require_realtime: bool = False,
    ) -> tuple[MarketDataProvider, ...]:
        if not isinstance(data_kind, ProviderDataKind):
            raise ProviderContractError("data_kind must be a ProviderDataKind value.")
        if not isinstance(require_historical, bool) or not isinstance(
            require_realtime, bool
        ):
            raise ProviderContractError("capability requirements must be booleans.")

        matches: list[MarketDataProvider] = []
        for provider in self.providers:
            descriptor = provider.descriptor
            if descriptor.availability is not ProviderAvailability.AVAILABLE:
                continue
            capability = descriptor.capability(data_kind)
            if (
                capability is None
                or capability.support is not CapabilitySupport.SUPPORTED
            ):
                continue
            if require_historical and (
                capability.historical_support is not CapabilitySupport.SUPPORTED
            ):
                continue
            if require_realtime and (
                capability.realtime_support is not CapabilitySupport.SUPPORTED
            ):
                continue
            matches.append(provider)
        return tuple(sorted(matches, key=lambda item: item.descriptor.provider_id))


__all__ = [
    "AuthenticationRequirement",
    "CapabilitySupport",
    "MarketDataProvider",
    "MarketDataRequest",
    "ProviderAvailability",
    "ProviderBatch",
    "ProviderBatchStatus",
    "ProviderCapability",
    "ProviderContractError",
    "ProviderDataKind",
    "ProviderDescriptor",
    "ProviderError",
    "ProviderFailureCode",
    "ProviderRegistry",
    "RateLimitKnowledge",
    "RateLimitPolicy",
]
