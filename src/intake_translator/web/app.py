"""FastAPI replacement for the local-only stdlib adapter."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from ..core import IntakeError
from ..store import process_once


def create_app(db_path: str, *, max_body_bytes: int = 16 * 1024) -> FastAPI:
    """Build the local service; external exposure still needs authentication."""
    app = FastAPI(title="Synthetic Intake Translator", docs_url=None, redoc_url=None)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "intake-translator"}

    @app.post("/intakes")
    async def intake(request: Request) -> JSONResponse:
        if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
            raise HTTPException(status_code=415, detail="unsupported_media_type")
        # Stream-bound before buffering the full body. Never expose this unauthenticated demo.
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > max_body_bytes:
                raise HTTPException(status_code=413, detail="payload_too_large")
        try:
            import json

            event: Any = json.loads(body)
            packet, replayed = process_once(db_path, event)
            return JSONResponse(
                {**packet, "replayed": replayed}, status_code=200 if replayed else 201
            )
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(status_code=400, detail="invalid_json") from exc
        except IntakeError as exc:
            raise HTTPException(
                status_code=409 if exc.code == "event_id_reused" else 422, detail=exc.code
            ) from exc

    return app
