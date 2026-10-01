"""Tenant-scoped SQLAlchemy storage models; v0.2 tables survive the migration."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, LargeBinary, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.engine import Engine


class Base(DeclarativeBase):
    pass


class ProcessedEvent(Base):
    __tablename__ = "processed_events_v2"
    tenant_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    source: Mapped[str] = mapped_column(String(100), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    packet_json: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (Index("ix_processed_events_tenant", "tenant_id"),)


class ReviewVersion(Base):
    __tablename__ = "review_versions"
    tenant_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    version: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    decisions_json: Mapped[str] = mapped_column(Text, nullable=False)
    packet_json: Mapped[str] = mapped_column(Text, nullable=False)


class RawEvent(Base):
    __tablename__ = "raw_events"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    event_id: Mapped[str] = mapped_column(String(100), nullable=False)
    received_at: Mapped[datetime] = mapped_column(nullable=False)
    body_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    auth_mode: Mapped[str] = mapped_column(String(30), nullable=False)
    __table_args__ = (Index("ix_raw_events_retention", "tenant_id", "received_at"),)


class MachineKey(Base):
    __tablename__ = "machine_keys"
    tenant_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    prefix: Mapped[str] = mapped_column(String(32), primary_key=True)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)


def engine_for(url: str) -> Engine:
    """SQLite WAL for local concurrent writes, Postgres through DATABASE_URL."""
    engine = create_engine(url, future=True)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def configure_sqlite(dbapi_connection: object, connection_record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA foreign_keys=ON")
            finally:
                cursor.close()

    return engine
