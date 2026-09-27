# Changelog

All notable changes to this project are documented here. The project follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and semantic versioning.

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

## [Unreleased]

### Added
- Layered service architecture: FastAPI local adapter and retained stdlib compatibility, tenant-scoped SQLAlchemy models and Alembic 0001 migration preserving v0.2 packets.
