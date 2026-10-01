# Threat model (synthetic intake)

| STRIDE threat | Boundary | Mitigation | Residual risk / test |
|---|---|---|---|
| Spoofed webhooks | Ingress | HMAC timestamp/body signature and per-tenant/source key; Zoho shared-token header fallback with optional IP allowlist | Static token theft can forge a body; rotate out of band and inspect the audit mode; HMAC and token tests |
| Replay or changed event | Ledger | `(tenant_id, source, event_id)` + SHA-256 of raw or normalized content, SQLite `BEGIN IMMEDIATE` | Stolen shared token may submit a new ID; replay and collision tests |
| Tenant confusion | API/storage | Repository requires tenant and source on reads/writes; no global ID lookup | Deployment must trust only an authenticated tenant mapping; randomized interleaving test |
| Reviewer impersonation | Review records | Actor/version recorded; API keys hashed and scoped | Authenticated human review UI is WP-24; no public reviewer route in v0.3 |
| Prompt injection through notes | Packet generation | Notes treated as data; no AI executor or outbound action | Future AI layer needs cited, opt-in evaluation and content isolation |
| Outbox double-apply | Projectors | No external projectors enabled at v0.3; local mock requires review and idempotent event ID | Transactional outbox and crash test planned for WP-26; never claim exactly-once external writes now |
| PII disclosure | Raw event storage | Fernet ciphertext, environment key, digest-only retention after 30 days; body size and depth bounds; explicit purge command required | Key management, backups and purge scheduling need deployment controls |
| Denial of service | Ingress | Default 16 KiB body limit, depth cap, per-tenant token bucket 429 | Per-request stream timeout implemented; proxy cap and distributed limiter needed before public deployment |

No real customer or employer data, secrets or live Zoho writes belong in fixtures or CI.
