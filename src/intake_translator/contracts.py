"""Pure, tenant-configured intake validation. No database or network access."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

import yaml

from .core import IntakeError

FieldType = Literal["text", "date", "int", "decimal", "enum", "email", "money", "enum_list", "bool"]
Compare = Literal["casefold", "exact", "numeric", "date"]


@dataclass(frozen=True)
class Field:
    type: FieldType
    required: bool
    max_len: int
    enum_values: tuple[str, ...]
    pii: bool
    compare: Compare


@dataclass(frozen=True)
class Source:
    priority: int
    trust: Literal["system", "human", "ai"]


@dataclass(frozen=True)
class Contract:
    fields: dict[str, Field]
    sources: dict[str, Source]
    digest: Literal["raw", "normalized"]
    auto_approve_when_unanimous: bool
    two_person_override: bool = False


def parse_contract(text: str) -> Contract:
    """Reject ambiguous or incomplete contract keys before accepting an event."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise IntakeError("invalid_contract", "contract YAML is invalid") from exc
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("fields"), dict)
        or not isinstance(data.get("sources"), dict)
    ):
        raise IntakeError("invalid_contract", "fields and sources must be objects")
    if not data["fields"] or not data["sources"]:
        raise IntakeError("invalid_contract", "fields and sources must not be empty")
    if set(data) - {
        "fields",
        "sources",
        "idempotency",
        "auto_approve_when_unanimous",
        "two_person_override",
    }:
        raise IntakeError("invalid_contract", "unknown contract option")
    fields: dict[str, Field] = {}
    for name, rule in data["fields"].items():
        if not isinstance(name, str) or not isinstance(rule, dict):
            raise IntakeError("invalid_contract", "field rules must be named objects")
        kind = rule.get("type")
        compare = rule.get("compare", "exact")
        values = rule.get("enum_values", [])
        limit = rule.get("max_len", 200)
        if kind not in (
            "text",
            "date",
            "int",
            "decimal",
            "enum",
            "email",
            "money",
            "enum_list",
            "bool",
        ) or compare not in ("casefold", "exact", "numeric", "date"):
            raise IntakeError("invalid_contract", "unsupported field type or comparison")
        if (
            type(limit) is not int
            or not 1 <= limit <= 4096
            or not isinstance(values, list)
            or any(not isinstance(v, str) for v in values)
        ):
            raise IntakeError("invalid_contract", "invalid field length or enum values")
        if kind in ("enum", "enum_list") and not values:
            raise IntakeError("invalid_contract", "enum fields need values")
        if kind == "enum_list" and compare != "exact":
            raise IntakeError("invalid_contract", "enum_list must use exact comparison")
        if any(type(rule.get(flag, False)) is not bool for flag in ("required", "pii")):
            raise IntakeError("invalid_contract", "required and pii must be booleans")
        if set(rule) - {"type", "required", "max_len", "enum_values", "pii", "compare"}:
            raise IntakeError("invalid_contract", "unknown field rule")
        fields[name] = Field(
            kind, rule.get("required", False), limit, tuple(values), rule.get("pii", False), compare
        )
    sources: dict[str, Source] = {}
    for name, rule in data["sources"].items():
        if (
            not isinstance(name, str)
            or not isinstance(rule, dict)
            or set(rule) != {"priority", "trust"}
        ):
            raise IntakeError("invalid_contract", "source requires priority and trust")
        if type(rule["priority"]) is not int or rule["trust"] not in ("system", "human", "ai"):
            raise IntakeError("invalid_contract", "invalid source priority or trust")
        sources[name] = Source(rule["priority"], rule["trust"])
    digest_data = data.get("idempotency", {"digest": "raw"})
    if (
        not isinstance(digest_data, dict)
        or set(digest_data) != {"digest"}
        or digest_data["digest"] not in ("raw", "normalized")
    ):
        raise IntakeError("invalid_contract", "digest must be raw or normalized")
    auto = data.get("auto_approve_when_unanimous", False)
    if type(auto) is not bool:
        raise IntakeError("invalid_contract", "auto_approve_when_unanimous must be boolean")
    two = data.get("two_person_override", False)
    if type(two) is not bool:
        raise IntakeError("invalid_contract", "two_person_override must be boolean")
    return Contract(fields, sources, digest_data["digest"], auto, two)


def load_contract(path: Path) -> Contract:
    return parse_contract(path.read_text(encoding="utf-8"))


