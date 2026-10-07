"""Review workflow v2: typed decisions, optimistic versions, amendments, audit."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from ..contracts import Contract, comparison_key, normalize
from ..core import IntakeError
from ..storage.schema import Amendment, ProcessedEvent, RawEvent, ReviewVersion
from .audit import append_in_session
from .roles import allowed, require

CLI_ACTOR = "cli:local"  # offline demos; in-process only, never accepted over HTTP
MIN_RATIONALE = 20


@dataclass(frozen=True)
class ReviewConflict(IntakeError):
    current_version: int = 0


def _begin(engine: Engine, session: Session) -> None:
    if engine.dialect.name == "sqlite":
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")


def _latest(session: Session, tenant_id: str, event_id: str) -> ReviewVersion | None:
    return session.scalar(
        select(ReviewVersion)
        .where(ReviewVersion.tenant_id == tenant_id, ReviewVersion.event_id == event_id)
        .order_by(ReviewVersion.version.desc())
        .limit(1)
    )


def _open_amendment(session: Session, tenant_id: str, event_id: str) -> Amendment | None:
    return session.scalar(
        select(Amendment)
        .where(
            Amendment.tenant_id == tenant_id,
            Amendment.event_id == event_id,
            Amendment.status == "open",
        )
        .order_by(Amendment.seq.desc())
        .limit(1)
    )


def _base_packet(session: Session, tenant_id: str, event_id: str) -> dict[str, Any]:
    matches = session.scalars(
        select(ProcessedEvent).where(
            ProcessedEvent.tenant_id == tenant_id, ProcessedEvent.event_id == event_id
        )
    ).all()
    if len(matches) != 1:
        raise IntakeError("not_found", "no single intake for this tenant and event")
    packet: dict[str, Any] = json.loads(matches[0].packet_json)
    return packet


def _status(latest: ReviewVersion | None, amendment: Amendment | None) -> str:
    if amendment is not None:
        return "needs_re_review"
    if latest is None:
        return "needs_review"
    return "approved" if latest.state == "approved" else "deferred"


def view_case(engine: Engine, tenant_id: str, event_id: str) -> dict[str, Any]:
    with Session(engine) as session:
        latest = _latest(session, tenant_id, event_id)
        amendment = _open_amendment(session, tenant_id, event_id)
        packet = _base_packet(session, tenant_id, event_id)
        if amendment is not None:
            packet = json.loads(amendment.packet_json)
        elif latest is not None:
            packet = json.loads(latest.packet_json)
        return {
            "event_id": event_id,
            "status": _status(latest, amendment),
            "version": latest.version if latest is not None else 0,
            "packet": packet,
            "amendment": (
                {"seq": amendment.seq, "diff": json.loads(amendment.diff_json)}
                if amendment is not None
                else None
            ),
        }


def received_at(engine: Engine, tenant_id: str, event_id: str) -> datetime | None:
    """First time the tenant's webhook accepted this event; None when no raw row exists."""
    with Session(engine) as session:
        value = session.scalar(
            select(func.min(RawEvent.received_at)).where(
                RawEvent.tenant_id == tenant_id, RawEvent.event_id == event_id
            )
        )
    if value is not None and value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)  # stored naive, always UTC
    return value


def _has_ai(packet: dict[str, Any], contract: Contract) -> bool:
    options = [o for group in packet.get("candidates", {}).values() for o in group]
    return any(
        o["source"] in contract.sources and contract.sources[o["source"]].trust == "ai"
        for o in options
    )


def _has_override(session: Session, tenant_id: str, event_id: str) -> bool:
    rows = session.scalars(
        select(ReviewVersion.decisions_json).where(
            ReviewVersion.tenant_id == tenant_id, ReviewVersion.event_id == event_id
        )
    ).all()
    for raw in rows:
        decisions = json.loads(raw)
        if any(isinstance(d, dict) and d.get("type") == "override" for d in decisions.values()):
            return True
    return False


def list_cases(
    engine: Engine, tenant_id: str, contract: Contract | None = None
) -> list[dict[str, Any]]:
    """Queue rows. With a contract each row also carries the filterable queue facts."""
    with Session(engine) as session:
        ids = session.scalars(
            select(ProcessedEvent.event_id)
            .where(ProcessedEvent.tenant_id == tenant_id)
            .order_by(ProcessedEvent.event_id)
        ).all()
    rows: list[dict[str, Any]] = []
    for event_id in ids:
        full = view_case(engine, tenant_id, event_id)
        row = {k: v for k, v in full.items() if k != "packet"}
        if contract is not None:
            packet = full["packet"]
            names = packet["resolved"].get("customer_name")
            if names is None:
                names = next(
                    (o["value"] for o in packet["candidates"].get("customer_name", [])), ""
                )
            when = received_at(engine, tenant_id, event_id)
            with Session(engine) as session:
                override = _has_override(session, tenant_id, event_id)
            row.update(
                customer=names,
                received_at=when.isoformat() if when is not None else None,
                has_ai=_has_ai(packet, contract),
                has_override=override,
            )
        rows.append(row)
    return rows


