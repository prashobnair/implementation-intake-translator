"""Local-only mock CRM projection of an explicitly reviewed synthetic intake."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from .core import IntakeError


def apply_reviewed_intake(db_path: str, event_id: str, *, fail_before_write: bool = False) -> tuple[dict[str, object], bool]:
    """Create exactly one local mock project from a stored version-1 review.

    The approved snapshot and mock project use the same SQLite transaction.
    Failed writes roll back, and a second delivery returns the stored project.
    No remote CRM request is made.
    """
    if not isinstance(event_id, str) or not event_id:
        raise IntakeError("invalid_event_id", "event_id is required")
    try:
        with sqlite3.connect(db_path, timeout=10) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT approved_packet_json FROM review_decisions WHERE event_id = ?", (event_id,)).fetchone()
            if row is None:
                raise IntakeError("not_approved", "no reviewed decision exists for this event")
            approved = json.loads(row[0])
            if approved.get("status") != "approved" or approved.get("review_version") != 1 or approved.get("event_id") != event_id:
                raise IntakeError("invalid_approval", "stored review is not an approved version-1 event")
            resolved = approved["resolved"]
            if not all(key in resolved for key in ("customer_name", "launch_date")):
                raise IntakeError("invalid_approval", "required details are missing")
            conn.execute("CREATE TABLE IF NOT EXISTS mock_projects (event_id TEXT PRIMARY KEY, project_json TEXT NOT NULL)")
            previous = conn.execute("SELECT project_json FROM mock_projects WHERE event_id = ?", (event_id,)).fetchone()
            if previous:
                return json.loads(previous[0]), True
            project = {"project_id": f"demo:{event_id}", "event_id": event_id, "review_version": 1,
                       "customer_name": resolved["customer_name"], "launch_date": resolved["launch_date"],
                       "seat_count": resolved.get("seat_count"), "region": resolved.get("region"), "system": "local_mock_crm"}
            if fail_before_write:
                raise IntakeError("simulated_failure", "mock CRM write failed before commit")
            conn.execute("INSERT INTO mock_projects (event_id, project_json) VALUES (?, ?)", (event_id, json.dumps(project, sort_keys=True)))
            return project, False
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            raise IntakeError("not_approved", "no reviewed decision exists for this event") from exc
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Write an approved synthetic intake to a LOCAL mock CRM table")
    parser.add_argument("event_id")
    parser.add_argument("--db", default="intake-events.sqlite3")
    args = parser.parse_args()
    try:
        project, replayed = apply_reviewed_intake(args.db, args.event_id)
    except (OSError, IntakeError) as exc:
        print(f"mock CRM error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({**project, "replayed": replayed}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
