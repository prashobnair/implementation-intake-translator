import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from intake_translator.core import IntakeError
from intake_translator.ingress.security import (
    TokenBucket,
    hash_machine_key,
    new_machine_key,
    parse_bounded_json,
    verify_hmac,
    verify_shared_token,
)
from intake_translator.storage.raw import append_raw, purge_bodies
from intake_translator.storage.schema import Base, RawEvent, engine_for


def test_hmac_known_vector_rotation_and_skew():
    body = b'{"event_id":"demo-1"}'
    signature = hmac.new(b"rotated-secret", b"1000." + body, hashlib.sha256).hexdigest()
    assert signature == "659014871469461a8406b0714ee248d78b065f405de61572e3bc610112e954a2"
    assert verify_hmac(body, "1000", "sha256=" + signature, (b"old", b"rotated-secret"), now=1000)
    assert not verify_hmac(body + b" ", "1000", signature, (b"old", b"rotated-secret"), now=1000)
    assert not verify_hmac(body, "1000", signature, (b"old", b"rotated-secret"), now=1301)
    assert not verify_hmac(body, "invalid", signature, (b"rotated-secret",), now=1000)


def test_shared_token_and_limits():
    assert verify_shared_token(
        "secret", "secret", "event-1", remote_ip="127.0.0.1", allowlist=frozenset({"127.0.0.1"})
    )
    assert not verify_shared_token("secret", "secret", "", remote_ip="127.0.0.1")
    assert not verify_shared_token(
        "secret", "secret", "event-1", remote_ip="10.0.0.1", allowlist=frozenset({"127.0.0.1"})
    )
    assert parse_bounded_json(b'{"ok":true}') == {"ok": True}
    with pytest.raises(IntakeError, match="exceeds configured"):
        parse_bounded_json(b"123", limit=2)
    with pytest.raises(IntakeError, match="nesting"):
        parse_bounded_json(json.dumps([[[1]]]).encode(), max_depth=2)
    clock = [1.0]
    bucket = TokenBucket(capacity=1, refill_per_second=1.0, clock=lambda: clock[0])
    assert bucket.allow("tenant-a")
    assert not bucket.allow("tenant-a")
    assert bucket.allow("tenant-b")
    clock[0] += 1
    assert bucket.allow("tenant-a")
    secret, prefix = new_machine_key()
    assert secret.startswith(prefix) and len(hash_machine_key(secret)) == 64


def test_encrypted_append_and_retention_preserves_digest(tmp_path):
    engine = engine_for(f"sqlite:///{tmp_path / 'raw.sqlite3'}")
    Base.metadata.create_all(engine)
    key = Fernet.generate_key()
    body = b"synthetic private demo body"
    row_id = append_raw(
        engine,
        tenant_id="demo",
        source="form",
        event_id="evt",
        body=body,
        auth_mode="hmac",
        key=key,
    )
    with engine.connect() as conn:
        row = conn.execute(select(RawEvent).where(RawEvent.id == row_id)).first()
        assert row and body not in bytes(row.body_ciphertext)
        assert Fernet(key).decrypt(bytes(row.body_ciphertext)) == body
    assert (
        purge_bodies(
            engine, tenant_id="other", before=datetime.now(timezone.utc) + timedelta(days=31)
        )
        == 0
    )
    assert (
        purge_bodies(
            engine, tenant_id="demo", before=datetime.now(timezone.utc) + timedelta(days=31)
        )
        == 1
    )
    with engine.connect() as conn:
        row = conn.execute(select(RawEvent).where(RawEvent.id == row_id)).first()
        assert (
            row
            and row.body_ciphertext is None
            and row.payload_sha256 == hashlib.sha256(body).hexdigest()
        )
    engine.dispose()
