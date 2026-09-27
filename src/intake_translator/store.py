"""Durable idempotency boundary for at-least-once event delivery."""

from __future__ import annotations
import hashlib
import json
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from .core import analyze_intake, IntakeError


def process_once(db_path: str, event: Mapping[str, object]) -> tuple[dict[str, object], bool]:
    """Return (packet, replayed); reject reused event IDs with different payloads."""
    # Canonical bytes make key order irrelevant but preserve values exactly.
    try:
        raw = json.dumps(
            event, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise IntakeError("invalid_event", "event must be JSON-compatible") from exc
    packet = analyze_intake(event)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    with closing(sqlite3.connect(db_path, timeout=10)) as conn, conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS processed_events (event_id TEXT PRIMARY KEY, payload_sha256 TEXT NOT NULL, packet_json TEXT NOT NULL)"
        )
        # SQLite serializes the check/insert transaction under concurrent writers.
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT payload_sha256, packet_json FROM processed_events WHERE event_id = ?",
            (packet["event_id"],),
        ).fetchone()
        if row:
            if row[0] != digest:
                raise IntakeError(
                    "event_id_reused", "event_id was already used for a different payload"
                )
            return json.loads(row[1]), True
        conn.execute(
            "INSERT INTO processed_events VALUES (?, ?, ?)",
            (packet["event_id"], digest, json.dumps(packet, sort_keys=True)),
        )
        return packet, False
