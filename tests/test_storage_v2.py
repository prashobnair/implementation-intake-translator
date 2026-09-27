"""Upgrade a real v0.2 SQLite ledger; enforce tenant/source isolation."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

from intake_translator.core import IntakeError
from intake_translator.storage.repository import SQLiteRepository
from intake_translator.storage.schema import engine_for
from intake_translator.store import process_once
from intake_translator.review import submit_review
from intake_translator.mock_crm import apply_reviewed_intake

EXAMPLE = json.loads((Path(__file__).parents[1] / "examples/conflicting-intake.json").read_text())


def migrate(path: Path):
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{path}"}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).parents[1],
        env=env,
        check=True,
        capture_output=True,
    )


def test_v02_migration_retains_replay_and_wal(tmp_path):
    db = tmp_path / "legacy.sqlite3"
    before, replayed = process_once(str(db), EXAMPLE)
    assert replayed is False
    assert before["event_id"] == "fictional-nexaflow-deal-001"
    assert before["conflicts"]["launch_date"] == [
        {"source": "form", "value": "2026-11-02"},
        {"source": "crm", "value": "2026-11-16"},
    ]
    approved_before, _ = submit_review(str(db), EXAMPLE["event_id"], {"launch_date": "crm"})
    project_before, _ = apply_reviewed_intake(str(db), EXAMPLE["event_id"])
    assert approved_before["resolved"]["launch_date"] == "2026-11-16"
    assert project_before["project_id"] == "demo:fictional-nexaflow-deal-001"
    migrate(db)
    assert process_once(str(db), EXAMPLE) == (before, True)
    assert submit_review(str(db), EXAMPLE["event_id"], {"launch_date": "crm"}) == (
        approved_before,
        True,
    )
    assert apply_reviewed_intake(str(db), EXAMPLE["event_id"]) == (project_before, True)
    engine = engine_for(f"sqlite:///{db}")
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
    engine.dispose()


def test_tenant_and_source_scope(tmp_path):
    db = tmp_path / "tenant.sqlite3"
    migrate(db)
    engine = engine_for(f"sqlite:///{db}")
    repo = SQLiteRepository(engine)
    event = {
        "schema_version": "2",
        "event_id": "same-id",
        "sources": {"form": {"customer_name": "Synthetic"}},
    }
    packet = {"event_id": "same-id", "status": "needs_review"}
    assert repo.put("tenant-a", "form", "same-id", event, packet) == (packet, False)
    assert repo.get("tenant-b", "form", "same-id") is None
    assert repo.get("tenant-a", "crm", "same-id") is None
    assert repo.put("tenant-b", "form", "same-id", {"different": True}, packet)[1] is False
    assert repo.put("tenant-a", "form", "same-id", event, packet) == (packet, True)
    with pytest.raises(IntakeError, match="different payload"):
        repo.put("tenant-a", "form", "same-id", {"changed": True}, packet)
    engine.dispose()


@given(
    st.lists(
        st.tuples(
            st.sampled_from(["tenant-a", "tenant-b", "tenant-c"]),
            st.sampled_from(["form", "crm"]),
            st.integers(min_value=1, max_value=10),
        ),
        min_size=1,
        max_size=25,
    )
)
@settings(max_examples=25, deadline=None)
def test_random_interleavings_never_cross_tenants(operations):
    with tempfile.TemporaryDirectory() as temp:
        db = Path(temp) / "tenant-property.sqlite3"
        migrate(db)
        engine = engine_for(f"sqlite:///{db}")
        repo = SQLiteRepository(engine)
        for tenant, source, number in operations:
            event_id = f"event-{number}"
            packet = {"event_id": event_id, "tenant": tenant}
            repo.put(tenant, source, event_id, packet, packet)
            for other in ("tenant-a", "tenant-b", "tenant-c"):
                found = repo.get(other, source, event_id)
                assert found is None or found["tenant"] == other
        engine.dispose()
