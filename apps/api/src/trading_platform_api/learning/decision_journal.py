"""C-107v1: immutable local declarations, never factual trades or authority."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from uuid import UUID, uuid5

from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.strategy.contracts import VersionReference

JOURNAL_NAMESPACE = UUID("f137c4ec-dab8-5bdd-a1f7-c46721f9b7db")
SOURCE_SCHEMAS = {"C-026": "2", "C-023": "1", "C-070": "2"}


def utc(value: datetime) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Journal timestamps must be timezone-aware.")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class LifecyclePin:
    event_id: UUID
    content_sha256: str
    snapshot_version: str = field(default="1", init=False)

    def __post_init__(self) -> None:
        VersionReference(
            "lifecycle-event-snapshot", self.event_id, "1", self.content_sha256
        )


@dataclass(frozen=True, slots=True)
class SourceObservation:
    projection_state: str | None
    reasons: tuple[str, ...]
    occurred_at: datetime
    expires_at: datetime | None
    lifecycle_pin: LifecyclePin | None

    def __post_init__(self) -> None:
        if self.projection_state is not None and (
            type(self.projection_state) is not str
            or not 1 <= len(self.projection_state) <= 32
        ):
            raise ValueError("Invalid recorded projection.")
        if (
            type(self.reasons) is not tuple
            or len(self.reasons) > 32
            or any(type(v) is not str or not 1 <= len(v) <= 256 for v in self.reasons)
        ):
            raise ValueError("Invalid recorded reasons.")
        object.__setattr__(self, "occurred_at", utc(self.occurred_at))
        if self.expires_at is not None:
            object.__setattr__(self, "expires_at", utc(self.expires_at))
            if self.expires_at < self.occurred_at:
                raise ValueError("Source expiry precedes occurrence.")
        if (
            self.lifecycle_pin is not None
            and type(self.lifecycle_pin) is not LifecyclePin
        ):
            raise ValueError("Invalid lifecycle pin.")


@dataclass(frozen=True, slots=True)
class ResearchDecisionJournalEntry:
    request_id: UUID
    request_sha256: str
    source: VersionReference
    market_context: VersionReference
    source_observation: SourceObservation
    declared_action: str
    declared_at: datetime
    recorded_at: datetime
    note: str = ""
    supersedes: VersionReference | None = None
    correction_reason: str | None = None
    entry_id: UUID = field(init=False)
    content_sha256: str = field(init=False)
    contract_id: str = field(default="C-107", init=False)
    schema_version: str = field(default="1", init=False)
    profile: str = field(default="PERSONAL_SPOT_RESEARCH", init=False)
    operating_mode: str = field(default="RESEARCH", init=False)
    origin: str = field(default="LOCAL_USER_DECLARATION", init=False)
    identity_assurance: str = field(default="LOCAL_SESSION_UNAUTHENTICATED", init=False)
    qualification_authorized: bool = field(default=False, init=False)
    approval_authorized: bool = field(default=False, init=False)
    execution_authorized: bool = field(default=False, init=False)
    trade_facts_verified: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        VersionReference("request", self.request_id, "1", self.request_sha256)
        if (
            type(self.source) is not VersionReference
            or SOURCE_SCHEMAS.get(self.source.artifact_type) != self.source.version
        ):
            raise ValueError("Unsupported journal source.")
        if type(self.market_context) is not VersionReference or (
            self.market_context.artifact_type,
            self.market_context.version,
        ) != ("C-006", "5"):
            raise ValueError("Exact C-006v5 context required.")
        if type(self.source_observation) is not SourceObservation:
            raise ValueError("Invalid source observation.")
        if self.declared_action not in ("ABSTAIN", "EXTERNAL_TRADE_INTENT"):
            raise ValueError("Unsupported declaration action.")
        for name in ("declared_at", "recorded_at"):
            object.__setattr__(self, name, utc(getattr(self, name)))
        if (
            max(self.declared_at, self.source_observation.occurred_at)
            > self.recorded_at
        ):
            raise ValueError("Future declaration/source or reversed server clock.")
        if type(self.note) is not str or len(self.note) > 2000:
            raise ValueError("Note must be plain text of at most 2000 characters.")
        if (self.supersedes is None) != (self.correction_reason is None):
            raise ValueError("Correction reference and reason must both be supplied.")
        if self.supersedes is not None:
            if type(self.supersedes) is not VersionReference or (
                self.supersedes.artifact_type,
                self.supersedes.version,
            ) != ("C-107", "1"):
                raise ValueError("Invalid correction parent.")
            if (
                type(self.correction_reason) is not str
                or not self.correction_reason.strip()
                or len(self.correction_reason) > 2000
            ):
                raise ValueError("Correction reason is required and bounded.")
        material = {
            f.name: getattr(self, f.name)
            for f in fields(self)
            if f.name not in {"entry_id", "content_sha256"}
        }
        digest = canonical_sha256(material)
        object.__setattr__(self, "content_sha256", digest)
        object.__setattr__(
            self, "entry_id", uuid5(JOURNAL_NAMESPACE, "C-107:1:" + digest)
        )
