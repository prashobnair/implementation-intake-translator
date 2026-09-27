"""Synthetic field-contract and schema compatibility checks."""

import copy
import json
from pathlib import Path

import pytest

from intake_translator.contracts import analyze_v2, load_contract, parse_contract
from intake_translator.core import IntakeError, analyze_intake

ROOT = Path(__file__).parents[1]


def test_default_contract_reproduces_v1_packet():
    contract = load_contract(ROOT / "config/default-contract.yaml")
    legacy = json.loads((ROOT / "examples/conflicting-intake.json").read_text())
    old = analyze_intake(legacy)
    newer = analyze_v2({**legacy, "schema_version": "2"}, contract)
    for key in (
        "event_id",
        "status",
        "resolved",
        "display",
        "conflicts",
        "questions",
        "source_count",
    ):
        assert newer[key] == old[key]


def test_marigold_fields_and_invalid_values():
    contract = load_contract(ROOT / "config/marigold-contract.yaml")
    event = {
        "schema_version": "2",
        "event_id": "demo-v2",
        "sources": {
            "form": {
                "customer_name": "Marigold Labs",
                "launch_date": "2027-01-12",
                "plan_tier": "growth",
                "contract_value": "100.00",
                "primary_contact_email": "hello@example.invalid",
                "integrations_in_scope": ["crm", "projects"],
                "data_migration_required": False,
            },
            "crm": {
                "customer_name": "marigold labs",
                "launch_date": "2027-01-12",
                "contract_value": "100",
            },
        },
    }
    packet = analyze_v2(event, contract)
    assert packet["conflicts"] == {}
    assert packet["resolved"]["contract_value"] == "100"
    assert packet["status"] == "needs_review"
    bad = copy.deepcopy(event)
    bad["sources"]["form"]["contract_value"] = "100.001"
    with pytest.raises(IntakeError, match="invalid amount"):
        analyze_v2(bad, contract)
    bad["sources"]["form"]["contract_value"] = 100.0
    with pytest.raises(IntakeError, match="decimal field"):
        analyze_v2(bad, contract)


def test_schema_and_contract_rejection():
    contract = load_contract(ROOT / "config/default-contract.yaml")
    with pytest.raises(IntakeError, match="unsupported_version"):
        analyze_v2({"schema_version": "3"}, contract)
    with pytest.raises(IntakeError, match="fields and sources"):
        parse_contract("[]")
    with pytest.raises(IntakeError, match="unknown contract option"):
        parse_contract(
            "fields: {x: {type: text}}\nsources: {x: {priority: 0, trust: human}}\nunknown: yes"
        )
