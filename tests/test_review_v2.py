from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys

from intake_translator.contracts import analyze_v2, load_contract
from intake_translator.storage.reviews import maybe_auto_approve
from intake_translator.storage.schema import engine_for

ROOT = Path(__file__).parents[1]


def test_unanimous_policy_records_review_and_excludes_ai(tmp_path):
    db = tmp_path / "reviews.sqlite3"
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": f"sqlite:///{db}"},
        check=True,
        capture_output=True,
    )
    engine = engine_for(f"sqlite:///{db}")
    default = load_contract(ROOT / "config/marigold-contract.yaml")
    contract = replace(default, auto_approve_when_unanimous=True)
    event = {
        "schema_version": "2",
        "event_id": "demo-safe",
        "sources": {
            "form": {"customer_name": "Marigold Labs", "launch_date": "2027-01-12"},
            "crm": {"customer_name": "marigold labs", "launch_date": "2027-01-12"},
        },
    }
    packet = analyze_v2(event, contract)
    approved = maybe_auto_approve(engine, "tenant-a", packet, contract)
    assert approved["review_actor"] == "system:unanimous-policy"
    assert approved["review_version"] == 1
    ai_event = {
        **event,
        "event_id": "demo-ai",
        "sources": {**event["sources"], "ai": {"customer_name": "Marigold Labs"}},
    }
    ai_packet = analyze_v2(ai_event, contract)
    assert maybe_auto_approve(engine, "tenant-a", ai_packet, contract)["status"] == "needs_review"
    engine.dispose()
