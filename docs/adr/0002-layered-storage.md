# ADR-0002: Layers and versioned storage

The v0.2 prototype has a pure `core.py`, a loopback-only stdlib HTTP adapter, and one local SQLite ledger. v0.3 adds separate ingress, storage, review, outbox, projector, AI, web and connector package boundaries. Core must not import these service/I/O layers. An import-linter contract in `pyproject.toml` is checked in CI.

`web.app.create_app` is the FastAPI service entry point. Its v1 `/intakes` route retains the packet/replay behavior for the local synthetic demo; it is not authenticated and must not be exposed publicly. The stdlib adapter is kept as `http_api_legacy` through v1.0, with `http_api` as a compatibility alias so old imports and CLI invocations still work. The signed tenant ingress is planned next and will supersede this local route.

SQLAlchemy 2 models provide tenant-scoped `processed_events_v2` plus review, raw-event and machine-key tables. Alembic revision `0001` preserves existing v0.2 `processed_events`, `review_decisions` and `mock_projects` rows and makes them replayable by the legacy functions. SQLite enables WAL and serializes writes with `BEGIN IMMEDIATE`; Postgres uses the same repository API and needs a server test before production claims. No real customer data or external service is involved.
