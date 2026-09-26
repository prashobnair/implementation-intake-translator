# Implementation Intake Translator

A fictional SaaS implementation handoff, inspired by the operational problem of mismatched form, CRM and meeting-note facts. This is a **local prototype**, not a live integration or production deployment. It never creates a project or contacts a customer.

## What it does

- Accepts schema-versioned JSON from up to three synthetic sources: form, CRM and notes, via CLI or a loopback-only HTTP adapter.
- Normalizes whitespace, validates field types and dates, preserves source provenance.
- Resolves an agreed value but makes conflicting values and missing required facts into human-review questions.
- Stores an event ID and SHA-256 digest in local SQLite. The same event replays the same packet; a reused ID with changed content fails.
- Emits a review packet and never auto-approves. A separate local CLI review gate accepts explicit source choices for conflicts. Only after that decision can a local mock CRM project be written.

## How to run and demo

For a screen-share dashboard, run `PYTHONPATH=src python3 -m intake_translator.dashboard` from the repository root, then open the printed `file://` URL in a browser. It generates an offline, read-only HTML snapshot of six cases, the review gate and local mock project, and deletes the temporary database. No server or internet access is needed. For a five-minute manual walkthrough, follow `docs/DEMO.md`. For configurable fictional source shapes plus good and bad sample inputs with expected outputs, see `docs/SAMPLE_GALLERY.md` and `examples/`. **No Zoho or other app trial is needed** for this version: its CRM is a local SQLite mock, not a real service. Python 3.10+ is the only prerequisite. Future live integrations will need separately documented trial account setup and credentials; no real customer system should be connected to this prototype.


Requires Python 3.10+; runtime is standard-library only. From this repository root, the shortest complete demo is `PYTHONPATH=src python3 -m intake_translator.demo`. It runs every sample, blocks an unreviewed mock write, applies a fictional review decision, creates and replays one local mock project, then deletes its temporary database. For manual steps:

```sh
PYTHONPATH=src python3 -m intake_translator.cli examples/conflicting-intake.json --db /tmp/intake-demo.sqlite3
PYTHONPATH=src python3 -m intake_translator.cli examples/conflicting-intake.json --db /tmp/intake-demo.sqlite3
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The second invocation sets `replayed: true`. For the local HTTP demo:

```sh
PYTHONPATH=src python3 -m intake_translator.http_api --db /tmp/intake-http-demo.sqlite3 --port 8765
# In another shell, from the repository root:
curl -i -H 'Content-Type: application/json' --data-binary @examples/conflicting-intake.json http://127.0.0.1:8765/intakes
```

To try the separate local review gate, inspect the packet and follow `docs/REVIEW_GATE.md`. The HTTP adapter binds to `127.0.0.1` only and has a bounded body and read timeout; do not expose or tunnel it. Its routes, response codes and limits are in `docs/HTTP_CONTRACT.md`. Delete demo databases when finished. No work account or external network access is needed.

## Current limits and next design gate

This increment adds a local HTTP boundary, not a signed webhook or deployable API. It is not yet a real CRM adapter, authenticated approval workflow, Docker setup or an audited deployment. A local source-selection decision does not establish customer approval; the only downstream write is to a local mock table, never to a customer system. The digest compares raw JSON values after canonical key sorting: normalized semantic equivalents with changed raw values are treated as a changed payload. An event ID is global in V1; a future multi-tenant design must scope it by tenant and authenticate the source before network intake. SQLite is local, not a distributed queue. Future work: signed webhook ingress, tenant scoping, authenticated review and amendments, reconciliation, failure tests, and operating docs. A GitHub Actions workflow runs tests and the disposable demo on Python 3.10-3.12; its status depends on GitHub Actions being enabled for this private repo. See `docs/ARCHITECTURE.md`.
