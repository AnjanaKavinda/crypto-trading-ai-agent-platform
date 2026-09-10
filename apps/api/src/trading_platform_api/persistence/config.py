from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

DATABASE_URL_VARIABLE = "DATABASE_URL"
APPROVED_DATABASE_DRIVER = "postgresql+asyncpg"


class DatabaseSettingsError(ValueError):
    """Raised when database settings cannot be parsed safely."""


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    database_url: str = field(repr=False)
    drivername: str = field(default=APPROVED_DATABASE_DRIVER, init=False)

    def __repr__(self) -> str:
        return "DatabaseSettings(database_url='<redacted>', drivername='postgresql+asyncpg')"

    __str__ = __repr__


def _validated_database_url(raw_value: str | None) -> str:
    if raw_value is None:
        raise DatabaseSettingsError(
            f"{DATABASE_URL_VARIABLE} is required and must use the postgresql+asyncpg:// SQLAlchemy async dialect."
        )
    if raw_value == "":
        raise DatabaseSettingsError(f"{DATABASE_URL_VARIABLE} must not be blank.")
    if raw_value.strip() == "":
        raise DatabaseSettingsError(f"{DATABASE_URL_VARIABLE} must not be whitespace-only.")
    if raw_value != raw_value.strip():
        raise DatabaseSettingsError(
            f"{DATABASE_URL_VARIABLE} must match the canonical postgresql+asyncpg:// form with no surrounding whitespace."
        )

    try:
        parsed_url = make_url(raw_value)
    except ArgumentError:
        raise DatabaseSettingsError(
            f"{DATABASE_URL_VARIABLE} must be a valid postgresql+asyncpg:// SQLAlchemy URL."
        ) from None

    if parsed_url.drivername != APPROVED_DATABASE_DRIVER:
        if parsed_url.drivername == "postgresql":
            raise DatabaseSettingsError(
                f"{DATABASE_URL_VARIABLE} must use the postgresql+asyncpg:// SQLAlchemy async dialect."
            )
        if parsed_url.drivername.startswith("sqlite"):
            raise DatabaseSettingsError(
                f"{DATABASE_URL_VARIABLE} must use PostgreSQL via the postgresql+asyncpg:// SQLAlchemy async dialect."
            )
        raise DatabaseSettingsError(
            f"{DATABASE_URL_VARIABLE} must be a valid postgresql+asyncpg:// SQLAlchemy URL."
        )

    if parsed_url.host is None or not parsed_url.database:
        raise DatabaseSettingsError(
            f"{DATABASE_URL_VARIABLE} must include a PostgreSQL host and database name."
        )

    return raw_value


def load_database_settings(environment_mapping: Mapping[str, str] | None = None) -> DatabaseSettings:
    mapping = os.environ if environment_mapping is None else environment_mapping
    return DatabaseSettings(database_url=_validated_database_url(mapping.get(DATABASE_URL_VARIABLE)))
