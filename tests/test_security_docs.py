"""Pin the documented auth boundary and STRIDE coverage to the security slice."""

from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_sec3_zoho_adr_and_api_contract_exact():
    adr = (ROOT / "docs/adr/0003-zoho-webhook-auth.md").read_text()
    api = (ROOT / "docs/API_CONTRACTS.md").read_text()
    assert "# ADR-0003: Zoho CRM webhook authentication" in adr
    assert "`X-Intake-Token` custom header" in adr
    assert "`auth_mode: shared_token`" in adr
    assert "URL parameters apply only to GET" not in adr  # exact source wording is cited below
    assert "`url_parameters` section says these apply only to GET" in adr
    assert "`url_parameters` section says these apply only to GET" in api
    assert "Do not present a URL token as a supported Zoho POST setup" in api
    assert "https://www.zoho.com/crm/developer/docs/api/v8/create-webhook.html" in api


def test_sec7_stride_threat_model_covers_required_scenarios():
    text = (ROOT / "docs/THREAT_MODEL.md").read_text()
    assert "| STRIDE threat | Boundary | Mitigation | Residual risk / test |" in text
    for threat in (
        "Spoofed webhooks",
        "Replay or changed event",
        "Tenant confusion",
        "Reviewer impersonation",
        "Prompt injection through notes",
        "Outbox double-apply",
    ):
        assert f"| {threat} |" in text
