"""Every repository operation requires a tenant, including idempotency replay."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from ..core import IntakeError
from .schema import ProcessedEvent


class EventRepository(Protocol):
    def put(
        self,
        tenant_id: str,
        source: str,
        event_id: str,
        event: Mapping[str, Any],
        packet: Mapping[str, Any],
        *,
        normalized: bool = False,
    ) -> tuple[dict[str, Any], bool]: ...
    def get(self, tenant_id: str, source: str, event_id: str) -> dict[str, Any] | None: ...


class SqlRepository:
    def __init__(self, engine: Engine):
        self.engine = engine

    @staticmethod
    def _scope(tenant_id: str, source: str, event_id: str) -> None:
        if not all(isinstance(s, str) and s for s in (tenant_id, source, event_id)):
            raise IntakeError("invalid_scope", "tenant_id, source and event_id are required")

    def get(self, tenant_id: str, source: str, event_id: str) -> dict[str, Any] | None:
        self._scope(tenant_id, source, event_id)
        with Session(self.engine) as session:
            row = session.get(ProcessedEvent, (tenant_id, source, event_id))
            return json.loads(row.packet_json) if row is not None else None

    def put(
        self,
        tenant_id: str,
        source: str,
        event_id: str,
        event: Mapping[str, Any],
        packet: Mapping[str, Any],
        *,
        normalized: bool = False,
    ) -> tuple[dict[str, Any], bool]:
        self._scope(tenant_id, source, event_id)
        if packet.get("event_id") != event_id:
            raise IntakeError("invalid_event_id", "packet ID does not match scoped event ID")
        material = packet.get("candidates") if normalized else event
        raw = json.dumps(
            material, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        with Session(self.engine) as session, session.begin():
            if self.engine.dialect.name == "sqlite":
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            if self.engine.dialect.name == "postgresql":
                row = session.scalar(
                    select(ProcessedEvent)
                    .where(
                        ProcessedEvent.tenant_id == tenant_id,
                        ProcessedEvent.source == source,
                        ProcessedEvent.event_id == event_id,
                    )
                    .with_for_update()
                )
            else:
                row = session.get(ProcessedEvent, (tenant_id, source, event_id))
            if row is not None:
                if row.payload_sha256 != digest:
                    raise IntakeError("event_id_reused", "event ID has a different payload")
                return json.loads(row.packet_json), True
            result = dict(packet)
            session.add(
                ProcessedEvent(
                    tenant_id=tenant_id,
                    source=source,
                    event_id=event_id,
                    payload_sha256=digest,
                    packet_json=json.dumps(result, sort_keys=True),
                )
            )
            return result, False


class SQLiteRepository(SqlRepository):
    pass


class PostgresRepository(SqlRepository):
    pass
