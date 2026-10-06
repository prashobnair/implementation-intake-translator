"""Browser-free checks for what the review UI consumes (IIT-UI-1/2 data, static serving)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from intake_translator.review_layer.api import create_review_app

from .seed import NOW, PASSWORD, TENANT, build


def client(tmp_path):
    engine, contracts = build(tmp_path / "api.sqlite3")
    app = create_review_app(engine, contracts, clock=lambda: NOW)
    web = TestClient(app, base_url="https://testserver")
    assert web.post("/login", json={"username": "rita", "password": PASSWORD}).status_code == 200
    return web


def test_ui_assets_are_served_with_a_strict_csp_and_nothing_else(tmp_path):
    web = client(tmp_path)
    page = web.get("/ui/")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert page.headers["content-security-policy"] == "default-src 'self'; frame-ancestors 'none'"
    assert page.headers["x-content-type-options"] == "nosniff"
    assert web.get("/ui/app.js").headers["content-type"].startswith("text/javascript")
    assert web.get("/ui/app.css").status_code == 200
    assert web.get("/ui/../api.py").status_code == 404
    assert web.get("/ui/secrets.txt").json() == {"detail": "not_found"}


def test_ui1_queue_rows_carry_filter_facts(tmp_path):
    body = client(tmp_path).get(f"/tenants/{TENANT}/cases").json()
    assert body["now"] == "2027-01-10T12:00:00+00:00"
    facts = {
        c["event_id"]: (
            c["customer"],
            c["received_at"],
            c["has_ai"],
            c["has_override"],
            c["status"],
        )
        for c in body["cases"]
    }
    assert facts == {
        "case-ai": ("Alder Freight", "2027-01-09T06:00:00+00:00", True, False, "needs_review"),
        "case-conflict": (
            "Marigold Labs",
            "2027-01-10T11:00:00+00:00",
            False,
            False,
            "needs_review",
        ),
        "case-done": (
            "Birch Cooperative",
            "2027-01-08T10:00:00+00:00",
            False,
            True,
            "approved",
        ),
        "case-missing": (
            "Juniper Works",
            "2027-01-10T06:00:00+00:00",
            False,
            False,
            "needs_review",
        ),
    }


def test_ui2_case_view_lists_fields_source_trust_and_role(tmp_path):
    view = client(tmp_path).get(f"/tenants/{TENANT}/cases/case-missing").json()
    assert [(f["name"], f["required"]) for f in view["fields"]][:3] == [
        ("customer_name", True),
        ("launch_date", True),
        ("seat_count", False),
    ]
    assert view["sources"] == {"form": "human", "crm": "system", "notes": "human", "ai": "ai"}
    assert (view["role"], view["received_at"]) == ("reviewer", "2027-01-10T06:00:00+00:00")
