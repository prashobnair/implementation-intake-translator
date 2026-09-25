# Engineering review

V1 is a local prototype, not a deployed integration. A reviewer should ask whether a conflicting source value is correctly preserved; whether missing and invalid values are distinct; how a replay behaves when the event ID is reused with a changed body; and whether any downstream action could happen before a human signs off. The current CLI has no downstream action.

Known weaknesses: event IDs are not tenant-scoped, there is no authentication or input-size cap, and raw payload hashing regards harmless whitespace changes as a changed event. SQLite is adequate for a local demonstration but not a multi-worker service. There is no HTTP adapter, migration plan, telemetry, CI or packaged demo. A future public release should add an explicit license and independent security review. Until then, do not connect employer systems or copy customer data into fixtures.

Next review gate: expose a mock HTTP contract with bounded payloads, tenant-aware idempotency, approval versioning, and tests for concurrent delivery, replay, malformed input and partial downstream failure. Preserve the exact source records and explain why a field was accepted or held for review.
