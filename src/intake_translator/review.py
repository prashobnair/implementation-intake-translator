"""Explicit, local review gate. A decision never triggers a downstream action."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Mapping
from .core import FIELDS, REQUIRED, IntakeError


def submit_review(db_path: str, event_id: str, decisions: Mapping[str, str], expected_version: int = 0) -> tuple[dict[str, object], bool]:
    """Atomically approve a fully resolved packet, or replay the exact same review.

    A conflict must select a named source already in the stored packet. No
    invented value or silent default is accepted; missing required fields block.
    """
    if not isinstance(event_id, str) or not event_id:
        raise IntakeError("invalid_review", "event_id is required")
    if not isinstance(expected_version, int) or isinstance(expected_version, bool) or expected_version != 0:
        raise IntakeError("invalid_review", "expected_version must be 0 for the initial review")
    if not isinstance(decisions, Mapping) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in decisions.items()):
        raise IntakeError("invalid_review", "decisions must map field names to source names")
    # No table creation here: an absent event is not a new intake.
    try:
        with sqlite3.connect(db_path, timeout=10) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT packet_json FROM processed_events WHERE event_id = ?", (event_id,)).fetchone()
            if row is None:
                raise IntakeError("not_found", "event_id has no stored intake")
            packet = json.loads(row[0])
            conflicts = packet["conflicts"]
            unknown = set(decisions) - set(conflicts)
            absent = set(conflicts) - set(decisions)
            if unknown or absent:
                raise IntakeError("invalid_review", f"decisions must select exactly these conflicts: {', '.join(sorted(conflicts))}")
            if packet["questions"] and any(field not in conflicts for field in REQUIRED if field not in packet["resolved"]):
                raise IntakeError("unresolved_required", "a required field is missing from the source records")
            resolved = dict(packet["resolved"])
            for field in FIELDS:
                if field not in conflicts:
                    continue
                matches = [candidate for candidate in conflicts[field] if candidate["source"] == decisions[field]]
                if len(matches) != 1:
                    raise IntakeError("invalid_review", f"{field} must select one source in its conflict candidates")
                resolved[field] = matches[0]["value"]
            if any(field not in resolved for field in REQUIRED):
                raise IntakeError("unresolved_required", "required field is unresolved")
            decision_json = json.dumps(dict(decisions), sort_keys=True)
            conn.execute("CREATE TABLE IF NOT EXISTS review_decisions (event_id TEXT PRIMARY KEY, version INTEGER NOT NULL, decisions_json TEXT NOT NULL, approved_packet_json TEXT NOT NULL, reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            prior = conn.execute("SELECT version, decisions_json, approved_packet_json FROM review_decisions WHERE event_id = ?", (event_id,)).fetchone()
            if prior:
                if prior[0] == 1 and prior[1] == decision_json:
                    return json.loads(prior[2]), True
                raise IntakeError("review_conflict", "event was already reviewed with different decisions")
            approved = {**packet, "status": "approved", "resolved": resolved, "questions": [], "review_version": 1, "review_decisions": dict(decisions)}
            conn.execute("INSERT INTO review_decisions (event_id, version, decisions_json, approved_packet_json) VALUES (?, 1, ?, ?)", (event_id, decision_json, json.dumps(approved, sort_keys=True)))
            return approved, False
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            raise IntakeError("not_found", "event_id has no stored intake") from exc
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Approve a stored synthetic intake after selecting each conflicting source")
    parser.add_argument("event_id")
    parser.add_argument("decisions", help="JSON file mapping conflict field to chosen source")
    parser.add_argument("--db", default="intake-events.sqlite3")
    args = parser.parse_args()
    try:
        with open(args.decisions, encoding="utf-8") as source:
            choices = json.load(source)
        approved, replayed = submit_review(args.db, args.event_id, choices)
    except (OSError, json.JSONDecodeError, IntakeError) as exc:
        print(f"review error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({**approved, "replayed": replayed}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