def _targets(packet: dict[str, Any], contract: Contract) -> list[str]:
    """Fields that need a decision: every conflict and every required field with no value."""
    names = set(packet["conflicts"])
    for name, rule in contract.fields.items():
        if rule.required and name not in packet["resolved"] and name not in names:
            names.add(name)
    return sorted(names)


def _apply(
    packet: dict[str, Any], contract: Contract, decisions: dict[str, Any]
) -> tuple[dict[str, Any], list[str], list[str]]:
    needed = _targets(packet, contract)
    unknown = sorted(set(decisions) - set(needed))
    absent = sorted(set(needed) - set(decisions))
    if unknown or absent:
        raise IntakeError(
            "invalid_review", f"decisions must cover exactly: {', '.join(needed) or 'nothing'}"
        )
    resolved = dict(packet["resolved"])
    deferred: list[str] = []
    overrides: list[str] = []
    for name in needed:
        decision = decisions[name]
        kind = decision.get("type") if isinstance(decision, dict) else None
        if kind == "choose_source":
            options = packet["conflicts"].get(name) or packet.get("candidates", {}).get(name, [])
            picked = [o for o in options if o["source"] == decision.get("source")]
            if len(picked) != 1:
                raise IntakeError("invalid_review", f"{name} must choose one candidate source")
            resolved[name] = picked[0]["value"]
        elif kind == "override":
            rationale = decision.get("rationale")
            if not isinstance(rationale, str) or len(rationale.strip()) < MIN_RATIONALE:
                raise IntakeError(
                    "invalid_review", f"override rationale needs {MIN_RATIONALE}+ characters"
                )
            value = normalize(contract.fields[name], decision.get("value"))
            if value is None:
                raise IntakeError("invalid_review", f"{name} override needs a value")
            resolved[name] = value
            overrides.append(name)
        elif kind == "defer":
            question = decision.get("question")
            if not isinstance(question, str) or not question.strip() or len(question) > 500:
                raise IntakeError("invalid_review", f"{name} defer needs a customer question")
            deferred.append(name)
        else:
            raise IntakeError("invalid_review", f"{name} needs choose_source, override or defer")
    return resolved, deferred, overrides


