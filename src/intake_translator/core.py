"""Pure decision logic. No downstream project creation or customer messaging."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re

SCHEMA_VERSION = "1"
SOURCES = ("form", "crm", "notes")
FIELDS = ("customer_name", "launch_date", "seat_count", "region")
REQUIRED = ("customer_name", "launch_date")


@dataclass(frozen=True)
class IntakeError(Exception):
    code: str
    detail: str

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


def _clean(field: str, value: object) -> str | int | None:
    if value is None:
        return None
    if field == "seat_count":
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise IntakeError("invalid_field", "seat_count must be a positive integer")
        text = str(value).strip()
        if not text.isdecimal() or int(text) < 1:
            raise IntakeError("invalid_field", "seat_count must be a positive integer")
        return int(text)
    if not isinstance(value, str):
        raise IntakeError("invalid_field", f"{field} must be text")
    text = " ".join(value.split())
    if not text:
        return None
    if len(text) > 200:
        raise IntakeError("invalid_field", f"{field} is too long")
    if field == "launch_date" and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        raise IntakeError("invalid_field", "launch_date must use YYYY-MM-DD")
    if field == "launch_date":
        from datetime import date
        try:
            date.fromisoformat(text)
        except ValueError as exc:
            raise IntakeError("invalid_field", "launch_date is not a calendar date") from exc
    return text


def analyze_intake(event: Mapping[str, object]) -> dict[str, object]:
    """Return a review packet; never choose among conflicting sources silently.

    A caller must supply an event_id and stable version; delivery deduplication
    belongs to the durable storage boundary, not this pure function.
    """
    if not isinstance(event, Mapping):
        raise IntakeError("invalid_event", "event must be an object")
    if event.get("schema_version") != SCHEMA_VERSION:
        raise IntakeError("unsupported_version", "schema_version must be 1")
    event_id = event.get("event_id")
    if not isinstance(event_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,99}", event_id):
        raise IntakeError("invalid_event_id", "event_id must be 1-100 safe characters")
    sources = event.get("sources")
    if not isinstance(sources, Mapping) or not sources:
        raise IntakeError("invalid_sources", "sources must be a nonempty object")
    unknown = set(sources) - set(SOURCES)
    if unknown:
        raise IntakeError("invalid_sources", f"unknown sources: {', '.join(sorted(map(str, unknown)))}")
    candidates: dict[str, list[dict[str, object]]] = {field: [] for field in FIELDS}
    for source in SOURCES:
        if source not in sources:
            continue
        record = sources[source]
        if not isinstance(record, Mapping):
            raise IntakeError("invalid_sources", f"{source} must be an object")
        unknown_fields = set(record) - set(FIELDS)
        if unknown_fields:
            raise IntakeError("invalid_field", f"{source} has unknown fields: {', '.join(sorted(map(str, unknown_fields)))}")
        for field in FIELDS:
            if field in record:
                clean = _clean(field, record[field])
                if clean is not None:
                    candidates[field].append({"source": source, "value": clean})
    resolved: dict[str, object] = {}
    conflicts: dict[str, list[dict[str, object]]] = {}
    questions: list[str] = []
    for field in FIELDS:
        options = candidates[field]
        distinct = {str(item["value"]).casefold() for item in options}
        if len(distinct) > 1:
            conflicts[field] = options
            questions.append(f"Which {field.replace('_', ' ')} is correct? Confirm against the source records.")
        elif options:
            resolved[field] = options[0]["value"]
        elif field in REQUIRED:
            questions.append(f"What is the {field.replace('_', ' ')}?")
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id,
        "status": "needs_review",  # V1 never auto-approves or acts downstream
        "resolved": resolved,
        "conflicts": conflicts,
        "questions": questions,
        "source_count": len(sources),
  }
