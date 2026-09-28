"""Pure webhook auth, bounded JSON and tenant-scoped request throttling."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Callable

from ..core import IntakeError


def verify_hmac(
    raw: bytes,
    timestamp: str,
    signature: str,
    secrets_active: tuple[bytes, ...],
    *,
    now: int | None = None,
) -> bool:
    if (
        not isinstance(timestamp, str)
        or not timestamp.isascii()
        or not timestamp.isdecimal()
        or len(timestamp) > 12
        or not secrets_active
        or len(secrets_active) > 2
    ):
        return False
    moment = int(timestamp)
    if abs((int(time.time()) if now is None else now) - moment) > 300:
        return False
    if not signature.startswith("sha256=") or len(signature) != 71:
        return False
    message = timestamp.encode("ascii") + b"." + raw
    accepted = False
    for key in secrets_active[:2]:
        expected = hmac.new(key, message, hashlib.sha256).hexdigest()
        accepted |= hmac.compare_digest(expected, signature[7:])
    return accepted


def verify_shared_token(
    provided: str,
    configured: str,
    event_id: object,
    *,
    remote_ip: str | None = None,
    allowlist: frozenset[str] | None = None,
) -> bool:
    if not configured or not isinstance(event_id, str) or not event_id:
        return False
    if allowlist is not None and remote_ip not in allowlist:
        return False
    return isinstance(provided, str) and hmac.compare_digest(provided, configured)


def parse_bounded_json(raw: bytes, *, limit: int = 16 * 1024, max_depth: int = 20) -> object:
    if not 1 <= limit <= 256 * 1024 or len(raw) > limit:
        raise IntakeError("payload_too_large", "body exceeds configured limit")
    if not 1 <= max_depth <= 100:
        raise IntakeError("invalid_limit", "invalid depth limit")
    try:
        value = json.loads(raw)
    except (UnicodeError, ValueError) as exc:
        raise IntakeError("invalid_json", "body is not JSON") from exc

    def depth(node: object, level: int) -> None:
        if level > max_depth:
            raise IntakeError("json_too_deep", "JSON nesting exceeds limit")
        if isinstance(node, dict):
            for child in node.values():
                depth(child, level + 1)
        elif isinstance(node, list):
            for child in node:
                depth(child, level + 1)

    depth(value, 0)
    return value


@dataclass
class TokenBucket:
    capacity: int = 30
    refill_per_second: float = 1.0
    clock: Callable[[], float] = time.monotonic
    buckets: dict[str, tuple[float, float]] = field(default_factory=dict)

    def allow(self, tenant_id: str) -> bool:
        if not tenant_id:
            return False
        now = self.clock()
        remaining, previous = self.buckets.get(tenant_id, (float(self.capacity), now))
        remaining = min(
            float(self.capacity), remaining + max(0.0, now - previous) * self.refill_per_second
        )
        allowed = remaining >= 1
        self.buckets[tenant_id] = (remaining - 1 if allowed else remaining, now)
        return allowed


def new_machine_key() -> tuple[str, str]:
    """Return a secret once and its stable non-secret lookup prefix."""
    secret = secrets.token_urlsafe(32)
    return secret, secret[:12]


def hash_machine_key(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()
