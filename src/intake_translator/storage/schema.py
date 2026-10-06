"""Tenant-scoped SQLAlchemy storage models; v0.2 tables survive the migration."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Index, LargeBinary, String, Text, create_engine, event
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
    # Review workflow v2 (migration 0002). Rows written by v0.3 keep the defaults.
    parent_version: Mapped[int | None] = mapped_column(nullable=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="approved")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class Account(Base):
    __tablename__ = "accounts"
    username: Mapped[str] = mapped_column(String(100), primary_key=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Membership(Base):
    __tablename__ = "memberships"
    tenant_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    username: Mapped[str] = mapped_column(String(100), primary_key=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)


class OidcIdentity(Base):
    __tablename__ = "oidc_identities"
    provider: Mapped[str] = mapped_column(String(30), primary_key=True)
    subject: Mapped[str] = mapped_column(String(200), primary_key=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False)


class Amendment(Base):
    __tablename__ = "case_amendments"
    tenant_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    seq: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    diff_json: Mapped[str] = mapped_column(Text, nullable=False)
    packet_json: Mapped[str] = mapped_column(Text, nullable=False)
    base_version: Mapped[int] = mapped_column(nullable=False)


class AuditEntry(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    ts: Mapped[str] = mapped_column(String(40), nullable=False)
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    detail_json: Mapped[str] = mapped_column(Text, nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (Index("ix_audit_tenant_id", "tenant_id", "id"),)


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
