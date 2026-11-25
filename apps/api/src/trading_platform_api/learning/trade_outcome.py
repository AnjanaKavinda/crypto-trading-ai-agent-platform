"""C-108v1: owner-reported Spot trade outcome linked to one C-107 journal entry.

The owner enters fills and fees from an exchange statement (or an estimate);
the platform derives position status, gross, fees and net result with exact
Decimal arithmetic. Facts stay owner-reported: nothing here is verified against
an exchange and nothing grants trading, approval or learning authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime
from decimal import Decimal, Inexact, localcontext
from typing import Callable, TypeVar
from uuid import UUID, uuid5

from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.learning.decision_journal import utc
from trading_platform_api.strategy.contracts import VersionReference

T = TypeVar("T")
OUTCOME_NAMESPACE = UUID("5d0a3f46-9a3c-5b8e-8f43-2e1c7b9d0c18")
FEE_SOURCES = ("STATEMENT", "ESTIMATE", "UNKNOWN")
SIDES = ("BUY", "SELL")
MAX_FILLS = 100
# Bounded inputs keep every product exact under the local Decimal context.
MAX_INTEGER_DIGITS = 15
MAX_FRACTION_DIGITS = 18


def bounded_decimal(name: str, value: Decimal, *, allow_zero: bool) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError(f"{name} must be a finite Decimal.")
    if value < 0 or (value == 0 and not allow_zero):
        raise ValueError(f"{name} must be positive.")
    sign, digits, exponent = value.normalize().as_tuple()
    assert isinstance(exponent, int)
    fraction = max(0, -exponent)
    integer = max(0, len(digits) + exponent)
    if fraction > MAX_FRACTION_DIGITS or integer > MAX_INTEGER_DIGITS:
        raise ValueError(f"{name} exceeds the supported precision.")
    return value


def exact(operation: Callable[[], T]) -> T:
    with localcontext() as context:
        context.prec = 200
        context.traps[Inexact] = True
        return operation()


@dataclass(frozen=True, slots=True)
class OwnerFill:
    side: str
    quantity: Decimal
    price_usdt: Decimal
    executed_at: datetime
    fee_source: str
    fee_usdt: Decimal | None

    def __post_init__(self) -> None:
        if self.side not in SIDES:
            raise ValueError("Fill side must be BUY or SELL.")
        bounded_decimal("quantity", self.quantity, allow_zero=False)
        bounded_decimal("price_usdt", self.price_usdt, allow_zero=False)
        object.__setattr__(self, "executed_at", utc(self.executed_at))
        if self.fee_source not in FEE_SOURCES:
            raise ValueError("Fee source must be STATEMENT, ESTIMATE or UNKNOWN.")
        if (self.fee_source == "UNKNOWN") != (self.fee_usdt is None):
            raise ValueError("Unknown fees have no amount; known fees need one.")
        if self.fee_usdt is not None:
            bounded_decimal("fee_usdt", self.fee_usdt, allow_zero=True)


@dataclass(frozen=True, slots=True)
class OwnerTradeOutcome:
    request_id: UUID
    request_sha256: str
    journal_entry: VersionReference
    journal_recorded_at: datetime
    instrument_id: str
    fills: tuple[OwnerFill, ...]
    recorded_at: datetime
    note: str = ""
    supersedes: VersionReference | None = None
    correction_reason: str | None = None
    position_status: str = field(init=False)
    bought_quantity: Decimal = field(init=False)
    sold_quantity: Decimal = field(init=False)
    gross_result_usdt: Decimal | None = field(init=False)
    total_fees_usdt: Decimal | None = field(init=False)
    net_result_usdt: Decimal | None = field(init=False)
    net_result_basis: str = field(init=False)
    net_result_reason: str | None = field(init=False)
    decision_recorded_before_first_fill: bool = field(init=False)
    outcome_id: UUID = field(init=False)
    content_sha256: str = field(init=False)
    contract_id: str = field(default="C-108", init=False)
    schema_version: str = field(default="1", init=False)
    profile: str = field(default="PERSONAL_SPOT_RESEARCH", init=False)
    operating_mode: str = field(default="RESEARCH", init=False)
    origin: str = field(default="LOCAL_OWNER_REPORT", init=False)
    identity_assurance: str = field(default="LOCAL_SESSION_UNAUTHENTICATED", init=False)
    trade_facts_verified: bool = field(default=False, init=False)
    approval_authorized: bool = field(default=False, init=False)
    execution_authorized: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        VersionReference("request", self.request_id, "1", self.request_sha256)
        if type(self.journal_entry) is not VersionReference or (
            self.journal_entry.artifact_type,
            self.journal_entry.version,
        ) != ("C-107", "1"):
            raise ValueError("An exact C-107v1 journal entry is required.")
        if type(self.instrument_id) is not str or not self.instrument_id:
            raise ValueError("Instrument is required.")
        for name in ("journal_recorded_at", "recorded_at"):
            object.__setattr__(self, name, utc(getattr(self, name)))
        fills = self.fills
        if (
            type(fills) is not tuple
            or not 1 <= len(fills) <= MAX_FILLS
            or any(type(fill) is not OwnerFill for fill in fills)
        ):
            raise ValueError("Between 1 and 100 fills are required.")
        if any(a.executed_at > b.executed_at for a, b in zip(fills, fills[1:])):
            raise ValueError("Fills must be in execution-time order.")
        if fills[-1].executed_at > self.recorded_at:
            raise ValueError("Future fill or reversed server clock.")
        if self.journal_recorded_at > self.recorded_at:
            raise ValueError("Journal entry is newer than the outcome record.")
        if type(self.note) is not str or len(self.note) > 2000:
            raise ValueError("Note must be plain text of at most 2000 characters.")
        if (self.supersedes is None) != (self.correction_reason is None):
            raise ValueError("Correction reference and reason must both be supplied.")
        if self.supersedes is not None:
            if type(self.supersedes) is not VersionReference or (
                self.supersedes.artifact_type,
                self.supersedes.version,
            ) != ("C-108", "1"):
                raise ValueError("Invalid correction parent.")
            if (
                type(self.correction_reason) is not str
                or not self.correction_reason.strip()
                or len(self.correction_reason) > 2000
            ):
                raise ValueError("Correction reason is required and bounded.")
        for name, value in summarise_fills(fills).items():
            object.__setattr__(self, name, value)
        object.__setattr__(
            self,
            "decision_recorded_before_first_fill",
            self.journal_recorded_at <= fills[0].executed_at,
        )
        # Identity follows the owner's request key, so a retry finds the same
        # record; the content digest still covers every fact.
        object.__setattr__(
            self,
            "outcome_id",
            uuid5(OUTCOME_NAMESPACE, "C-108:1:" + str(self.request_id)),
        )
        material = {
            f.name: getattr(self, f.name)
            for f in fields(self)
            if f.name not in {"outcome_id", "content_sha256"}
        }
        object.__setattr__(self, "content_sha256", canonical_sha256(material))


def summarise_fills(fills: tuple[OwnerFill, ...]) -> dict[str, object]:
    """Long-only Spot arithmetic; the position may never go below zero."""

    def compute() -> dict[str, object]:
        position = Decimal(0)
        bought = sold = Decimal(0)
        spent = received = Decimal(0)
        for fill in fills:
            notional = fill.quantity * fill.price_usdt
            if fill.side == "BUY":
                position += fill.quantity
                bought += fill.quantity
                spent += notional
            else:
                if fill.quantity > position:
                    raise ValueError("Spot sell exceeds the bought quantity.")
                position -= fill.quantity
                sold += fill.quantity
                received += notional
        fees: Decimal | None = Decimal(0)
        for fill in fills:
            fees = (
                None if fees is None or fill.fee_usdt is None else fees + fill.fee_usdt
            )
        closed = position == 0
        gross = received - spent if closed else None
        if not closed:
            reason: str | None = "POSITION_OPEN"
        elif fees is None:
            reason = "FEE_UNKNOWN"
        else:
            reason = None
        net = gross - fees if gross is not None and fees is not None else None
        if net is None:
            basis = "UNAVAILABLE"
        elif all(fill.fee_source == "STATEMENT" for fill in fills):
            basis = "STATEMENT_FEES"
        else:
            basis = "INCLUDES_ESTIMATED_FEES"
        return {
            "position_status": "CLOSED" if closed else "OPEN",
            "bought_quantity": bought,
            "sold_quantity": sold,
            "gross_result_usdt": gross,
            "total_fees_usdt": fees,
            "net_result_usdt": net,
            "net_result_basis": basis,
            "net_result_reason": reason,
        }

    if not fills or fills[0].side != "BUY":
        raise ValueError("A Spot trade starts with a BUY fill.")
    return exact(compute)
