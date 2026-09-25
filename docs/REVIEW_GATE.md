# Local review gate

This is a synthetic, local decision exercise, not a customer approval or production workflow. A person must inspect the intake packet and put a source choice for **each conflicting field** in a JSON file. For `examples/conflicting-intake.json`, write `{"launch_date":"crm"}` to `/tmp/intake-review.json` after comparing the fictional evidence. Then run:

```sh
PYTHONPATH=src python3 -m intake_translator.cli examples/conflicting-intake.json --db /tmp/intake-review-demo.sqlite3
PYTHONPATH=src python3 -m intake_translator.review fictional-nexaflow-deal-001 /tmp/intake-review.json --db /tmp/intake-review-demo.sqlite3
```

The reviewer selects a source already present in each conflict. Invented values, missing choices and missing required fields are rejected; no automatic winner is chosen. The original `needs_review` packet is immutable in `processed_events`. A separate `review_decisions` row stores the chosen sources and the approved packet at `review_version: 1`. A replay of identical decisions returns the stored packet; conflicting later decisions fail. SQLite's immediate transaction serializes competing reviewers. No HTTP approval endpoint or downstream project write exists.

The prototype has no reviewer identity, authorization, audit-grade timestamps or amendment workflow. Do not interpret the `approved` status as a real customer's consent. A real deployment needs authenticated reviewer identities, scope checks, a migration and reconciliation plan, decision rationale, and signed webhook ingress before connecting customer systems.