def submit_decisions(
    engine: Engine,
    tenant_id: str,
    event_id: str,
    actor: str,
    role: str | None,
    decisions: dict[str, Any],
    contract: Contract,
    *,
    expected_version: int,
    reason: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Record version n+1. Approves only when every target is decided and none deferred."""
    if type(expected_version) is not int or expected_version < 0 or not isinstance(decisions, dict):
        raise IntakeError("invalid_review", "expected_version and decisions are required")
    if actor == CLI_ACTOR:
        role = "reviewer"
    require(role, "decide")
    with Session(engine) as session, session.begin():
        _begin(engine, session)
        latest = _latest(session, tenant_id, event_id)
        current = latest.version if latest is not None else 0
        if current != expected_version:
            raise ReviewConflict("review_conflict", "review version changed", current)
        amendment = _open_amendment(session, tenant_id, event_id)
        if latest is not None and latest.state == "approved" and amendment is None:
            raise IntakeError("already_approved", "case is approved; amend it to reopen")
        packet = (
            json.loads(amendment.packet_json)
            if amendment is not None
            else _base_packet(session, tenant_id, event_id)
        )
        resolved, deferred, overrides = _apply(packet, contract, decisions)
        if overrides and contract.two_person_override and not allowed(role, "override_two_person"):
            raise IntakeError("forbidden", "overrides need an approver for this tenant")
        approved = not deferred
        questions = [decisions[name]["question"] for name in deferred]
        result = {
            **packet,
            "status": "approved" if approved else "needs_customer_input",
            "resolved": resolved,
            "questions": questions,
            "review_version": current + 1,
            "review_actor": actor,
            "review_decisions": decisions,
        }
        session.add(
            ReviewVersion(
                tenant_id=tenant_id,
                event_id=event_id,
                version=current + 1,
                parent_version=current or None,
                actor=actor,
                decisions_json=json.dumps(decisions, sort_keys=True),
                packet_json=json.dumps(result, sort_keys=True),
                state="approved" if approved else "deferred",
                reason=reason or None,
                **({"created_at": now} if now is not None else {}),
            )
        )
        detail = {
            "version": current + 1,
            "types": {name: decisions[name]["type"] for name in sorted(decisions)},
        }
        append_in_session(session, tenant_id, actor, "decide", event_id, detail, now=now)
        if approved:
            append_in_session(
                session, tenant_id, actor, "approve", event_id, {"version": current + 1}, now=now
            )
            if amendment is not None:
                amendment.status = "closed"
        return result


def amend_case(
    engine: Engine,
    tenant_id: str,
    event_id: str,
    actor: str,
    role: str | None,
    source: str,
    fields: dict[str, Any],
    contract: Contract,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """New source evidence on an approved case reopens it with a field-level diff."""
    if actor == CLI_ACTOR:
        role = "reviewer"
    require(role, "amend")
    if source not in contract.sources or not isinstance(fields, dict) or not fields:
        raise IntakeError("invalid_amendment", "a configured source and fields are required")
    if set(fields) - set(contract.fields):
        raise IntakeError("invalid_amendment", "fields must be in the tenant contract")
    with Session(engine) as session, session.begin():
        _begin(engine, session)
        latest = _latest(session, tenant_id, event_id)
        if latest is None or latest.state != "approved":
            raise IntakeError("not_approved", "only an approved case can be amended")
        if _open_amendment(session, tenant_id, event_id) is not None:
            raise IntakeError("amendment_open", "finish the open amendment first")
        approved_packet = json.loads(latest.packet_json)
        if "candidates" not in approved_packet:
            raise IntakeError("unsupported_version", "amendments need a schema 2 case")
        candidates: dict[str, list[dict[str, Any]]] = {
            name: [dict(c) for c in options]
            for name, options in approved_packet["candidates"].items()
        }
        for name, raw in fields.items():
            value = normalize(contract.fields[name], raw)
            if value is None:
                raise IntakeError("invalid_amendment", f"{name} needs a value")
            kept = [c for c in candidates[name] if c["source"] != source]
            candidates[name] = sorted(
                [*kept, {"source": source, "value": value}],
                key=lambda c: (contract.sources[c["source"]].priority, c["source"]),
            )
        resolved: dict[str, Any] = {}
        conflicts: dict[str, list[dict[str, Any]]] = {}
        questions: list[str] = []
        for name, rule in contract.fields.items():
            options = candidates[name]
            if name not in fields and name in approved_packet["resolved"]:
                # An earlier reviewer decision stands for fields the new evidence does not touch.
                resolved[name] = approved_packet["resolved"][name]
            elif len({comparison_key(rule, c["value"]) for c in options}) > 1:
                conflicts[name] = options
                questions.append(f"Which {name.replace('_', ' ')} is correct?")
            elif options:
                resolved[name] = options[0]["value"]
            elif rule.required:
                questions.append(f"What is the {name.replace('_', ' ')}?")
        diff = []
        for name in sorted(fields):
            old = approved_packet["resolved"].get(name)
            new_value = next(c["value"] for c in candidates[name] if c["source"] == source)
            rule = contract.fields[name]
            if old is None or comparison_key(rule, new_value) != comparison_key(rule, old):
                diff.append(
                    {"field": name, "old_approved_value": old, "new_candidates": candidates[name]}
                )
        if not diff:
            raise IntakeError("no_change", "the new evidence matches the approved values")
        packet = {
            **approved_packet,
            "status": "needs_re_review",
            "resolved": resolved,
            "conflicts": conflicts,
            "questions": questions,
            "candidates": candidates,
        }
        for key in ("review_version", "review_actor", "review_decisions"):
            packet.pop(key, None)
        seq = (
            session.scalar(
                select(func.max(Amendment.seq)).where(
                    Amendment.tenant_id == tenant_id, Amendment.event_id == event_id
                )
            )
            or 0
        ) + 1
        session.add(
            Amendment(
                tenant_id=tenant_id,
                event_id=event_id,
                seq=seq,
                status="open",
                diff_json=json.dumps(diff, sort_keys=True),
                packet_json=json.dumps(packet, sort_keys=True),
                base_version=latest.version,
            )
        )
        append_in_session(
            session,
            tenant_id,
            actor,
            "amend",
            event_id,
            {"seq": seq, "source": source, "fields": sorted(fields)},
            now=now,
        )
        return {"status": "needs_re_review", "diff": diff, "base_version": latest.version}


__all__ = [
    "CLI_ACTOR",
    "ReviewConflict",
    "amend_case",
    "list_cases",
    "submit_decisions",
    "view_case",
]
