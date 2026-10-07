"""OIDC sign-in (GitHub or Google) behind configuration, with PKCE and state.

The provider exchange is injected, so tests use a fake IdP and production code
supplies the real token and userinfo calls. Identities are never auto-created:
an admin links a provider subject to an existing account first.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlencode

from sqlalchemy.engine import Engine

from ..core import IntakeError
from .accounts import constant_time_equal, username_for_oidc

PROVIDERS = {
    "github": "https://github.com/login/oauth/authorize",
    "google": "https://accounts.google.com/o/oauth2/v2/auth",
}


@dataclass(frozen=True)
class OidcProvider:
    name: str
    client_id: str
    redirect_uri: str
    # (code, pkce_verifier) -> verified provider subject. Raises IntakeError on failure.
    exchange: Callable[[str, str], str]

    def __post_init__(self) -> None:
        if self.name not in PROVIDERS or not self.client_id or not self.redirect_uri:
            raise ValueError("provider must be github or google with a client and redirect")


@dataclass
class PendingLogins:
    """In-memory state for one process; sign-ins started elsewhere will not complete."""

    ttl_seconds: int = 600
    clock: Callable[[], float] = time.monotonic
    items: dict[str, tuple[str, str, float]] = field(default_factory=dict)

    def start(self, provider: OidcProvider) -> str:
        state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
        self.items[state] = (provider.name, verifier, self.clock() + self.ttl_seconds)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        query = urlencode(
            {
                "client_id": provider.client_id,
                "redirect_uri": provider.redirect_uri,
                "response_type": "code",
                "scope": "openid email",
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{PROVIDERS[provider.name]}?{query}"

    def finish(self, engine: Engine, provider: OidcProvider, state: str, code: str) -> str:
        entry = self.items.pop(state, None)
        if (
            entry is None
            or not constant_time_equal(entry[0], provider.name)
            or entry[2] < self.clock()
        ):
            raise IntakeError("invalid_state", "sign-in state is unknown or expired")
        subject = provider.exchange(code, entry[1])
        username = username_for_oidc(engine, provider.name, subject)
        if username is None:
            raise IntakeError("forbidden", "identity is not linked to an account")
        return username
