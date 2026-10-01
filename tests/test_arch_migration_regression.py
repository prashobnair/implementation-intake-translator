"""Migration remains a no-op for the exact legacy row bytes."""

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from contextlib import closing

from intake_translator.store import process_once

ROOT = Path(__file__).parents[1]
EXAMPLE = json.loads((ROOT / "examples/conflicting-intake.json").read_text())


def test_migration_preserves_original_packet_bytes(tmp_path):
    db = tmp_path / "v02.sqlite3"
    process_once(str(db), EXAMPLE)
    with closing(sqlite3.connect(db)) as conn:
        old = conn.execute(
            "SELECT event_id, payload_sha256, packet_json FROM processed_events"
        ).fetchone()
    assert old is not None and old[0] == "fictional-nexaflow-deal-001"
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": f"sqlite:///{db}"},
        check=True,
        capture_output=True,
    )
    with closing(sqlite3.connect(db)) as conn:
        new = conn.execute(
            "SELECT event_id, payload_sha256, packet_json FROM processed_events"
        ).fetchone()
    assert new == old
    assert json.loads(new[2])["conflicts"]["launch_date"][0] == {
        "source": "form",
        "value": "2026-11-02",
    }
