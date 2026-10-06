# Changelog

All notable changes to this project are documented here. The project follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and semantic versioning.

## [Unreleased]

### Added
- Review workflow v2 API: local accounts with argon2id passwords, secure session cookies with CSRF checks, optional GitHub or Google sign-in for pre-linked accounts, and per-tenant roles (viewer, reviewer, approver, admin).
- Typed field decisions (choose a source, override with a written rationale, defer with a customer question), versioned reviews with optimistic concurrency (a stale version returns 409 and the current version), and an optional two-person rule for overrides.
- Amendments: new evidence on an approved case reopens it with a field-level diff; approving creates the next version.
- Hash-chained audit log per tenant with `GET /audit/verify`.
- Alembic migration 0002 for the new tables. Existing v0.3 review rows stay valid.

## [0.3.0] - 2026-10-01

### Added
- Layered service architecture: a local FastAPI adapter alongside the stdlib server, tenant-scoped SQLAlchemy storage, and an Alembic migration that keeps v0.2 packets readable.
- Tenant field contracts: typed fields, per-source display order and trust, with synthetic example contracts. Schema v2 events use the tenant contract; v1 events replay exactly as before.
- Semantic digest option: equivalent normalized values replay instead of conflicting. The default digest stays raw.
- Unanimous review policy: a packet is approved automatically only when required fields agree and no AI source took part. The decision is recorded as a versioned review. Off by default.
- Authenticated tenant webhook ingress with three modes: HMAC-signed bodies with a five-minute clock window and key rotation, a shared token header for Zoho-style webhooks, and per-tenant API keys stored only as hashes.
- Request limits: body size, JSON depth, read time and a per-tenant rate limit. Unauthenticated callers get a flat 401 and no parse or validation detail.
- Encrypted raw-event ledger with 30-day body erasure that keeps the digest, scope, time and auth mode for audit.
- Numeric normalization accepts ASCII digits only and rejects exponent notation, underscores and Arabic-Indic digits.
- Threat model and a decision record for webhook authentication.

### Changed
- The pure core may not import the legacy service and storage modules, as well as the new layers.

### Fixed
- A non-ASCII credential header no longer crashes the webhook with a 500. It returns 401.
- A raw-ledger failure can no longer leave a processed event without its raw record.

## [0.2.1] - 2026-09-27

### Added
- MIT license, contribution and security guidance, templates and dependency updates.
- uv lockfile, Python 3.11-3.13 CI, lint, typing, security and core-only jobs.
- Explicit `first_source_priority` display policy and regression coverage.

### Changed
- README now leads with the problem and offline demo rather than repeated caveats.
- Python support starts at 3.11. The core keeps zero runtime dependencies.

## [0.2.0] - 2026-09-27

### Added
- Local review gate, mock-CRM projection and offline dashboard.
