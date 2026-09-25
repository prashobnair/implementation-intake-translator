# V1 design record

Problem: three fictional intake sources can disagree on launch date or scope. A silent winner would misstate the contract and trigger rework. This slice validates and presents evidence for a human, not an autonomous project creator.

Flow: JSON file -> strict version/field validation -> canonical normalized candidate values -> conflicts and unresolved questions -> SQLite idempotency record -> review packet on stdout. Business logic is pure and testable; storage handles at-least-once delivery. Each packet is `needs_review`, even when sources agree.

Trade-offs: standard-library CLI and SQLite let a reviewer run the demo without SaaS credentials or Docker. The advertised future Python HTTP service and mock API are not yet implemented. Separate tests cover duplicate delivery, event-ID payload collision, missing required field, malformed date and unknown schema/fields. No personal, employer or production customer data belongs in the fixture.

Known gaps: concurrent SQLite writes are serialized via `BEGIN IMMEDIATE`, but this has not been load-tested; no authentication, authorization, real webhook signature, input-body size cap, metrics, approval workflow, DB migration, or disaster recovery. Do not expose this CLI as an internet service. A future HTTP boundary must reject large payloads and protect logs. Only human-reviewed requirements may ever drive downstream project creation.
