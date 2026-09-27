"""One-command, synthetic-only walkthrough of intake and review gates."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import cast

from .core import IntakeError
from .mock_crm import apply_reviewed_intake
from .review import submit_review
from .store import process_once


def walkthrough(examples_dir: Path) -> dict[str, object]:
    """Run a disposable local demonstration without touching live services."""
    expected = (
        "good-agreement",
        "bad-conflict",
        "bad-missing-required",
        "bad-invalid-date",
        "bad-unknown-field",
        "bad-unsupported-version",
    )
    outcomes = {}
    with tempfile.TemporaryDirectory(prefix="intake-demo-") as tmp:
        database = str(Path(tmp) / "demo.sqlite3")
        for name in expected:
            event = json.loads((examples_dir / f"{name}.json").read_text(encoding="utf-8"))
            try:
                packet, _ = process_once(database, event)
                outcomes[name] = {
                    "status": packet["status"],
                    "conflicts": packet["conflicts"],
                    "questions": packet["questions"],
                }
            except IntakeError as exc:
                outcomes[name] = {"error": exc.code, "detail": exc.detail}
        event_id = "demo-bad-conflict-001"
        try:
            apply_reviewed_intake(database, event_id)
        except IntakeError as exc:
            blocked = exc.code
        else:
            raise RuntimeError("mock CRM unexpectedly accepted an unreviewed intake")
        approval, _ = submit_review(database, event_id, {"launch_date": "crm"})
        project, _ = apply_reviewed_intake(database, event_id)
        replay, replayed = apply_reviewed_intake(database, event_id)
        if project != replay or not replayed:
            raise RuntimeError("mock CRM replay did not return the stored project")
        return {
            "samples": outcomes,
            "before_review": blocked,
            "selected_source": cast(dict[str, str], approval["review_decisions"])["launch_date"],
            "mock_project": project,
            "mock_project_replayed": replayed,
            "state": "disposed",
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--examples", type=Path, default=Path(__file__).resolve().parents[2] / "examples"
    )
    args = parser.parse_args()
    print(json.dumps(walkthrough(args.examples), indent=2))


if __name__ == "__main__":
    main()
