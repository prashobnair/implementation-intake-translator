# Local HTTP contract (v0.2)

Run `PYTHONPATH=src python3 -m intake_translator.http_api --db /tmp/intake-http-demo.sqlite3 --port 8765`, then in another shell:

```sh
curl -i -H 'Content-Type: application/json' --data-binary @examples/conflicting-intake.json http://127.0.0.1:8765/intakes
curl -i http://127.0.0.1:8765/health
```

`POST /intakes` accepts a version `1` JSON object with `event_id` (1-100 safe characters) and a `sources` object containing at least one of `form`, `crm`, `notes`. Allowed fields are `customer_name`, `launch_date` (ISO calendar date), `seat_count` (positive integer), and `region`. The response preserves candidates on disagreement, lists questions, and remains `needs_review`; it never creates projects or sends messages. New event: HTTP 201, `replayed:false`. Same event ID and identical canonical JSON: HTTP 200, `replayed:true`. Reused ID with a different payload: 409. Invalid schema/field: 422. Invalid JSON: 400. Wrong content type: 415. Body over 16 KiB: 413. Unknown route: 404. `GET /health` returns 200.

This is **loopback-only** and deliberately lacks authentication and TLS. Do not expose it through a tunnel or bind it to a public interface. The boundary does not yet handle chunked transfer or trust-proxy headers. It keeps neither raw request bodies nor payloads in logs, but the local SQLite packet can hold synthetic customer names. Delete the demo database when finished. Before production use, add source authentication/signature verification, tenant scope, transport security, request timeout policy, observability, migrations and threat review.
