"""Tenant-specific field-contract dispatch, with legacy v1 replay unchanged."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .contracts import Contract, analyze_v2
from .core import IntakeError, analyze_intake
from .storage.repository import SqlRepository
from .storage.reviews import maybe_auto_approve
from .storage.schema import ReviewVersion


def process_contract_event(
    repository: SqlRepository,
    tenant_id: str,
    source: str,
    event: Mapping[str, Any],
    contracts: Mapping[str, Contract],
) -> tuple[dict[str, Any], bool]:
    """Choose v1 or v2, then use the tenant/source-scoped idempotency ledger."""
    if tenant_id not in contracts:
        raise IntakeError("unknown_tenant", "tenant has no configured field contract")
    schema = event.get("schema_version")
    if schema == "1":
        packet = analyze_intake(event)
    elif schema == "2":
        packet = analyze_v2(dict(event), contracts[tenant_id])
    else:
        raise IntakeError("unsupported_version", "schema_version must be 1 or 2")
    event_id = packet["event_id"]
    if not isinstance(event_id, str):
        raise IntakeError("invalid_event_id", "event ID must be text")
    packet, replayed = repository.put(
        tenant_id,
        source,
        event_id,
        event,
        packet,
        normalized=schema == "2" and contracts[tenant_id].digest == "normalized",
    )
    if schema == "2" and replayed:
        with Session(repository.engine) as session:
            review = session.scalar(
                select(ReviewVersion).where(
                    ReviewVersion.tenant_id == tenant_id,
                    ReviewVersion.event_id == event_id,
                    ReviewVersion.actor == "system:unanimous-policy",
                )
            )
            if review is not None:
                packet = json.loads(review.packet_json)
    elif schema == "2":
        packet = maybe_auto_approve(repository.engine, tenant_id, packet, contracts[tenant_id])
    return packet, replayed
