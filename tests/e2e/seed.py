"""Synthetic review-UI world shared by the Playwright tests and the README screenshots."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy.orm import Session

from intake_translator.contracts import load_contract
from intake_translator.field_service import process_contract_event
from intake_translator.review_layer import accounts, service
from intake_translator.storage.repository import SqlRepository
from intake_translator.storage.schema import ProcessedEvent, RawEvent, engine_for

ROOT = Path(__file__).parents[2]
NOW = datetime(2027, 1, 10, 12, 0, tzinfo=timezone.utc)
PASSWORD = "correct horse battery"
TENANT = "tenant-a"


def event(event_id: str, **sources: dict[str, str]) -> dict[str, object]:
    return {"schema_version": "2", "event_id": event_id, "sources": sources}


def build(db: Path):
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": f"sqlite:///{db}"},
        check=True,
        capture_output=True,
    )
    contract = load_contract(ROOT / "config/marigold-contract.yaml")
    contracts = {TENANT: contract, "tenant-b": contract}
    repo = SqlRepository(engine_for(f"sqlite:///{db}"))
    cases = {
        "case-conflict": (
            1,
            event(
                "case-conflict",
                form={"customer_name": "Marigold Labs", "launch_date": "2027-02-01"},
                crm={"customer_name": "Marigold Labs Inc", "launch_date": "2027-02-01"},
            ),
        ),
        "case-missing": (
            6,
            event("case-missing", form={"customer_name": "Juniper Works"}),
        ),
        "case-ai": (
            30,
            event(
                "case-ai",
                form={"customer_name": "Alder Freight", "launch_date": "2027-03-01"},
                ai={"customer_name": "Alder Freight", "launch_date": "2027-03-15"},
            ),
        ),
        "case-done": (
            50,
            event(
                "case-done",
                form={"customer_name": "Birch Cooperative", "launch_date": "2027-01-20"},
                crm={"customer_name": "Birch Co-op", "launch_date": "2027-01-20"},
            ),
        ),
    }
    for event_id, (hours, payload) in cases.items():
        process_contract_event(repo, TENANT, "form", payload, contracts)
        with Session(repo.engine) as session, session.begin():
            session.add(
                RawEvent(
                    tenant_id=TENANT,
                    source="form",
                    event_id=event_id,
                    received_at=(NOW - timedelta(hours=hours)).replace(tzinfo=None),
                    body_ciphertext=None,
                    payload_sha256="0" * 64,
                    auth_mode="hmac",
                )
            )
    # Give the AI candidate a quoted passage, the way notes extraction will store it.
    with Session(repo.engine) as session, session.begin():
        row = session.get(ProcessedEvent, (TENANT, "form", "case-ai"))
        packet = json.loads(row.packet_json)
        for group in packet["candidates"].values():
            for option in group:
                if option["source"] == "ai" and option["value"] == "2027-03-15":
                    option["quote"] = "Customer said they now expect to launch on 2027-03-15."
        row.packet_json = json.dumps(packet, sort_keys=True)
    accounts.create_account(
        repo.engine, "rita", PASSWORD, {TENANT: "reviewer", "tenant-b": "viewer"}
    )
    service.submit_decisions(
        repo.engine,
        TENANT,
        "case-done",
        "rita",
        "reviewer",
        {
            "customer_name": {
                "type": "override",
                "value": "Birch Cooperative",
                "rationale": "Legal name confirmed against the signed order form.",
            }
        },
        contract,
        expected_version=0,
        now=NOW,
    )
    return repo.engine, contracts
