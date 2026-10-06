"""Authenticated review API: cookie sessions, CSRF, per-tenant roles, versions, audit."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pathlib import Path

from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.engine import Engine

from ..contracts import Contract
from ..core import IntakeError
from ..ingress.security import TokenBucket
from . import accounts, audit, service
from .oidc import OidcProvider, PendingLogins
from .roles import allowed, require

UI_DIR = Path(__file__).parent / "ui"
UI_FILES = {"index.html": "text/html", "app.js": "text/javascript", "app.css": "text/css"}
COOKIE = "iit_session"
MAX_BODY = 64 * 1024


def create_review_app(
    engine: Engine,
    contracts: dict[str, Contract],
    *,
    secure_cookies: bool = True,
    session_ttl_seconds: int = 8 * 3600,
    oidc_providers: dict[str, OidcProvider] | None = None,
    login_bucket: TokenBucket | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    attempts = login_bucket if login_bucket is not None else TokenBucket(5, 1 / 60)
    pending = PendingLogins()
    providers = oidc_providers or {}

    def now() -> datetime:
        return clock() if clock is not None else datetime.now(timezone.utc)

    async def body_of(request: Request) -> dict[str, Any]:
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_BODY:
                raise HTTPException(status_code=413, detail="payload_too_large")
        try:
            data = json.loads(raw or b"{}")
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(status_code=400, detail="invalid_json") from exc
        if not isinstance(data, dict):
            raise HTTPException(status_code=422, detail="invalid_body")
        return data

    def session_of(request: Request, *, unsafe: bool) -> accounts.SessionInfo:
        info = accounts.lookup_session(engine, request.cookies.get(COOKIE, ""), now=now())
        if info is None:
            raise HTTPException(status_code=401, detail="unauthorized")
        if unsafe and not accounts.constant_time_equal(
            request.headers.get("x-csrf-token", ""), info.csrf_token
        ):
            raise HTTPException(status_code=403, detail="csrf_failed")
        return info

    def tenant_role(info: accounts.SessionInfo, tenant_id: str) -> str:
        role = accounts.role_for(engine, info.username, tenant_id)
        if role is None or tenant_id not in contracts:
            raise HTTPException(status_code=404, detail="unknown_route")  # hide other tenants
        return role

    def fail(exc: IntakeError) -> HTTPException:
        status = {
            "forbidden": 403,
            "not_found": 404,
            "review_conflict": 409,
            "already_approved": 409,
            "amendment_open": 409,
            "not_approved": 409,
            "invalid_state": 400,
        }.get(exc.code, 422)
        if isinstance(exc, service.ReviewConflict):
            return HTTPException(
                status_code=status,
                detail={"detail": exc.code, "current_version": exc.current_version},
            )
        return HTTPException(status_code=status, detail=exc.code)

    def ui_headers() -> dict[str, str]:
        return {
            "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        }

    def start_session(username: str) -> JSONResponse:
        token, csrf = accounts.create_session(
            engine, username, ttl_seconds=session_ttl_seconds, now=now()
        )
        response = JSONResponse(
            {
                "username": username,
                "csrf_token": csrf,
                "memberships": accounts.memberships_for(engine, username),
            }
        )
        response.set_cookie(
            COOKIE,
            token,
            max_age=session_ttl_seconds,
            httponly=True,
            secure=secure_cookies,
            samesite="lax",
            path="/",
        )
        return response

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        body = exc.detail if isinstance(exc.detail, dict) else {"detail": exc.detail}
        return JSONResponse(body, status_code=exc.status_code)

    @app.get("/")
    @app.get("/ui/")
    async def ui_index() -> FileResponse:
        return FileResponse(UI_DIR / "index.html", media_type="text/html", headers=ui_headers())

    @app.get("/ui/{name}")
    async def ui_asset(name: str) -> FileResponse:
        if name not in UI_FILES:
            raise HTTPException(status_code=404, detail="not_found")
        return FileResponse(UI_DIR / name, media_type=UI_FILES[name], headers=ui_headers())

    @app.post("/login")
    async def login(request: Request) -> JSONResponse:
        data = await body_of(request)
        username, password = data.get("username"), data.get("password")
        if not isinstance(username, str) or not isinstance(password, str):
            raise HTTPException(status_code=401, detail="invalid_credentials")
        if not attempts.allow(f"login:{username}"):
            raise HTTPException(status_code=429, detail="rate_limited")
        if not accounts.verify_login(engine, username, password):
            raise HTTPException(status_code=401, detail="invalid_credentials")
        return start_session(username)

    @app.post("/logout")
    async def logout(request: Request) -> Response:
        session_of(request, unsafe=True)
        accounts.delete_session(engine, request.cookies.get(COOKIE, ""))
        response = JSONResponse({"status": "logged_out"})
        response.delete_cookie(COOKIE, path="/")
        return response

    @app.get("/me")
    async def me(request: Request) -> dict[str, Any]:
        info = session_of(request, unsafe=False)
        return {
            "username": info.username,
            "memberships": accounts.memberships_for(engine, info.username),
        }

    @app.get("/auth/oidc/{provider}/start")
    async def oidc_start(provider: str) -> RedirectResponse:
        if provider not in providers:
            raise HTTPException(status_code=404, detail="unknown_route")
        return RedirectResponse(pending.start(providers[provider]), status_code=302)

    @app.get("/auth/oidc/{provider}/callback")
    async def oidc_callback(provider: str, request: Request) -> JSONResponse:
        if provider not in providers:
            raise HTTPException(status_code=404, detail="unknown_route")
        state, code = request.query_params.get("state", ""), request.query_params.get("code", "")
        try:
            username = pending.finish(engine, providers[provider], state, code)
        except IntakeError as exc:
            raise fail(exc) from exc
        return start_session(username)

    @app.get("/tenants/{tenant_id}/cases")
    async def cases(tenant_id: str, request: Request) -> dict[str, Any]:
        role = tenant_role(session_of(request, unsafe=False), tenant_id)
        require(role, "view")
        return {
            "now": now().isoformat(),
            "cases": service.list_cases(engine, tenant_id, contracts[tenant_id]),
        }

    @app.get("/tenants/{tenant_id}/cases/{event_id}")
    async def case(tenant_id: str, event_id: str, request: Request) -> dict[str, Any]:
        role = tenant_role(session_of(request, unsafe=False), tenant_id)
        require(role, "view")
        try:
            view = service.view_case(engine, tenant_id, event_id)
        except IntakeError as exc:
            raise fail(exc) from exc
        contract = contracts[tenant_id]
        when = service.received_at(engine, tenant_id, event_id)
        view["received_at"] = when.isoformat() if when is not None else None
        view["fields"] = [
            {"name": name, "required": rule.required} for name, rule in contract.fields.items()
        ]
        view["sources"] = {name: src.trust for name, src in contract.sources.items()}
        view["role"] = role
        return view

    @app.post("/tenants/{tenant_id}/cases/{event_id}/decisions")
    async def decide(tenant_id: str, event_id: str, request: Request) -> JSONResponse:
        info = session_of(request, unsafe=True)
        role = tenant_role(info, tenant_id)
        data = await body_of(request)
        if not allowed(role, "decide"):
            raise HTTPException(status_code=403, detail="forbidden")
        decisions, version = data.get("decisions"), data.get("expected_version")
        if not isinstance(decisions, dict) or type(version) is not int:
            raise HTTPException(status_code=422, detail="invalid_review")
        reason = data.get("reason", "")
        try:
            result = service.submit_decisions(
                engine,
                tenant_id,
                event_id,
                info.username,
                role,
                decisions,
                contracts[tenant_id],
                expected_version=version,
                reason=reason if isinstance(reason, str) else "",
                now=now(),
            )
        except IntakeError as exc:
            raise fail(exc) from exc
        return JSONResponse(result, status_code=201)

    @app.post("/tenants/{tenant_id}/cases/{event_id}/amendments")
    async def amend(tenant_id: str, event_id: str, request: Request) -> JSONResponse:
        info = session_of(request, unsafe=True)
        role = tenant_role(info, tenant_id)
        data = await body_of(request)
        source, fields = data.get("source"), data.get("fields")
        if not allowed(role, "amend"):
            raise HTTPException(status_code=403, detail="forbidden")
        if not isinstance(source, str) or not isinstance(fields, dict):
            raise HTTPException(status_code=422, detail="invalid_amendment")
        try:
            result = service.amend_case(
                engine,
                tenant_id,
                event_id,
                info.username,
                role,
                source,
                fields,
                contracts[tenant_id],
                now=now(),
            )
        except IntakeError as exc:
            raise fail(exc) from exc
        return JSONResponse(result, status_code=201)

    @app.get("/audit/verify")
    async def verify(request: Request) -> dict[str, Any]:
        info = session_of(request, unsafe=False)
        tenant_id = request.query_params.get("tenant_id", "")
        role = tenant_role(info, tenant_id)
        if not allowed(role, "audit_verify"):
            raise HTTPException(status_code=403, detail="forbidden")
        return audit.verify_chain(engine, tenant_id)

    return app
