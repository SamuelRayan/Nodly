"""Declarative base, naming convention and column helpers shared by all models."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, MetaData, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from nodly.clock import utcnow

# Deterministic constraint names, so migrations can refer to them and errors can report them.
# https://alembic.sqlalchemy.org/en/latest/naming.html
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {  # noqa: RUF012  # SQLAlchemy reads this class attribute
        datetime: DateTime(timezone=True),
        dict[str, Any]: JSONB,
    }


class UUIDPrimaryKey:
    # Generated in Python so related rows can be built before a flush; the server default
    # covers rows inserted by plain SQL.
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
        sort_order=-100,  # first column in the table
    )


class CreatedAt:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), sort_order=100)


class Timestamps(CreatedAt):
    # Python-side onupdate, so the new value is known without reloading the row.
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=utcnow, sort_order=101
    )


def one_of(column: str, values: type[StrEnum], name: str) -> CheckConstraint:
    """CHECK (column IN (...)). We store enums as text: adding a value later is one migration."""
    allowed = ", ".join(f"'{member.value}'" for member in values)
    return CheckConstraint(f"{column} IN ({allowed})", name=name)


# Formats enforced in the database as a last line of defence; services validate first.
COUNTRY_CODE_PATTERN = "^[A-Z]{2}$"
E164_PATTERN = "^\\+[1-9][0-9]{6,14}$"
LOCALE_PATTERN = "^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$"
SHA256_HEX_PATTERN = "^[0-9a-f]{64}$"


def matches(column: str, pattern: str, name: str, *, nullable: bool = False) -> CheckConstraint:
    condition = f"{column} ~ '{pattern}'"
    if nullable:
        condition = f"{column} IS NULL OR {condition}"
    return CheckConstraint(condition, name=name)


def not_blank(column: str, max_length: int) -> CheckConstraint:
    return CheckConstraint(
        f"length(btrim({column})) BETWEEN 1 AND {max_length}", name=f"{column}_not_blank"
    )
