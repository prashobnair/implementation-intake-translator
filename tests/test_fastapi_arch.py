"""Exact v1 API parity while the legacy stdlib adapter is retained."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from intake_translator.web.app import create_app

ROOT = Path(__file__).parents[1]


def test_fastapi_v1_packet_and_replay(tmp_path):
    client = TestClient(create_app(str(tmp_path / "events.sqlite3")))
    assert client.get("/health").json() == {"status": "ok", "service": "intake-translator"}
    event = json.loads((ROOT / "examples/conflicting-intake.json").read_text())
    first = client.post("/intakes", json=event)
    assert first.status_code == 201
    assert first.json() == {
        "schema_version": "1",
        "event_id": "fictional-nexaflow-deal-001",
        "status": "needs_review",
        "resolved": {"customer_name": "Acme Sample Co", "seat_count": 75, "region": "India"},
        "display": "first_source_priority",
        "conflicts": {
            "launch_date": [
                {"source": "form", "value": "2026-11-02"},
                {"source": "crm", "value": "2026-11-16"},
            ]
        },
        "questions": ["Which launch date is correct? Confirm against the source records."],
        "source_count": 3,
        "replayed": False,
    }
    again = client.post("/intakes", json=event)
    assert again.status_code == 200
    assert again.json() == {**first.json(), "replayed": True}
    assert (
        client.post("/intakes", content=b"{}", headers={"content-type": "text/plain"}).status_code
        == 415
    )
    assert (
        client.post(
            "/intakes", content=b"x" * 16385, headers={"content-type": "application/json"}
        ).status_code
        == 413
    )
