# Five-minute local demo

This walkthrough uses fictional data and a local SQLite mock CRM. It needs Python 3.10+ and no API keys, network connection, Docker or app trials. Run from the repository root. On Windows, use a writable database path such as `demo.sqlite3` rather than `/tmp/...`.

1. Run the tests: `PYTHONPATH=src python3 -m unittest discover -s tests -v`.
2. Start with a clean demo database: `rm -f /tmp/intake-walkthrough.sqlite3` (or use a new path). Run `PYTHONPATH=src python3 -m intake_translator.cli examples/conflicting-intake.json --db /tmp/intake-walkthrough.sqlite3`. Point out the competing `form` and `crm` launch dates and `needs_review` status.
3. Attempt a downstream write before review: `PYTHONPATH=src python3 -m intake_translator.mock_crm fictional-nexaflow-deal-001 --db /tmp/intake-walkthrough.sqlite3`. It exits with `not_approved`; no project is created.
4. Inspect the fictional source dates, then create a choice file: `printf '{"launch_date":"crm"}\n' > /tmp/intake-choice.json`. Run `PYTHONPATH=src python3 -m intake_translator.review fictional-nexaflow-deal-001 /tmp/intake-choice.json --db /tmp/intake-walkthrough.sqlite3`. This local demo decision picks November 16 from CRM. It is not a real customer's approval.
5. Run `PYTHONPATH=src python3 -m intake_translator.mock_crm fictional-nexaflow-deal-001 --db /tmp/intake-walkthrough.sqlite3`. A local mock project is created with the reviewed launch date. Repeat the command: it returns the same project with `replayed: true`, not a duplicate. `mock_projects` is a SQLite table in the same local database, not Zoho or another service.

Optional HTTP intake demo: start `PYTHONPATH=src python3 -m intake_translator.http_api --db /tmp/intake-http-demo.sqlite3 --port 8765`, then POST `examples/conflicting-intake.json` to `http://127.0.0.1:8765/intakes` as shown in the README. Review and mock CRM remain separate CLI commands sharing the `--db` path. Do not tunnel or expose this unauthenticated loopback service.

A Zoho or other trial account is **not needed** for this version. No trial setup, credentials or real CRM integration are hidden prerequisites. A future live adapter would need its own setup guide and a safe test tenant; do not connect this prototype to a real customer account. For now, the demo is intentionally local and synthetic.
