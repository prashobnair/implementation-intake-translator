"""Full-value contract, schema, digest and review-policy acceptance tests."""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from intake_translator.contracts import analyze_v2, load_contract, parse_contract
from intake_translator.core import IntakeError, analyze_intake
from intake_translator.field_service import process_contract_event
from intake_translator.storage.repository import SQLiteRepository
from intake_translator.storage.schema import ReviewVersion, engine_for

ROOT = Path(__file__).parents[1]


def repo(tmp_path):
    db = tmp_path / "fields.sqlite3"
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": f"sqlite:///{db}"},
        check=True,
        capture_output=True,
    )
    return SQLiteRepository(engine_for(f"sqlite:///{db}"))


def test_fc1_default_contract_exact_v1_golden():
    contract = load_contract(ROOT / "config/default-contract.yaml")
    event = json.loads((ROOT / "examples/conflicting-intake.json").read_text())
    expected = analyze_intake(event)
    assert expected == {
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
    }
    packet = analyze_v2({**event, "schema_version": "2"}, contract)
    assert {key: packet[key] for key in expected if key != "schema_version"} == {
        key: value for key, value in expected.items() if key != "schema_version"
    }
    assert packet["schema_version"] == "2"
    assert [(name, contract.sources[name].priority) for name in contract.sources] == [
        ("form", 0),
        ("crm", 1),
        ("notes", 2),
    ]
    assert contract.digest == "raw" and contract.auto_approve_when_unanimous is False
    assert contract.fields["customer_name"].max_len == 200
    with pytest.raises(IntakeError, match="unknown contract option"):
        parse_contract((ROOT / "config/default-contract.yaml").read_text() + "\nextra: true\n")


def test_fc2_marigold_fields_exact_types_and_outputs():
    contract = load_contract(ROOT / "config/marigold-contract.yaml")
    assert tuple(contract.fields) == (
        "customer_name",
        "launch_date",
        "seat_count",
        "region",
        "plan_tier",
        "contract_value",
        "primary_contact_email",
        "integrations_in_scope",
        "data_migration_required",
    )
    assert contract.fields["primary_contact_email"].pii is True
    assert contract.fields["plan_tier"].enum_values == ("starter", "growth", "enterprise")
    event = json.loads((ROOT / "examples/marigold-v2-good.json").read_text())
    packet = analyze_v2(event, contract)
    assert packet["resolved"] == {
        "customer_name": "Marigold Labs",
        "launch_date": "2027-01-12",
        "seat_count": 75,
        "region": "India",
        "plan_tier": "growth",
        "contract_value": "100",
        "primary_contact_email": "hello@example.invalid",
        "integrations_in_scope": ["crm", "projects"],
        "data_migration_required": False,
    }
    assert (
        packet["conflicts"] == {}
        and packet["questions"] == []
        and packet["status"] == "needs_review"
    )
    bad = json.loads((ROOT / "examples/marigold-v2-bad.json").read_text())
    with pytest.raises(IntakeError) as error:
        analyze_v2(bad, contract)
    assert (
        error.value.code == "invalid_field" and error.value.detail == "invalid amount or precision"
    )


def test_fc3_schema_version_1_and_2_dispatch_and_unknown(tmp_path):
    repository = repo(tmp_path)
    contract = load_contract(ROOT / "config/default-contract.yaml")
    event = json.loads((ROOT / "examples/conflicting-intake.json").read_text())
    expected = analyze_intake(event)
    first, replayed = process_contract_event(
        repository, "tenant-a", "form", event, {"tenant-a": contract}
    )
    assert (first, replayed) == (expected, False)
    assert process_contract_event(
        repository, "tenant-a", "form", event, {"tenant-a": contract}
    ) == (expected, True)
    v2 = {**event, "schema_version": "2"}
    second, replayed = process_contract_event(
        repository, "tenant-a", "crm", v2, {"tenant-a": contract}
    )
    assert (
        replayed is False
        and second["schema_version"] == "2"
        and second["conflicts"]["launch_date"] == expected["conflicts"]["launch_date"]
    )
    with pytest.raises(IntakeError) as error:
        process_contract_event(
            repository, "tenant-a", "form", {**event, "schema_version": "3"}, {"tenant-a": contract}
        )
    assert error.value.code == "unsupported_version"
    repository.engine.dispose()