def normalize(field: Field, value: object) -> str | int | bool | list[str] | None:
    if value is None:
        return None
    kind = field.type
    if kind == "bool":
        if type(value) is not bool:
            raise IntakeError("invalid_field", "boolean field must be true or false")
        return value
    if kind == "enum_list":
        if not isinstance(value, list) or any(
            not isinstance(v, str) or v not in field.enum_values for v in value
        ):
            raise IntakeError("invalid_field", "invalid enum list")
        return sorted(set(value))
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise IntakeError("invalid_field", "integer field must be positive")
        text = str(value)
        if not re.fullmatch(r"[0-9]+", text) or int(text) < 1:
            raise IntakeError("invalid_field", "integer field must be positive")
        return int(text)
    if kind in ("money", "decimal"):
        if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
            raise IntakeError("invalid_field", "decimal field must be a number")
        text = str(value)
        # ASCII digits only; Decimal itself accepts exponent, underscores and Unicode digits.
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", text) or (
            kind == "money" and "." in text and len(text.partition(".")[2]) > 2
        ):
            raise IntakeError("invalid_field", "invalid amount or precision")
        try:
            number = Decimal(text)
        except InvalidOperation as exc:
            raise IntakeError("invalid_field", "invalid decimal") from exc
        return format(number.normalize(), "f")
    if not isinstance(value, str):
        raise IntakeError("invalid_field", "field must be text")
    text = " ".join(value.split())
    if not text:
        return None
    if len(text) > field.max_len:
        raise IntakeError("invalid_field", "field is too long")
    if kind == "date":
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            raise IntakeError("invalid_field", "date must be YYYY-MM-DD")
        try:
            date.fromisoformat(text)
        except ValueError as exc:
            raise IntakeError("invalid_field", "invalid calendar date") from exc
    elif kind == "enum" and text not in field.enum_values:
        raise IntakeError("invalid_field", "unknown enum value")
    elif kind == "email" and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", text):
        raise IntakeError("invalid_field", "invalid email")
    return text


def comparison_key(field: Field, value: str | int | bool | list[str]) -> str:
    if field.compare == "casefold":
        return str(value).casefold()
    if field.compare == "numeric":
        return str(Decimal(str(value)).normalize())
    return str(value)


def analyze_v2(event: dict[str, Any], contract: Contract) -> dict[str, Any]:
    """Produce a review packet, preserving candidates and deterministic source priority."""
    if event.get("schema_version") != "2":
        raise IntakeError("unsupported_version", "schema_version must be 2")
    event_id = event.get("event_id")
    if not isinstance(event_id, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._:-]{0,99}", event_id
    ):
        raise IntakeError("invalid_event_id", "event_id must be 1-100 safe characters")
    raw_sources = event.get("sources")
    if (
        not isinstance(raw_sources, dict)
        or not raw_sources
        or set(raw_sources) - set(contract.sources)
    ):
        raise IntakeError("invalid_sources", "sources must be a nonempty configured object")
    candidates: dict[str, list[dict[str, Any]]] = {name: [] for name in contract.fields}
    for name in sorted(raw_sources, key=lambda n: (contract.sources[n].priority, n)):
        source = raw_sources[name]
        if not isinstance(source, dict) or set(source) - set(contract.fields):
            raise IntakeError("invalid_field", "source contains invalid fields")
        for field_name, value in source.items():
            cleaned = normalize(contract.fields[field_name], value)
            if cleaned is not None:
                candidates[field_name].append({"source": name, "value": cleaned})
    resolved: dict[str, Any] = {}
    conflicts: dict[str, list[dict[str, Any]]] = {}
    questions: list[str] = []
    for name, rule in contract.fields.items():
        options = candidates[name]
        if len({comparison_key(rule, item["value"]) for item in options}) > 1:
            conflicts[name] = options
            questions.append(
                f"Which {name.replace('_', ' ')} is correct? Confirm against the source records."
            )
        elif options:
            resolved[name] = options[0]["value"]
        elif rule.required:
            questions.append(f"What is the {name.replace('_', ' ')}?")
    return {
        "schema_version": "2",
        "event_id": event_id,
        "status": "needs_review",
        "resolved": resolved,
        "display": "first_source_priority",
        "conflicts": conflicts,
        "questions": questions,
        "source_count": len(raw_sources),
        "candidates": candidates,
    }
