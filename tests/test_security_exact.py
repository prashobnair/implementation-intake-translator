"""Exact-value security acceptance tests, with only synthetic inputs and secrets."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings, strategies as st
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from intake_translator.contracts import Field, load_contract, normalize
from intake_translator.core import IntakeError
from intake_translator.ingress.api import SourceAuth, create_ingress_app
from intake_translator.ingress.security import TokenBucket, parse_bounded_json, verify_hmac
from intake_translator.storage.machine_keys import issue_key, verify_key
from intake_translator.storage.raw import append_raw, purge_expired_bodies
from intake_translator.storage.repository import SqlRepository
from intake_translator.storage.schema import MachineKey, RawEvent, engine_for

ROOT = Path(__file__).parents[1]
KEY = Fernet.generate_key()


def repo(tmp_path):
    db = tmp_path / "security.sqlite3"
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": f"sqlite:///{db}"},
        check=True,
        capture_output=True,
    )
    return SqlRepository(engine_for(f"sqlite:///{db}"))


def app_client(repository, *, mode="hmac", bucket=None, timeout=10.0, limit=16 * 1024):
    contract = load_contract(ROOT / "config/default-contract.yaml")
    policy = SourceAuth(
        hmac_secrets=(b"old-key", b"new-key"), shared_token="tenant-a-token", max_body_bytes=limit
    )
    app = create_ingress_app(
        repository.engine,
        {"tenant-a": contract},
        {("tenant-a", "form"): policy},
        encryption_key=KEY,
        bucket=bucket,
        request_timeout=timeout,
    )
    return TestClient(app)


def event_bytes(event_id="evt-1", name="Synthetic Lab"):
    return json.dumps(
        {
            "schema_version": "2",
            "event_id": event_id,
            "sources": {"form": {"customer_name": name, "launch_date": "2027-01-12"}},
        },
        separators=(",", ":"),
    ).encode()


def sign(body, stamp="1000", key=b"new-key"):
    return "sha256=" + hmac.new(key, stamp.encode() + b"." + body, hashlib.sha256).hexdigest()


def post(
    client, body, *, timestamp=None, signature=None, token=None, tenant="tenant-a", source="form"
):
    headers = {"Content-Type": "application/json"}
    if timestamp is not None:
        headers["X-Intake-Timestamp"] = timestamp
    if signature is not None:
        headers["X-Intake-Signature"] = signature
    if token is not None:
        headers["X-Intake-Token"] = token
    return client.post(f"/v1/tenants/{tenant}/webhooks/{source}", content=body, headers=headers)


@given(
    operations=st.lists(
        st.tuples(
            st.sampled_from(["a", "b", "c"]), st.sampled_from(["form", "crm"]), st.integers(1, 5)
        ),
        min_size=1,
        max_size=15,
    )
)
@settings(
    max_examples=12, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
def test_sec1_random_interleavings_tenant_and_source_keys(operations):
    with tempfile.TemporaryDirectory() as directory:
        repository = repo(Path(directory))
        expected = {}
        for tenant, source, number in operations:
            event_id = f"evt-{number}"
            event = {"event_id": event_id}
            packet = {"event_id": event_id, "tenant": tenant, "source": source}
            result, replayed = repository.put(tenant, source, event_id, event, packet)
            key = (tenant, source, event_id)
            assert (result, replayed) == (packet, key in expected)
            expected[key] = packet
            for other in ("a", "b", "c"):
                assert repository.get(other, source, event_id) == expected.get(
                    (other, source, event_id)
                )
        repository.engine.dispose()


def test_sec2_hmac_vector_rotation_skew_and_signed_replay(tmp_path, monkeypatch):
    raw = event_bytes()
    assert sign(raw) == "sha256=" + hmac.new(b"new-key", b"1000." + raw, hashlib.sha256).hexdigest()
    assert verify_hmac(raw, "1000", sign(raw), (b"old-key", b"new-key"), now=1300)
    assert not verify_hmac(raw, "1000", sign(raw), (b"old-key", b"new-key"), now=1301)
    assert not verify_hmac(raw + b" ", "1000", sign(raw), (b"old-key", b"new-key"), now=1000)
    assert not verify_hmac(raw, "1000", sign(raw), (), now=1000)
    monkeypatch.setattr("intake_translator.ingress.security.time.time", lambda: 1000)
    repository = repo(tmp_path)
    with app_client(repository) as client:
        first = post(client, raw, timestamp="1000", signature=sign(raw))
        assert first.status_code == 201
        assert first.json()["auth_mode"] == "hmac" and first.json()["replayed"] is False
        replay = post(client, raw, timestamp="1000", signature=sign(raw))
        assert replay.status_code == 200 and replay.json()["replayed"] is True
        bad = post(client, raw + b" ", timestamp="1000", signature=sign(raw))
        assert (bad.status_code, bad.json()) == (401, {"detail": "unauthorized"})
        stale = post(client, raw, timestamp="699", signature=sign(raw, "699"))
        assert (stale.status_code, stale.json()) == (401, {"detail": "unauthorized"})
        changed = post(
            client,
            event_bytes(name="Different"),
            timestamp="1000",
            signature=sign(event_bytes(name="Different")),
        )
        assert (changed.status_code, changed.json()) == (409, {"detail": "event_id_reused"})
    repository.engine.dispose()


def test_sec3_shared_token_header_audit_and_zoho_query_caveat(tmp_path):
    repository = repo(tmp_path)
    with app_client(repository) as client:
        body = event_bytes()
        response = post(client, body, token="tenant-a-token")
        assert response.status_code == 201
        assert (response.json()["auth_mode"], response.json()["event_id"]) == (
            "shared_token",
            "evt-1",
        )
        with Session(repository.engine) as session:
            row = session.scalar(
                select(RawEvent).where(RawEvent.id == response.json()["raw_event_id"])
            )
            assert row is not None and (row.tenant_id, row.source, row.auth_mode) == (
                "tenant-a",
                "form",
                "shared_token",
            )
        assert (
            post(client, body, token="wrong").status_code,
            post(client, event_bytes(event_id=""), token="tenant-a-token").status_code,
        ) == (401, 422)
        assert (
            post(
                client, event_bytes(event_id="evt-2"), tenant="tenant-b", token="tenant-a-token"
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/v1/tenants/tenant-a/webhooks/form?token=tenant-a-token",
                content=event_bytes(event_id="evt-3"),
                headers={"Content-Type": "application/json"},
            ).status_code
            == 401
        )
    repository.engine.dispose()


def test_sec4_machine_key_hash_tenant_scope_and_bearer(tmp_path):
    repository = repo(tmp_path)
    secret, prefix = issue_key(repository.engine, "tenant-a")
    assert secret.startswith(prefix) and len(prefix) == 12
    assert verify_key(repository.engine, "tenant-a", secret) is True
    assert verify_key(repository.engine, "tenant-b", secret) is False
    assert verify_key(repository.engine, "tenant-a", secret + "x") is False
    with Session(repository.engine) as session:
        row = session.get(MachineKey, ("tenant-a", prefix))
        assert row is not None and row.digest == hashlib.sha256(secret.encode()).hexdigest()
        assert secret not in row.digest
    client = app_client(repository)
    response = client.post(
        "/v1/tenants/tenant-a/webhooks/form",
        content=event_bytes("api-1"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {secret}"},
    )
    assert (response.status_code, response.json()["auth_mode"]) == (201, "api_key")
    repository.engine.dispose()


def test_sec5_limits_depth_timeout_and_tenant_bucket(tmp_path, monkeypatch):
    repository = repo(tmp_path)
    assert parse_bounded_json(b'{"x": [1]}') == {"x": [1]}
    with pytest.raises(IntakeError) as error:
        parse_bounded_json(b'{"a":{"b":{"c":1}}}', max_depth=2)
    assert error.value.code == "json_too_deep"
    with pytest.raises(ValueError, match="body limit"):
        SourceAuth(max_body_bytes=256 * 1024 + 1)
    clock = [0.0]
    limiter = TokenBucket(capacity=1, refill_per_second=1.0, clock=lambda: clock[0])
    client = app_client(repository, bucket=limiter, limit=64)
    assert post(client, event_bytes(), token="tenant-a-token").status_code == 413
    # A larger configured body fits; rate limit is per tenant after authentication.
    client = app_client(repository, bucket=limiter)
    assert post(client, event_bytes(), token="tenant-a-token").status_code == 201
    assert (
        post(client, event_bytes("evt-2"), token="tenant-a-token").status_code,
        post(client, event_bytes("evt-3"), token="wrong").status_code,
    ) == (429, 401)
    clock[0] = 1.0
    assert post(client, event_bytes("evt-2"), token="tenant-a-token").status_code == 201

    async def timed_out(coroutine, timeout):
        coroutine.close()
        raise TimeoutError()

    monkeypatch.setattr("intake_translator.ingress.api.asyncio.wait_for", timed_out)
    assert post(client, event_bytes("evt-4"), token="tenant-a-token").status_code == 408
    repository.engine.dispose()


def test_sec6_ciphertext_and_30_day_purge_keeps_digest_audit(tmp_path):
    repository = repo(tmp_path)
    body = b"synthetic private body"
    row_id = append_raw(
        repository.engine,
        tenant_id="tenant-a",
        source="form",
        event_id="evt",
        body=body,
        auth_mode="shared_token",
        key=KEY,
    )
    with Session(repository.engine) as session:
        row = session.get(RawEvent, row_id)
        assert row is not None and row.body_ciphertext is not None
        assert body not in row.body_ciphertext
        assert Fernet(KEY).decrypt(row.body_ciphertext) == body
        assert row.payload_sha256 == hashlib.sha256(body).hexdigest()
    assert (
        purge_expired_bodies(
            repository.engine,
            tenant_id="tenant-a",
            days=30,
            now=datetime.now(timezone.utc) + timedelta(days=29),
        )
        == 0
    )
    assert (
        purge_expired_bodies(
            repository.engine,
            tenant_id="tenant-b",
            days=30,
            now=datetime.now(timezone.utc) + timedelta(days=31),
        )
        == 0
    )
    assert (
        purge_expired_bodies(
            repository.engine,
            tenant_id="tenant-a",
            days=30,
            now=datetime.now(timezone.utc) + timedelta(days=31),
        )
        == 1
    )
    with Session(repository.engine) as session:
        row = session.get(RawEvent, row_id)
        assert row is not None and row.body_ciphertext is None
        assert (row.tenant_id, row.source, row.event_id, row.auth_mode) == (
            "tenant-a",
            "form",
            "evt",
            "shared_token",
        )
        assert row.payload_sha256 == hashlib.sha256(body).hexdigest()
    repository.engine.dispose()


@pytest.mark.parametrize(
    "kind,invalid",
    [
        ("int", "1e3"),
        ("int", "1_000"),
        ("int", "١٢"),
        ("money", "1e3"),
        ("money", "1_000"),
        ("money", "١٢"),
        ("money", "1.234"),
        ("int", " 12"),
        ("money", " 12"),
        ("decimal", "12 "),
        ("decimal", "1e3"),
        ("decimal", "1_000"),
        ("decimal", "١٢"),
    ],
)
def test_ascii_numeric_rejects_exact_values(kind, invalid):
    field = Field(kind, True, 200, (), False, "numeric")
    with pytest.raises(IntakeError) as error:
        normalize(field, invalid)
    assert error.value.code == "invalid_field"
    assert error.value.detail == (
        "integer field must be positive" if kind == "int" else "invalid amount or precision"
    )


def test_ascii_numeric_accepts_exact_values():
    base = Field("int", True, 200, (), False, "numeric")
    assert normalize(base, "1000") == 1000
    assert normalize(replace(base, type="money"), "1000.20") == "1000.2"
    assert normalize(replace(base, type="decimal"), "0.125") == "0.125"


def test_sec2_source_binding_wrong_secret_and_unsigned_denied(tmp_path, monkeypatch):
    monkeypatch.setattr("intake_translator.ingress.security.time.time", lambda: 1000)
    repository = repo(tmp_path)
    contract = load_contract(ROOT / "config/default-contract.yaml")
    app = create_ingress_app(
        repository.engine,
        {"tenant-a": contract},
        {
            ("tenant-a", "form"): SourceAuth(hmac_secrets=(b"form-key",)),
            ("tenant-a", "crm"): SourceAuth(hmac_secrets=(b"crm-key",)),
        },
        encryption_key=KEY,
    )
    client = TestClient(app)
    raw = event_bytes("source-bound")
    assert (
        post(
            client, raw, source="crm", timestamp="1000", signature=sign(raw, key=b"form-key")
        ).status_code
        == 401
    )
    assert post(client, raw, source="form").status_code == 401
    accepted = post(
        client, raw, source="crm", timestamp="1000", signature=sign(raw, key=b"crm-key")
    )
    assert (accepted.status_code, accepted.json()["auth_mode"]) == (201, "hmac")
    repository.engine.dispose()


def test_sec3_optional_ip_allowlist_and_explicit_query_mode(tmp_path):
    repository = repo(tmp_path)
    contract = load_contract(ROOT / "config/default-contract.yaml")
    policy = SourceAuth(
        shared_token="scoped-token", allowed_ips=frozenset({"10.0.0.1"}), allow_query_token=True
    )
    app = create_ingress_app(
        repository.engine,
        {"tenant-a": contract},
        {("tenant-a", "form"): policy},
        encryption_key=KEY,
    )
    client = TestClient(app)
    raw = event_bytes("query-1")
    assert (
        client.post(
            "/v1/tenants/tenant-a/webhooks/form?token=scoped-token",
            content=raw,
            headers={"Content-Type": "application/json"},
        ).status_code
        == 401
    )
    permitted = SourceAuth(
        shared_token="scoped-token", allowed_ips=frozenset({"testclient"}), allow_query_token=True
    )
    app = create_ingress_app(
        repository.engine,
        {"tenant-a": contract},
        {("tenant-a", "form"): permitted},
        encryption_key=KEY,
    )
    client = TestClient(app)
    accepted = client.post(
        "/v1/tenants/tenant-a/webhooks/form?token=scoped-token",
        content=raw,
        headers={"Content-Type": "application/json"},
    )
    assert (accepted.status_code, accepted.json()["auth_mode"]) == (201, "shared_token")
    repository.engine.dispose()


def test_sec5_default_and_transcript_body_cap_exact(tmp_path):
    repository = repo(tmp_path)
    assert SourceAuth().max_body_bytes == 16 * 1024
    assert SourceAuth(max_body_bytes=256 * 1024).max_body_bytes == 256 * 1024
    body = event_bytes(name="S" * (17 * 1024))
    assert post(app_client(repository), body, token="tenant-a-token").status_code == 413
    # Size cap may be raised for long transcripts; field length still rejects this sample.
    response = post(app_client(repository, limit=256 * 1024), body, token="tenant-a-token")
    assert (response.status_code, response.json()) == (422, {"detail": "invalid_field"})
    repository.engine.dispose()


def test_sec2_hmac_non_ascii_timestamp_denied():
    assert verify_hmac(b"{}", "١٠٠٠", "sha256=" + "0" * 64, (b"key",), now=1000) is False
    assert verify_hmac(b"{}", "9" * 10000, "sha256=" + "0" * 64, (b"key",), now=1000) is False
