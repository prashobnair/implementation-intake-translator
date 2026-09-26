# Engineering review

V1 is a local prototype, not a deployed integration. A reviewer should ask whether a conflicting source value is correctly preserved; whether missing and invalid values are distinct; how a replay behaves when the event ID is reused with a changed body; and whether any downstream action could happen before a human signs off. The current CLI has no downstream action.

Known weaknesses: event IDs are not tenant-scoped, there is no authentication (HTTP bodies are capped at 16 KiB), and raw payload hashing regards harmless whitespace changes as a changed event. SQLite is adequate for a local demonstration but not a multi-worker service. A loopback-only HTTP adapter and local review CLI now exist, but there is no authenticated webhook, real CRM adapter, migration plan, telemetry or CI. A local demo walkthrough is provided. A future public release should add an explicit license and independent security review. Until then, do not connect employer systems or copy customer data into fixtures.

Next review gate: tenant-aware idempotency, signed webhook ingress, authenticated approval with amendments, and tests for partial failure across a real downstream boundary. The local mock write has failure/retry tests. Preserve the exact source records and explain why a field was accepted or held for review.
