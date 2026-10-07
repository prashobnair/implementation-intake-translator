"""Exact-value acceptance tests for review workflow v2 (IIT-RV-1..7). Synthetic data only."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from intake_translator.contracts import load_contract
from intake_translator.core import IntakeError
from intake_translator.field_service import process_contract_event
from intake_translator.ingress.api import SourceAuth, create_ingress_app
from intake_translator.ingress.security import TokenBucket
from intake_translator.review import submit_review
from intake_translator.review_layer import accounts, audit, service
from intake_translator.review_layer.api import create_review_app
from intake_translator.review_layer.oidc import OidcProvider
from intake_translator.review_layer.roles import ROLES, allowed
from intake_translator.storage.repository import SqlRepository
from intake_translator.storage.schema import Amendment, AuditEntry, ReviewVersion, engine_for

ROOT = Path(__file__).parents[1]
BASE = load_contract(ROOT / "config/default-contract.yaml")
PASSWORD = "correct horse battery"
T = "tenant-a"


def upgrade(db: Path, revision: str = "head") -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": f"sqlite:///{db}"},
        check=True,
        capture_output=True,
    )


def event(event_id: str, **sources: dict[str, str]) -> dict[str, object]:
    return {"schema_version": "2", "event_id": event_id, "sources": sources}


def world(tmp_path, contract=BASE):
    db = tmp_path / "review.sqlite3"
    upgrade(db)
    repo = SqlRepository(engine_for(f"sqlite:///{db}"))
    contracts = {T: contract, "tenant-b": contract}
    seeds = [
        event(
            "case-conflict",
            form={"customer_name": "Marigold Labs", "launch_date": "2027-01-12"},
            crm={"customer_name": "Marigold Labs Inc", "launch_date": "2027-01-12"},
        ),
        event("case-missing", form={"customer_name": "Marigold Labs"}),
        event(
            "case-agree",
            form={"customer_name": "Marigold Labs", "launch_date": "2027-01-12"},
            crm={"customer_name": "marigold labs", "launch_date": "2027-01-12"},
        ),
    ]
    for item in seeds:
        process_contract_event(repo, T, "form", item, contracts)
    process_contract_event(repo, "tenant-b", "form", seeds[2], contracts)
    for name, role in (
        ("vera", "viewer"),
        ("rita", "reviewer"),
        ("alma", "approver"),
        ("ada", "admin"),
    ):
        accounts.create_account(repo.engine, name, PASSWORD, {T: role})
    return repo.engine, contracts


def client_for(engine, contracts, **options):
    app = create_review_app(engine, contracts, **options)
    return TestClient(app, base_url="https://testserver", raise_server_exceptions=False)


def login(client, name="rita"):
    response = client.post("/login", json={"username": name, "password": PASSWORD})
    assert response.status_code == 200
    return response.json()["csrf_token"]


def decide(client, csrf, event_id, decisions, version=0):
    return client.post(
        f"/tenants/{T}/cases/{event_id}/decisions",
        json={"decisions": decisions, "expected_version": version},
        headers={"X-CSRF-Token": csrf},
    )


CHOOSE = {"customer_name": {"type": "choose_source", "source": "crm"}}


# ---- IIT-RV-1: authentication -------------------------------------------------


def test_rv1_argon2_hash_and_password_policy(tmp_path):
    engine, _ = world(tmp_path)
    with engine.connect() as conn:
        stored = conn.execute(text("SELECT password_hash FROM accounts WHERE username='rita'"))
        digest = stored.scalar_one()
    assert digest.startswith("$argon2id$") and PASSWORD not in digest
    assert accounts.verify_login(engine, "rita", PASSWORD) is True
    assert accounts.verify_login(engine, "rita", PASSWORD + "x") is False
    assert accounts.verify_login(engine, "nobody", PASSWORD) is False
    with pytest.raises(IntakeError) as short:
        accounts.create_account(engine, "newbie", "short", {T: "viewer"})
    assert (short.value.code, short.value.detail) == (
        "invalid_account",
        "password needs at least 12 characters",
    )
    with pytest.raises(IntakeError) as dup:
        accounts.create_account(engine, "rita", PASSWORD, {T: "viewer"})
    assert dup.value.code == "account_exists"


@pytest.mark.parametrize(
    "username", ["cli:local", "system:admin", ":reviewer", "reviewer:", "a:b:c"]
)
@pytest.mark.parametrize("password", [PASSWORD, None])
def test_rv1_create_account_rejects_colon_usernames_without_writes(tmp_path, username, password):
    db = tmp_path / "accounts.sqlite3"
    upgrade(db)
    engine = engine_for(f"sqlite:///{db}")
    with pytest.raises(IntakeError) as rejected:
        accounts.create_account(engine, username, password, {T: "admin"})
    assert (rejected.value.code, rejected.value.detail) == (
        "invalid_account",
        "username must be 1-100 ASCII characters without colons",
    )
    with engine.connect() as conn:
        assert conn.execute(text("SELECT username FROM accounts")).all() == []
        assert conn.execute(text("SELECT username FROM memberships")).all() == []
    assert accounts.verify_login(engine, username, PASSWORD) is False
    assert accounts.role_for(engine, username, T) is None


def test_rv1_login_cookie_flags_and_uniform_failure(tmp_path):
    engine, contracts = world(tmp_path)
    client = client_for(engine, contracts)
    ok = client.post("/login", json={"username": "rita", "password": PASSWORD})
    cookie = ok.headers["set-cookie"].lower()
    assert ok.json()["memberships"] == {T: "reviewer"}
    assert all(flag in cookie for flag in ("httponly", "secure", "samesite=lax", "path=/"))
    wrong = client.post("/login", json={"username": "rita", "password": "wrong password!!"})
    unknown = client.post("/login", json={"username": "ghost", "password": PASSWORD})
    assert [(r.status_code, r.json()) for r in (wrong, unknown)] == [
        (401, {"detail": "invalid_credentials"})
    ] * 2
    assert client.post("/login", json={"username": 1, "password": 2}).status_code == 401


def test_rv1_csrf_required_on_unsafe_requests_and_logout(tmp_path):
    engine, contracts = world(tmp_path)
    client = client_for(engine, contracts)
    csrf = login(client)
    url = f"/tenants/{T}/cases/case-conflict/decisions"
    body = {"decisions": CHOOSE, "expected_version": 0}
    missing = client.post(url, json=body)
    wrong = client.post(url, json=body, headers={"X-CSRF-Token": "x" * 43})
    assert [(r.status_code, r.json()) for r in (missing, wrong)] == [
        (403, {"detail": "csrf_failed"})
    ] * 2
    assert client.get(f"/tenants/{T}/cases").status_code == 200  # safe methods need no token
    assert client.post(url, json=body, headers={"X-CSRF-Token": csrf}).status_code == 201
    assert client.post("/logout").status_code == 403
    assert client.post("/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
    assert client.get("/me").status_code == 401


def test_rv1_session_expiry_and_login_rate_limit(tmp_path):
    engine, contracts = world(tmp_path)
    clock = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    client = client_for(engine, contracts, session_ttl_seconds=60, clock=lambda: clock[0])
    login(client)
    assert client.get("/me").json() == {"username": "rita", "memberships": {T: "reviewer"}}
    clock[0] += timedelta(seconds=61)
    assert client.get("/me").status_code == 401
    limited = client_for(
        engine, contracts, login_bucket=TokenBucket(capacity=2, refill_per_second=0.0)
    )
    codes = [
        limited.post("/login", json={"username": "rita", "password": "bad password 12"}).status_code
        for _ in range(3)
    ]
    assert codes == [401, 401, 429]


def test_rv1_oidc_fake_idp_state_pkce_and_linking(tmp_path):
    engine, contracts = world(tmp_path)
    seen = {}

    def exchange(code: str, verifier: str) -> str:
        seen["verifier"] = verifier
        return {"good-code": "gh-1001", "stranger-code": "gh-9999"}[code]

    provider = OidcProvider("github", "client-1", "https://app.example/cb", exchange)
    accounts.link_oidc(engine, "github", "gh-1001", "rita")
    client = client_for(engine, contracts, oidc_providers={"github": provider})
    start = client.get("/auth/oidc/github/start", follow_redirects=False)
    target = urlparse(start.headers["location"])
    query = parse_qs(target.query)
    assert (start.status_code, target.netloc, target.path) == (
        302,
        "github.com",
        "/login/oauth/authorize",
    )
    assert (query["client_id"], query["code_challenge_method"]) == (["client-1"], ["S256"])
    state = query["state"][0]
    done = client.get(f"/auth/oidc/github/callback?code=good-code&state={state}")
    assert (done.status_code, done.json()["username"]) == (200, "rita")
    assert len(seen["verifier"]) == 64 and client.get("/me").status_code == 200
    reused = client.get(f"/auth/oidc/github/callback?code=good-code&state={state}")
    forged = client.get("/auth/oidc/github/callback?code=good-code&state=forged")
    assert [(r.status_code, r.json()) for r in (reused, forged)] == [
        (400, {"detail": "invalid_state"})
    ] * 2
    second = parse_qs(
        urlparse(
            client.get("/auth/oidc/github/start", follow_redirects=False).headers["location"]
        ).query
    )
    stranger = client.get(
        f"/auth/oidc/github/callback?code=stranger-code&state={second['state'][0]}"
    )
    assert (stranger.status_code, stranger.json()) == (403, {"detail": "forbidden"})
    assert client.get("/auth/oidc/google/start", follow_redirects=False).status_code == 404
    with pytest.raises(ValueError):
        OidcProvider("gitlab", "c", "https://x", exchange)


# ---- IIT-RV-2: roles ------------------------------------------------------------


def test_rv2_authorization_matrix_exact():
    expected = {
        "view": [False, True, True, True, True],
        "decide": [False, False, True, True, True],
        "amend": [False, False, True, True, True],
        "override_two_person": [False, False, False, True, True],
        "audit_verify": [False, False, False, False, True],
    }
    for action, row in expected.items():
        got = [allowed(role, action) for role in (None, *ROLES)]
        assert got == row, action
    assert allowed("reviewer", "unknown_action") is False and ROLES == (
        "viewer",
        "reviewer",
        "approver",
        "admin",
    )


def test_rv2_http_roles_and_tenant_isolation(tmp_path):
    engine, contracts = world(tmp_path)
    viewer = client_for(engine, contracts)
    csrf = login(viewer, "vera")
    assert viewer.get(f"/tenants/{T}/cases/case-conflict").status_code == 200
    denied = decide(viewer, csrf, "case-conflict", CHOOSE)
    assert (denied.status_code, denied.json()) == (403, {"detail": "forbidden"})
    accounts.create_account(engine, "outsider", PASSWORD, {"tenant-b": "admin"})
    outsider = client_for(engine, contracts)
    out_csrf = login(outsider, "outsider")
    hidden = outsider.get(f"/tenants/{T}/cases")
    assert (hidden.status_code, hidden.json()) == (404, {"detail": "unknown_route"})
    assert decide(outsider, out_csrf, "case-conflict", CHOOSE).status_code == 404
    own = outsider.get("/tenants/tenant-b/cases").json()
    assert own["cases"] == [
        {
            "event_id": "case-agree",
            "status": "needs_review",
            "version": 0,
            "amendment": None,
            "customer": "Marigold Labs",
            "received_at": None,
            "has_ai": False,
            "has_override": False,
        }
    ]


def test_rv2_two_person_override_needs_approver(tmp_path):
    contract = replace(BASE, two_person_override=True)
    engine, contracts = world(tmp_path, contract)
    override = {
        "launch_date": {
            "type": "override",
            "value": "2027-02-01",
            "rationale": "Customer confirmed by phone on a call",
        }
    }
    reviewer = client_for(engine, contracts)
    r_csrf = login(reviewer, "rita")
    blocked = decide(reviewer, r_csrf, "case-missing", override)
    assert (blocked.status_code, blocked.json()) == (403, {"detail": "forbidden"})
    approver = client_for(engine, contracts)
    ok = decide(approver, login(approver, "alma"), "case-missing", override)
    assert ok.status_code == 201 and ok.json()["resolved"]["launch_date"] == "2027-02-01"
    assert ok.json()["review_actor"] == "alma"
    # Without the tenant option a reviewer may override.
    (tmp_path / "plain").mkdir()
    engine2, contracts2 = world(tmp_path / "plain")
    plain = client_for(engine2, contracts2)
    assert decide(plain, login(plain, "rita"), "case-missing", override).status_code == 201


# ---- IIT-RV-3: decision types ---------------------------------------------------


def test_rv3_choose_override_defer_and_approvability(tmp_path):
    engine, contracts = world(tmp_path)
    client = client_for(engine, contracts)
    csrf = login(client)
    short = {"launch_date": {"type": "override", "value": "2027-02-01", "rationale": "x" * 19}}
    bad = decide(client, csrf, "case-missing", short)
    assert (bad.status_code, bad.json()) == (422, {"detail": "invalid_review"})
    with pytest.raises(IntakeError) as why:
        service.submit_decisions(
            engine, T, "case-missing", "rita", "reviewer", short, BASE, expected_version=0
        )
    assert why.value.detail == "override rationale needs 20+ characters"
    exact = {"launch_date": {"type": "override", "value": "2027-02-01", "rationale": "x" * 20}}
    approved = decide(client, csrf, "case-missing", exact)
    body = approved.json()
    assert (approved.status_code, body["status"], body["questions"]) == (201, "approved", [])
    assert body["resolved"] == {"customer_name": "Marigold Labs", "launch_date": "2027-02-01"}
    chosen = decide(client, csrf, "case-conflict", CHOOSE)
    assert chosen.json()["resolved"]["customer_name"] == "Marigold Labs Inc"
    assert chosen.json()["status"] == "approved"


def test_rv3_defer_blocks_approval_and_incomplete_is_rejected(tmp_path):
    engine, contracts = world(tmp_path)
    client = client_for(engine, contracts)
    csrf = login(client)
    deferred = {"customer_name": {"type": "defer", "question": "Which legal entity signs?"}}
    result = decide(client, csrf, "case-conflict", deferred)
    body = result.json()
    assert (result.status_code, body["status"], body["questions"]) == (
        201,
        "needs_customer_input",
        ["Which legal entity signs?"],
    )
    assert body["resolved"].get("customer_name") is None
    assert client.get(f"/tenants/{T}/cases/case-conflict").json()["status"] == "deferred"
    for decisions in (
        {},
        {"region": CHOOSE["customer_name"]},
        {**CHOOSE, "launch_date": CHOOSE["customer_name"]},
    ):
        r = decide(client, csrf, "case-conflict", decisions, version=1)
        assert (r.status_code, r.json()) == (422, {"detail": "invalid_review"})
    bad_kind = decide(
        client, csrf, "case-conflict", {"customer_name": {"type": "guess"}}, version=1
    )
    stale_source = decide(
        client,
        csrf,
        "case-conflict",
        {"customer_name": {"type": "choose_source", "source": "notes"}},
        version=1,
    )
    assert [r.status_code for r in (bad_kind, stale_source)] == [422, 422]
    final = decide(client, csrf, "case-conflict", CHOOSE, version=1)
    assert (final.status_code, final.json()["status"]) == (201, "approved")
    replay = decide(client, csrf, "case-conflict", CHOOSE, version=2)
    assert (replay.status_code, replay.json()) == (409, {"detail": "already_approved"})


# ---- IIT-RV-4: versions and concurrency ---------------------------------------


def test_rv4_version_rows_parent_and_stale_409(tmp_path):
    engine, contracts = world(tmp_path)
    client = client_for(engine, contracts)
    csrf = login(client)
    deferred = {"customer_name": {"type": "defer", "question": "Which entity?"}}
    assert decide(client, csrf, "case-conflict", deferred).status_code == 201
    stale = decide(client, csrf, "case-conflict", CHOOSE, version=0)
    assert (stale.status_code, stale.json()) == (
        409,
        {"detail": "review_conflict", "current_version": 1},
    )
    assert decide(client, csrf, "case-conflict", CHOOSE, version=1).status_code == 201
    with Session(engine) as session:
        rows = session.scalars(
            select(ReviewVersion)
            .where(ReviewVersion.event_id == "case-conflict")
            .order_by(ReviewVersion.version)
        ).all()
        facts = [
            (r.version, r.parent_version, r.actor, r.state, r.created_at is not None) for r in rows
        ]
        assert facts == [(1, None, "rita", "deferred", True), (2, 1, "rita", "approved", True)]
        assert json.loads(rows[1].decisions_json) == CHOOSE
        assert json.loads(rows[1].packet_json)["status"] == "approved"


def test_rv4_two_reviewers_race_one_wins_one_gets_409(tmp_path):
    engine, contracts = world(tmp_path)
    calls = [("rita", "crm"), ("alma", "form")]

    def submit(who):
        name, source = who
        role = "reviewer" if name == "rita" else "approver"
        try:
            service.submit_decisions(
                engine,
                T,
                "case-conflict",
                name,
                role,
                {"customer_name": {"type": "choose_source", "source": source}},
                BASE,
                expected_version=0,
            )
            return "ok"
        except service.ReviewConflict as exc:
            return f"{exc.code}:{exc.current_version}"
        except IntakeError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(submit, calls))
    assert outcomes == ["ok", "review_conflict:1"]
    with Session(engine) as session:
        assert (
            len(
                session.scalars(
                    select(ReviewVersion).where(ReviewVersion.event_id == "case-conflict")
                ).all()
            )
            == 1
        )


# ---- IIT-RV-5: amendments -------------------------------------------------------


def approve_conflict(engine):
    service.submit_decisions(
        engine, T, "case-conflict", "rita", "reviewer", CHOOSE, BASE, expected_version=0
    )


def test_rv5_amendment_reopens_with_exact_diff_and_version_n_plus_1(tmp_path):
    engine, contracts = world(tmp_path)
    approve_conflict(engine)
    client = client_for(engine, contracts)
    csrf = login(client)
    url = f"/tenants/{T}/cases/case-conflict/amendments"
    posted = client.post(
        url,
        json={"source": "notes", "fields": {"launch_date": "2027-03-01"}},
        headers={"X-CSRF-Token": csrf},
    )
    assert posted.status_code == 201
    assert posted.json() == {
        "status": "needs_re_review",
        "base_version": 1,
        "diff": [
            {
                "field": "launch_date",
                "old_approved_value": "2027-01-12",
                "new_candidates": [
                    {"source": "form", "value": "2027-01-12"},
                    {"source": "crm", "value": "2027-01-12"},
                    {"source": "notes", "value": "2027-03-01"},
                ],
            }
        ],
    }
    viewed = client.get(f"/tenants/{T}/cases/case-conflict").json()
    assert (viewed["status"], viewed["version"], viewed["amendment"]["seq"]) == (
        "needs_re_review",
        1,
        1,
    )
    assert list(viewed["packet"]["conflicts"]) == ["launch_date"]
    second = client.post(
        url,
        json={"source": "notes", "fields": {"launch_date": "2027-04-01"}},
        headers={"X-CSRF-Token": csrf},
    )
    assert (second.status_code, second.json()) == (409, {"detail": "amendment_open"})
    pick = {"launch_date": {"type": "choose_source", "source": "notes"}}
    done = decide(client, csrf, "case-conflict", pick, version=1)
    assert done.status_code == 201
    assert (done.json()["review_version"], done.json()["resolved"]["launch_date"]) == (
        2,
        "2027-03-01",
    )
    with Session(engine) as session:
        v2 = session.scalar(
            select(ReviewVersion).where(
                ReviewVersion.event_id == "case-conflict", ReviewVersion.version == 2
            )
        )
        assert v2 is not None and v2.parent_version == 1
        assert session.scalars(select(Amendment.status)).all() == ["closed"]
    assert client.get(f"/tenants/{T}/cases/case-conflict").json()["status"] == "approved"


def test_rv5_amendment_guards(tmp_path):
    engine, contracts = world(tmp_path)
    codes = []
    for event_id, fields in (("case-conflict", {"region": "EU"}),):
        try:
            service.amend_case(engine, T, event_id, "rita", "reviewer", "notes", fields, BASE)
        except IntakeError as exc:
            codes.append(exc.code)
    approve_conflict(engine)
    for source, fields in (
        ("notes", {"customer_name": "Marigold Labs Inc"}),
        ("nope", {"region": "EU"}),
        ("notes", {"zzz": "1"}),
    ):
        try:
            service.amend_case(engine, T, "case-conflict", "rita", "reviewer", source, fields, BASE)
        except IntakeError as exc:
            codes.append(exc.code)
    try:
        service.amend_case(
            engine, T, "case-conflict", "vera", "viewer", "notes", {"region": "EU"}, BASE
        )
    except IntakeError as exc:
        codes.append(exc.code)
    assert codes == [
        "not_approved",
        "no_change",
        "invalid_amendment",
        "invalid_amendment",
        "forbidden",
    ]


# ---- IIT-RV-6: audit chain ------------------------------------------------------


def test_rv6_audit_chain_records_actions_and_detects_tampering(tmp_path):
    engine, contracts = world(tmp_path)
    approve_conflict(engine)
    service.amend_case(
        engine, T, "case-conflict", "rita", "reviewer", "notes", {"region": "EU"}, BASE
    )
    with Session(engine) as session:
        rows = session.scalars(
            select(AuditEntry).where(AuditEntry.tenant_id == T).order_by(AuditEntry.id)
        ).all()
        assert [(r.action, r.actor, r.subject) for r in rows] == [
            ("decide", "rita", "case-conflict"),
            ("approve", "rita", "case-conflict"),
            ("amend", "rita", "case-conflict"),
        ]
        assert rows[0].prev_hash == "0" * 64 and rows[1].prev_hash == rows[0].hash
        assert json.loads(rows[0].detail_json) == {
            "types": {"customer_name": "choose_source"},
            "version": 1,
        }
    assert audit.verify_chain(engine, T) == {"valid": True, "entries": 3, "first_invalid_id": None}
    assert audit.verify_chain(engine, "tenant-b") == {
        "valid": True,
        "entries": 0,
        "first_invalid_id": None,
    }
    with engine.begin() as conn:
        conn.execute(text("UPDATE audit_log SET actor='mallory' WHERE action='approve'"))
    assert audit.verify_chain(engine, T) == {"valid": False, "entries": 1, "first_invalid_id": 2}


def test_rv6_deleted_row_breaks_chain_and_http_verify_is_admin_only(tmp_path):
    engine, contracts = world(tmp_path)
    approve_conflict(engine)
    audit.record_audit(engine, T, "system", "project", "case-conflict", {"ok": True})
    client = client_for(engine, contracts)
    login(client, "rita")
    forbidden = client.get(f"/audit/verify?tenant_id={T}")
    assert (forbidden.status_code, forbidden.json()) == (403, {"detail": "forbidden"})
    admin = client_for(engine, contracts)
    login(admin, "ada")
    assert admin.get(f"/audit/verify?tenant_id={T}").json() == {
        "valid": True,
        "entries": 3,
        "first_invalid_id": None,
    }
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM audit_log WHERE id=2"))
    assert admin.get(f"/audit/verify?tenant_id={T}").json() == {
        "valid": False,
        "entries": 1,
        "first_invalid_id": 3,
    }
    with pytest.raises(IntakeError) as unknown:
        audit.record_audit(engine, T, "system", "teleport", "x", {})
    assert unknown.value.code == "invalid_audit"


def test_rv6_webhook_ingest_is_audited(tmp_path):
    engine, contracts = world(tmp_path)
    key = Fernet.generate_key()
    app = create_ingress_app(
        engine,
        {T: BASE},
        {(T, "form"): SourceAuth(shared_token="tenant-a-token")},
        encryption_key=key,
    )
    body = json.dumps(
        event("evt-audit", form={"customer_name": "Marigold Labs", "launch_date": "2027-01-12"})
    )
    response = TestClient(app).post(
        f"/v1/tenants/{T}/webhooks/form",
        content=body,
        headers={"Content-Type": "application/json", "X-Intake-Token": "tenant-a-token"},
    )
    assert response.status_code == 201
    with Session(engine) as session:
        row = session.scalar(select(AuditEntry).where(AuditEntry.action == "ingest"))
        assert row is not None
        assert (row.actor, row.subject, json.loads(row.detail_json)) == (
            "webhook:shared_token",
            "evt-audit",
            {"raw_event_id": 1, "replayed": False, "source": "form"},
        )
    assert audit.verify_chain(engine, T)["valid"] is True


# ---- IIT-RV-7: legacy CLI -------------------------------------------------------


def test_rv7_cli_actor_works_in_process_but_cannot_log_in(tmp_path):
    engine, contracts = world(tmp_path)
    result = service.submit_decisions(
        engine, T, "case-conflict", service.CLI_ACTOR, None, CHOOSE, BASE, expected_version=0
    )
    assert (result["review_actor"], result["status"]) == ("cli:local", "approved")
    client = client_for(engine, contracts)
    denied = client.post("/login", json={"username": "cli:local", "password": PASSWORD})
    assert (denied.status_code, denied.json()) == (401, {"detail": "invalid_credentials"})


def test_rv7_legacy_cli_review_gate_unchanged(tmp_path):
    from intake_translator.store import process_once

    db = str(tmp_path / "legacy.sqlite3")
    packet, _ = process_once(
        db,
        {
            "schema_version": "1",
            "event_id": "legacy-1",
            "sources": {
                "form": {"customer_name": "A", "launch_date": "2027-01-12"},
                "crm": {"customer_name": "B", "launch_date": "2027-01-12"},
            },
        },
    )
    assert list(packet["conflicts"]) == ["customer_name"]
    approved, replayed = submit_review(db, "legacy-1", {"customer_name": "crm"})
    assert (approved["status"], approved["resolved"]["customer_name"], replayed) == (
        "approved",
        "B",
        False,
    )


def test_migration_0002_keeps_v03_review_rows(tmp_path):
    db = tmp_path / "old.sqlite3"
    upgrade(db, "0001")
    engine = engine_for(f"sqlite:///{db}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO review_versions VALUES ('t','e1',1,'system:unanimous-policy','{}','{\"status\":\"approved\"}')"
            )
        )
    upgrade(db)
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT version, parent_version, state, reason FROM review_versions")
        ).one()
    assert tuple(row) == (1, None, "approved", None)
    engine.dispose()


def test_contract_two_person_override_option_is_strict():
    from intake_translator.contracts import parse_contract

    base = (ROOT / "config/default-contract.yaml").read_text()
    assert parse_contract(base).two_person_override is False
    assert parse_contract(base + "two_person_override: true\n").two_person_override is True
    with pytest.raises(IntakeError) as bad:
        parse_contract(base + "two_person_override: yes please\n")
    assert bad.value.detail == "two_person_override must be boolean"