def test_fc4_raw_vs_normalized_digest_exact_replay(tmp_path):
    repository = repo(tmp_path)
    raw_contract = load_contract(ROOT / "config/default-contract.yaml")
    normalized_contract = replace(raw_contract, digest="normalized")
    base = {
        "schema_version": "2",
        "event_id": "raw-1",
        "sources": {"form": {"customer_name": "Marigold Labs", "launch_date": "2027-01-12"}},
    }
    altered = {
        **base,
        "sources": {"form": {"customer_name": "  Marigold   Labs  ", "launch_date": "2027-01-12"}},
    }
    packet, replayed = process_contract_event(
        repository, "tenant-a", "form", base, {"tenant-a": raw_contract}
    )
    assert replayed is False and packet["resolved"]["customer_name"] == "Marigold Labs"
    with pytest.raises(IntakeError) as error:
        process_contract_event(repository, "tenant-a", "form", altered, {"tenant-a": raw_contract})
    assert error.value.code == "event_id_reused"
    base["event_id"] = altered["event_id"] = "normalized-1"
    first, replayed = process_contract_event(
        repository, "tenant-a", "form", base, {"tenant-a": normalized_contract}
    )
    assert replayed is False
    assert process_contract_event(
        repository, "tenant-a", "form", altered, {"tenant-a": normalized_contract}
    ) == (first, True)
    changed = {
        **base,
        "sources": {"form": {"customer_name": "Other Labs", "launch_date": "2027-01-12"}},
    }
    with pytest.raises(IntakeError) as error:
        process_contract_event(
            repository, "tenant-a", "form", changed, {"tenant-a": normalized_contract}
        )
    assert error.value.code == "event_id_reused"
    repository.engine.dispose()


def test_fc5_review_version_and_ai_exclusion_exact(tmp_path):
    repository = repo(tmp_path)
    contract = replace(
        load_contract(ROOT / "config/marigold-contract.yaml"), auto_approve_when_unanimous=True
    )
    event = {
        "schema_version": "2",
        "event_id": "unanimous-1",
        "sources": {
            "form": {"customer_name": "Marigold Labs", "launch_date": "2027-01-12"},
            "crm": {"customer_name": "marigold labs", "launch_date": "2027-01-12"},
        },
    }
    packet, replayed = process_contract_event(
        repository, "tenant-a", "form", event, {"tenant-a": contract}
    )
    assert (
        replayed is False
        and packet["status"] == "approved"
        and packet["review_actor"] == "system:unanimous-policy"
        and packet["review_version"] == 1
    )
    assert process_contract_event(
        repository, "tenant-a", "form", event, {"tenant-a": contract}
    ) == (packet, True)
    with Session(repository.engine) as session:
        row = session.scalar(
            select(ReviewVersion).where(
                ReviewVersion.tenant_id == "tenant-a", ReviewVersion.event_id == "unanimous-1"
            )
        )
        assert row is not None and row.version == 1 and row.actor == "system:unanimous-policy"
        assert json.loads(row.packet_json)["resolved"]["customer_name"] == "Marigold Labs"
    ai_event = {
        **event,
        "event_id": "ai-1",
        "sources": {**event["sources"], "ai": {"customer_name": "Marigold Labs"}},
    }
    held, _ = process_contract_event(
        repository, "tenant-a", "form", ai_event, {"tenant-a": contract}
    )
    assert held["status"] == "needs_review" and held["event_id"] == "ai-1"
    incomplete = {
        **event,
        "event_id": "missing-1",
        "sources": {"form": {"customer_name": "Marigold Labs"}},
    }
    held, _ = process_contract_event(
        repository, "tenant-a", "form", incomplete, {"tenant-a": contract}
    )
    assert held["questions"] == ["What is the launch date?"] and held["status"] == "needs_review"
    repository.engine.dispose()
