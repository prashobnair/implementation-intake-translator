"""Tenant-scoped, append-only review versions and safe unanimous policy."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from ..contracts import Contract
from ..core import IntakeError
from .schema import ReviewVersion


def record_review(
    engine: Engine,
    tenant_id: str,
    event_id: str,
    actor: str,
    decisions: dict[str, str],
    packet: dict[str, Any],
    *,
    expected_version: int = 0,
) -> dict[str, Any]:
    if (
        not all((tenant_id, event_id, actor))
        or type(expected_version) is not int
        or expected_version < 0
    ):
        raise IntakeError("invalid_review", "tenant, event, actor and version required")
    if packet.get("event_id") != event_id:
        raise IntakeError("invalid_review", "packet ID must match")
    with Session(engine) as session, session.begin():
        if engine.dialect.name == "sqlite":
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        latest = (
            session.scalar(
                select(func.max(ReviewVersion.version)).where(
                    ReviewVersion.tenant_id == tenant_id, ReviewVersion.event_id == event_id
                )
            )
            or 0
        )
        if latest != expected_version:
            raise IntakeError("review_conflict", "review version changed")
        approved = {
            **packet,
            "status": "approved",
            "review_version": latest + 1,
            "review_actor": actor,
            "review_decisions": decisions,
            "questions": [],
        }
        session.add(
            ReviewVersion(
                tenant_id=tenant_id,
                event_id=event_id,
                version=latest + 1,
                actor=actor,
                decisions_json=json.dumps(decisions, sort_keys=True),
                packet_json=json.dumps(approved, sort_keys=True),
            )
        )
        return approved


def maybe_auto_approve(
    engine: Engine, tenant_id: str, packet: dict[str, Any], contract: Contract
) -> dict[str, Any]:
    """Never approve missing/conflicting required fields or any AI-sourced candidate."""
    if (
        not contract.auto_approve_when_unanimous
        or packet.get("conflicts")
        or packet.get("questions")
    ):
        return packet
    candidates = packet.get("candidates", {})
    if not isinstance(candidates, dict):
        return packet
    if any(
        contract.sources[item["source"]].trust == "ai"
        for options in candidates.values()
        for item in options
    ):
        return packet
    for field, rule in contract.fields.items():
        if not rule.required:
            continue
        options = candidates.get(field, [])
        if not options or any(contract.sources[item["source"]].trust == "ai" for item in options):
            return packet
    return record_review(
        engine, tenant_id, packet["event_id"], "system:unanimous-policy", {}, packet
    )
