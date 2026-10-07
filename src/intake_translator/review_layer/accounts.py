"""Local accounts (argon2id), per-tenant roles and server-side sessions."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import delete
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from ..core import IntakeError
from ..storage.schema import Account, AuthSession, Membership, OidcIdentity
from .roles import validate_role

_HASHER = PasswordHasher()
_DUMMY = _HASHER.hash("not-a-real-password")
MIN_PASSWORD = 12


def constant_time_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def create_account(
    engine: Engine, username: str, password: str | None, memberships: dict[str, str]
) -> None:
    if not username or len(username) > 100 or not username.isascii() or ":" in username:
        raise IntakeError(
            "invalid_account", "username must be 1-100 ASCII characters without colons"
        )
    if password is not None and len(password) < MIN_PASSWORD:
        raise IntakeError("invalid_account", f"password needs at least {MIN_PASSWORD} characters")
    with Session(engine) as session, session.begin():
        if session.get(Account, username) is not None:
            raise IntakeError("account_exists", "username is taken")
        session.add(
            Account(
                username=username,
                password_hash=_HASHER.hash(password) if password is not None else None,
                active=True,
            )
        )
        for tenant_id, role in memberships.items():
            session.add(
                Membership(tenant_id=tenant_id, username=username, role=validate_role(role))
            )


def verify_login(engine: Engine, username: str, password: str) -> bool:
    """Run one argon2 verification for unknown users too, so timing does not leak."""
    with Session(engine) as session:
        account = session.get(Account, username) if username.isascii() else None
    stored = account.password_hash if account is not None and account.active else None
    try:
        _HASHER.verify(stored or _DUMMY, password)
    except (VerificationError, InvalidHashError):
        return False
    return stored is not None


def role_for(engine: Engine, username: str, tenant_id: str) -> str | None:
    with Session(engine) as session:
        account = session.get(Account, username)
        membership = session.get(Membership, (tenant_id, username))
        if account is None or not account.active or membership is None:
            return None
        return membership.role


def memberships_for(engine: Engine, username: str) -> dict[str, str]:
    from sqlalchemy import select

    with Session(engine) as session:
        rows = session.scalars(select(Membership).where(Membership.username == username))
        return {row.tenant_id: row.role for row in rows}


def link_oidc(engine: Engine, provider: str, subject: str, username: str) -> None:
    """An admin links an external identity to an existing account. No auto-provisioning."""
    with Session(engine) as session, session.begin():
        if session.get(Account, username) is None:
            raise IntakeError("not_found", "account does not exist")
        session.merge(OidcIdentity(provider=provider, subject=subject, username=username))


def username_for_oidc(engine: Engine, provider: str, subject: str) -> str | None:
    with Session(engine) as session:
        row = session.get(OidcIdentity, (provider, subject))
        return row.username if row is not None else None


@dataclass(frozen=True)
class SessionInfo:
    username: str
    csrf_token: str


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def create_session(
    engine: Engine, username: str, *, ttl_seconds: int = 8 * 3600, now: datetime | None = None
) -> tuple[str, str]:
    """Return the cookie token and CSRF token. Only the token hash is stored."""
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    moment = now or datetime.now(timezone.utc)
    with Session(engine) as session, session.begin():
        session.add(
            AuthSession(
                token_hash=_hash_token(token),
                username=username,
                csrf_token=csrf,
                expires_at=(moment + timedelta(seconds=ttl_seconds)).replace(tzinfo=None),
            )
        )
    return token, csrf


def lookup_session(
    engine: Engine, token: str, *, now: datetime | None = None
) -> SessionInfo | None:
    if not token or not token.isascii():
        return None
    moment = (now or datetime.now(timezone.utc)).replace(tzinfo=None)
    with Session(engine) as session:
        row = session.get(AuthSession, _hash_token(token))
        if row is None or row.expires_at <= moment:
            return None
        return SessionInfo(row.username, row.csrf_token)


def delete_session(engine: Engine, token: str) -> None:
    if not token.isascii():
        return
    with Session(engine) as session, session.begin():
        session.execute(delete(AuthSession).where(AuthSession.token_hash == _hash_token(token)))
