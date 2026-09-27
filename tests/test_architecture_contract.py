"""The core stays import-pure, and Postgres path requests a locked read."""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from intake_translator.storage.schema import ProcessedEvent


def test_core_has_no_service_or_storage_imports():
    core = (Path(__file__).parents[1] / "src/intake_translator/core.py").read_text()
    assert "from .storage" not in core
    assert "from .web" not in core
    assert "from .ingress" not in core


def test_postgres_event_lookup_uses_for_update():
    statement = (
        select(ProcessedEvent)
        .where(
            ProcessedEvent.tenant_id == "tenant-a",
            ProcessedEvent.source == "form",
            ProcessedEvent.event_id == "demo",
        )
        .with_for_update()
    )
    sql = str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert "FOR UPDATE" in sql
    assert "tenant-a" in sql and "form" in sql and "demo" in sql
