"""The pure core may not reach any of the existing I/O-facing modules."""

from pathlib import Path
import tomllib


def test_core_forbidden_import_contract_lists_legacy_and_new_modules():
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    contract = project["tool"]["importlinter"]["contracts"][0]
    assert contract["source_modules"] == ["intake_translator.core"]
    assert set(contract["forbidden_modules"]) == {
        "intake_translator.ingress",
        "intake_translator.storage",
        "intake_translator.review_layer",
        "intake_translator.outbox",
        "intake_translator.projectors",
        "intake_translator.ai",
        "intake_translator.web",
        "intake_translator.connectors",
        "intake_translator.store",
        "intake_translator.review",
        "intake_translator.mock_crm",
        "intake_translator.http_api",
        "intake_translator.http_api_legacy",
        "intake_translator.dashboard",
        "intake_translator.demo",
        "intake_translator.cli",
    }
