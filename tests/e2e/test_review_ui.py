"""Playwright acceptance for the review UI (IIT-UI-1..3). Set RUN_E2E=1; CI does."""

from __future__ import annotations

from contextlib import closing
import os
from pathlib import Path
import socket
import threading
import time

import pytest

from .seed import NOW, PASSWORD, build

if not os.environ.get("RUN_E2E"):
    pytest.skip("set RUN_E2E=1 to run browser tests", allow_module_level=True)

import uvicorn
from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import Page, expect, sync_playwright

from intake_translator.review_layer.api import create_review_app

SHOTS = Path(__file__).parents[2] / "docs" / "screenshots"


@pytest.fixture()
def server(tmp_path):
    engine, contracts = build(tmp_path / "ui.sqlite3")
    app = create_review_app(engine, contracts, secure_cookies=False, clock=lambda: NOW)
    with closing(socket.socket()) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    while not srv.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    thread.join(5)


@pytest.fixture()
def page(server):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page(viewport={"width": 1100, "height": 760})
        pg.goto(server + "/ui/")
        yield pg
        browser.close()


def sign_in(page: Page) -> None:
    page.get_by_label("Username").fill("rita")
    page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("heading", name="Review queue")).to_be_visible()


def rows(page: Page) -> list[str]:
    return page.locator("tbody tr").evaluate_all("rs => rs.map(r => r.dataset.case)")


def test_ui1_queue_filters_sla_badges_and_customer_search(page):
    sign_in(page)
    assert rows(page) == ["case-ai", "case-conflict", "case-done", "case-missing"]
    expect(page.locator("#count")).to_have_text("4 of 4 cases")
    badge = lambda case: page.locator(f'tr[data-case="{case}"] .badge').inner_text()  # noqa: E731
    assert [badge(c) for c in rows(page)] == [
        "SLA: breached",
        "SLA: on time",
        "SLA: done",
        "SLA: at risk",
    ]
    page.get_by_label("Status").select_option("approved")
    assert rows(page) == ["case-done"]
    page.get_by_label("Status").select_option("")
    page.get_by_label("Age").select_option("gt24")
    assert rows(page) == ["case-ai", "case-done"]
    page.get_by_label("Age").select_option("4to24")
    assert rows(page) == ["case-missing"]
    page.get_by_label("Age").select_option("")
    page.get_by_label("AI source").select_option("yes")
    assert rows(page) == ["case-ai"]
    page.get_by_label("AI source").select_option("")
    page.get_by_label("Override").select_option("yes")
    assert rows(page) == ["case-done"]
    page.get_by_label("Override").select_option("")
    page.get_by_label("Customer search").fill("juniper")
    assert rows(page) == ["case-missing"]
    expect(page.locator("#count")).to_have_text("1 of 4 cases")
    page.get_by_label("Tenant").select_option("tenant-b")
    expect(page.locator("#count")).to_have_text("0 of 0 cases")
    assert rows(page) == []


def test_ui2_matrix_marks_conflict_and_missing_and_shows_evidence(page):
    sign_in(page)
    page.get_by_role("link", name="case-conflict").click()
    conflict = page.locator('tr[data-field="customer_name"]')
    assert conflict.locator("th .tag").inner_text() == "Conflict"
    assert conflict.locator("td.conflict").count() == 4
    cells = page.locator('tr[data-field="customer_name"] td').all_inner_texts()
    assert "Marigold Labs\nform (human)" in cells[2]  # columns: ai, crm, form, notes
    assert "Marigold Labs Inc\ncrm (system)" in cells[1]
    assert "fetched 2027-01-10T11:00:00+00:00" in cells[2]
    assert cells[0] == "none"
    page.get_by_role("link", name="Back to queue").click()
    page.get_by_role("link", name="case-missing").click()
    missing = page.locator('tr[data-field="launch_date"]')
    assert missing.locator("th .tag").inner_text() == "Required, missing"
    assert page.locator('tr[data-field="region"] th .tag').inner_text() == "Optional, empty"
    page.get_by_role("link", name="Back to queue").click()
    page.get_by_role("link", name="case-ai").click()
    row = page.locator('tr[data-field="launch_date"]')
    button = row.get_by_role("button", name="Evidence").first
    expect(button).to_have_attribute("aria-expanded", "false")
    button.click()
    expect(button).to_have_attribute("aria-expanded", "true")
    assert row.locator("mark").inner_text() == "2027-03-15"
    assert (
        row.locator("blockquote").inner_text()
        == "Customer said they now expect to launch on 2027-03-15."
    )
    page.screenshot(path=str(SHOTS / "2-case-matrix.png"), full_page=True)


def test_ui2_decisions_and_stale_version_message(page):
    sign_in(page)
    page.get_by_role("link", name="case-conflict").click()
    page.get_by_role("radio", name="Choose crm: Marigold Labs Inc").check()
    page.get_by_role("button", name="Submit decisions").click()
    expect(page.locator("#case-status")).to_have_text("approved")
    page.get_by_role("link", name="Back to queue").click()
    expect(page.locator('tr[data-case="case-conflict"] td').nth(2)).to_have_text("approved")


def test_ui2_override_needs_rationale_and_missing_field_decision(page):
    sign_in(page)
    page.get_by_role("link", name="case-missing").click()
    page.get_by_role("radio", name="Override with a written value").check()
    page.get_by_label("Override value").fill("2027-04-01")
    page.get_by_label("Override rationale (20+ characters)").fill("too short")
    page.get_by_role("button", name="Submit decisions").click()
    expect(page.locator("#msg")).to_have_text("Could not save (invalid_review).")
    page.get_by_label("Override rationale (20+ characters)").fill(
        "Date confirmed by phone with the customer."
    )
    page.get_by_role("button", name="Submit decisions").click()
    expect(page.locator("#case-status")).to_have_text("approved")


def test_ui3_keyboard_only_decision(page):
    sign_in(page)
    page.get_by_role("link", name="case-conflict").click()
    page.get_by_role("radio", name="Choose form: Marigold Labs").focus()
    page.keyboard.press("ArrowDown")  # radio group arrow keys move and select
    page.keyboard.press("ArrowUp")
    focused = page.evaluate("document.activeElement.id")
    assert focused == "d-customer_name-src:form"
    assert page.get_by_role("radio", name="Choose form: Marigold Labs").is_checked()
    submit = page.get_by_role("button", name="Submit decisions")
    submit.focus()
    page.keyboard.press("Enter")
    expect(page.locator("#case-status")).to_have_text("approved")


@pytest.mark.parametrize("view", ["login", "queue", "conflict", "approved"])
def test_ui3_axe_has_no_violations(server, view):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page(viewport={"width": 1100, "height": 760})
        pg.goto(server + "/ui/")
        if view != "login":
            sign_in(pg)
        if view == "conflict":
            pg.get_by_role("link", name="case-conflict").click()
            expect(pg.get_by_role("heading", name="Case case-conflict")).to_be_visible()
        if view == "approved":
            pg.get_by_role("link", name="case-done").click()
            expect(pg.get_by_role("heading", name="Case case-done")).to_be_visible()
        if view == "queue":
            pg.screenshot(path=str(SHOTS / "1-queue.png"), full_page=True)
        result = Axe().run(pg)
        assert result.violations_count == 0, result.generate_report()
        browser.close()
