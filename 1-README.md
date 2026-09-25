# Implementation Intake Translator

A fictional SaaS implementation handoff, inspired by the operational problem of mismatched form, CRM and meeting-note facts. This is a **local V1 prototype**, not a live integration or production deployment. It never creates a project or contacts a customer.

## What it does

- Accepts schema-versioned JSON from up to three synthetic sources: form, CRM and notes.
- Normalizes whitespace, validates field types and dates, preserves source provenance.
- Resolves an agreed value but makes conflicting values and missing required facts into human-review questions.
- Stores an event ID and SHA-256 digest in local SQLite. The same event replays the same packet; a reused ID with changed content fails.
- Emits a review packet, not an approved specification. Even conflict-free input stays `needs_review` until a later approval workflow is designed.

## Run locally

Requires Python 3.10+; runtime is standard-library only. From this repository root:

```sh
PYTHONPATH=src python3 -m intake_translator.cli examples/conflicting-intake.json --db /tmp/intake-demo.sqlite3
PYTHONPATH=src python3 -m intake_translator.cli examples/conflicting-intake.json --db /tmp/intake-demo.sqlite3
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The second invocation sets `replayed: true`. Delete the demo database when finished. No work account or network access is needed.

## Current limits and next design gate

This increment is intentionally a CLI slice. It is not yet the proposed HTTP API, mock CRM adapter, approval state, Docker setup or an audited deployment. No owner approval or downstream side effect occurs. The digest compares raw JSON values after canonical key sorting: normalized semantic equivalents with changed raw values are treated as a changed payload. An event ID is global in V1; a future multi-tenant design must scope it by tenant and authenticate the source before network intake. SQLite is local, not a distributed queue. Future work: define a signed webhook contract and real HTTP errors, durable review state and approval versioning, reconciliation, failure tests, CI, and operating docs. See `docs/ARCHITECTURE.md`.
