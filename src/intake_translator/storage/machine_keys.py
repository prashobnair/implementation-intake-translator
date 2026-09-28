"""Tenant-scoped machine credentials; only the fingerprint and lookup prefix persist."""

from __future__ import annotations

import hmac
from sqlalchemy.orm import Session
from sqlalchemy.engine import Engine

from ..core import IntakeError
from ..ingress.security import hash_machine_key, new_machine_key
from .schema import MachineKey


def issue_key(engine: Engine, tenant_id: str) -> tuple[str, str]:
    if not tenant_id:
        raise IntakeError("invalid_scope", "tenant is required")
    with Session(engine) as session, session.begin():
        for _ in range(3):
            secret, prefix = new_machine_key()
            if session.get(MachineKey, (tenant_id, prefix)) is None:
                session.add(
                    MachineKey(tenant_id=tenant_id, prefix=prefix, digest=hash_machine_key(secret))
                )
                return secret, prefix
    raise IntakeError("key_collision", "unable to issue unique key")


def verify_key(engine: Engine, tenant_id: str, secret: str) -> bool:
    if not tenant_id or not isinstance(secret, str) or len(secret) < 13:
        return False
    with Session(engine) as session:
        row = session.get(MachineKey, (tenant_id, secret[:12]))
        return row is not None and hmac.compare_digest(row.digest, hash_machine_key(secret))
