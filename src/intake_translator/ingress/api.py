"""Authenticated, tenant-scoped webhook ingress. No public/demo route is reused."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import os
from typing import Literal

from cryptography.fernet import Fernet
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.engine import Engine

from ..contracts import Contract
from ..core import IntakeError
from ..field_service import process_contract_event
from ..storage.machine_keys import verify_key
from ..storage.raw import append_raw
from ..storage.repository import SqlRepository
from .security import TokenBucket, parse_bounded_json, verify_hmac, verify_token


@dataclass(frozen=True)
class SourceAuth:
    """Provisioned outside the repo; two active HMAC keys support rotation."""

    hmac_secrets: tuple[bytes, ...] = ()
    shared_token: str | None = None
    allowed_ips: frozenset[str] | None = None
    allow_query_token: bool = False  # not supported by Zoho POST; custom clients only
    max_body_bytes: int = 16 * 1024

    def __post_init__(self) -> None:
        if not 1 <= self.max_body_bytes <= 256 * 1024:
            raise ValueError("body limit must be 1-256 KiB")
        if len(self.hmac_secrets) > 2 or any(not key for key in self.hmac_secrets):
            raise ValueError("one or two nonempty HMAC keys required")
        if self.shared_token is not None and not self.shared_token:
            raise ValueError("shared token must not be empty")


def create_ingress_app(
    engine: Engine,
    contracts: dict[str, Contract],
    source_auth: dict[tuple[str, str], SourceAuth],
    *,
    encryption_key: bytes | None = None,
    bucket: TokenBucket | None = None,
    request_timeout: float = 10.0,
    max_json_depth: int = 20,
) -> FastAPI:
    """Call only with provisioned tenant/source secrets and a Fernet key from env/KMS."""
    if encryption_key is None:
        configured = os.environ.get("INTAKE_FERNET_KEY")
        if not configured:
            raise ValueError("INTAKE_FERNET_KEY is required")
        encryption_key = configured.encode("ascii")
    Fernet(encryption_key)  # fail closed at startup
    if request_timeout <= 0:
        raise ValueError("request timeout must be positive")
    repo = SqlRepository(engine)
    limiter = bucket if bucket is not None else TokenBucket()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.post("/v1/tenants/{tenant_id}/webhooks/{source}")
    async def webhook(tenant_id: str, source: str, request: Request) -> JSONResponse:
        if tenant_id not in contracts or (tenant_id, source) not in source_auth:
            raise HTTPException(status_code=404, detail="unknown_route")
        policy = source_auth[(tenant_id, source)]
        if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
            raise HTTPException(status_code=415, detail="unsupported_media_type")

        async def read_bounded() -> bytes:
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > policy.max_body_bytes:
                    raise HTTPException(status_code=413, detail="payload_too_large")
            return bytes(body)

        try:
            raw = await asyncio.wait_for(read_bounded(), timeout=request_timeout)
        except TimeoutError as exc:
            raise HTTPException(status_code=408, detail="request_timeout") from exc
        mode: Literal["hmac", "shared_token", "api_key"]
        timestamp = request.headers.get("x-intake-timestamp", "")
        signature = request.headers.get("x-intake-signature", "")
        header_token = request.headers.get("x-intake-token", "")
        query_token = request.query_params.get("token", "") if policy.allow_query_token else ""
        bearer = request.headers.get("authorization", "")
        remote_ip = request.client.host if request.client is not None else None
        if timestamp or signature:
            if not verify_hmac(raw, timestamp, signature, policy.hmac_secrets):
                raise HTTPException(status_code=401, detail="unauthorized")
            mode = "hmac"
        elif header_token or query_token:
            if header_token and query_token and header_token != query_token:
                raise HTTPException(status_code=401, detail="unauthorized")
            if not verify_token(
                header_token or query_token,
                policy.shared_token or "",
                remote_ip=remote_ip,
                allowlist=policy.allowed_ips,
            ):
                raise HTTPException(status_code=401, detail="unauthorized")
            mode = "shared_token"
        elif bearer.startswith("Bearer ") and verify_key(engine, tenant_id, bearer[7:]):
            mode = "api_key"
        else:
            raise HTTPException(status_code=401, detail="unauthorized")
        if not limiter.allow(tenant_id):
            raise HTTPException(status_code=429, detail="rate_limited")
        try:
            event = parse_bounded_json(raw, limit=policy.max_body_bytes, max_depth=max_json_depth)
        except IntakeError as exc:
            raise HTTPException(
                status_code=413 if exc.code == "payload_too_large" else 400, detail=exc.code
            ) from exc
        if (
            not isinstance(event, dict)
            or not isinstance(event.get("event_id"), str)
            or not event["event_id"]
        ):
            raise HTTPException(status_code=422, detail="invalid_event_id")
        event_id = event["event_id"]
        try:
            # Raw row first: a ledger failure leaves nothing processed, so no processed
            # event can exist without its raw record. Rejected events keep an audit row.
            raw_id = append_raw(
                engine,
                tenant_id=tenant_id,
                source=source,
                event_id=event_id,
                body=raw,
                auth_mode=mode,
                key=encryption_key,
            )
            packet, replayed = process_contract_event(repo, tenant_id, source, event, contracts)
        except IntakeError as exc:
            code = 409 if exc.code == "event_id_reused" else 422
            raise HTTPException(status_code=code, detail=exc.code) from exc
        return JSONResponse(
            {**packet, "replayed": replayed, "auth_mode": mode, "raw_event_id": raw_id},
            status_code=200 if replayed else 201,
        )

    return app
