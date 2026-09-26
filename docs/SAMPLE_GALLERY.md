# Synthetic input and output gallery

All names and system records here are fictional. `examples/source-shapes.json` illustrates *possible* form submission, CRM deal properties and meeting-note decisions. It is **not** a captured or official Zoho, Typeform, Salesforce or other vendor payload. `sample-mapping.json` lists the configuration that turns those three sample record shapes into the version-1 normalized contract. This repository does not connect to any app or need a trial account.

From the repository root, run:

```sh
PYTHONPATH=src python3 -m intake_translator.sample_mapping examples/source-shapes.json examples/sample-mapping.json > /tmp/mapped-intake.json
PYTHONPATH=src python3 -m intake_translator.cli /tmp/mapped-intake.json --db /tmp/gallery-mapped.sqlite3
```

The mapping is explicit: `form_submission.fields[key=go_live_date].answer` becomes `sources.form.launch_date`; `crm_deal_record.properties.Target_Go_Live` becomes `sources.crm.launch_date`; `meeting_notes.decisions[topic=launch date].value` becomes `sources.notes.launch_date`. Similar keys map name, seat count and region. If a configured key is absent or repeated in a list, mapping fails rather than silently dropping a source. The mapped packet is `needs_review`, with launch dates `2026-12-01` from form/notes and `2026-12-15` from CRM. It does not choose the date.

For ready-to-run normalized examples, use a **fresh `--db` path per example** (event IDs can be replayed by design):

| Input | Expected result from `PYTHONPATH=src python3 -m intake_translator.cli examples/NAME --db /tmp/NAME.sqlite3` |
| --- | --- |
| `good-agreement.json` | Exit 0, `needs_review`, `conflicts: {}`, `questions: []`, resolved launch `2026-12-01`, seats `40`. Agreement does **not** auto-approve. |
| `bad-conflict.json` | Exit 0, `needs_review`; `launch_date` conflict retains form `2026-12-01`, CRM `2026-12-15`, notes `2026-12-01`; question asks which date is correct. |
| `bad-missing-required.json` | Exit 0, `needs_review`; no launch date; question `What is the launch date?`. The review gate refuses approval of a required field with no source candidate. |
| `bad-invalid-date.json` | Exit 2, `invalid_field: launch_date is not a calendar date` (February 30). Nothing is stored. |
| `bad-unknown-field.json` | Exit 2, `invalid_field: form has unknown fields: unmapped_budget`. Unknown data is not silently accepted. |
| `bad-unsupported-version.json` | Exit 2, `unsupported_version: schema_version must be 1`. Version drift is explicit. |

A "bad" conflict or missing field is still valid JSON, so its output is a **review packet** rather than an HTTP error. The last three inputs fail validation. To see downstream gating and idempotent local mock project creation, follow `docs/DEMO.md`. No sample contains employer or customer data.
