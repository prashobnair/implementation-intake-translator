# API contracts

No live vendor endpoint is called in v0.3.0; fixtures are synthetic, not captures of vendor responses. The new webhook ingress receives data and does not make Zoho writes.

| Claim | Verified source | Consequence |
|---|---|---|
| Zoho CRM v8 Create Webhook supports custom headers with static custom parameters on POST/PUT | [Zoho CRM Create Webhook API](https://www.zoho.com/crm/developer/docs/api/v8/create-webhook.html), checked 2026-09-28 | Use a custom `X-Intake-Token` header for Zoho-origin POST. Configure a nonsecret module parameter too if required by the Zoho UI. |
| The `url_parameters` section says these apply only to GET; custom headers apply to POST/PUT | [Zoho CRM Create Webhook API](https://www.zoho.com/crm/developer/docs/api/v8/create-webhook.html), checked 2026-09-28 | Do not present a URL token as a supported Zoho POST setup. |

No live Zoho contract or org was exercised. Before a live setup, verify the exact account's UI, region, rate and security behavior separately. See [ADR-0003](adr/0003-zoho-webhook-auth.md).

## Webhook request order (WP-23 correction)

Route lookup (404) -> content type (415) -> bounded read (413/408) -> authenticate (401) -> tenant rate limit (429) -> parse and validate (400/413/422) -> raw ledger row -> process. HMAC covers the raw body, API keys use the bearer header, and a shared token is verified before parsing; `event_id` is required only after the token passes. Credentials are compared as UTF-8 bytes and non-ASCII values return 401. The raw row is written before processing, so a ledger failure leaves no processed event without its raw record; rejected events keep an audit row.

## Review API v2 (authenticated)

All routes need a session cookie from `POST /login` (`{"username","password"}`). Unsafe methods also need the `X-CSRF-Token` returned at login. Roles are per tenant; a user outside a tenant gets 404 for its routes.

| Route | Role | Notes |
|---|---|---|
| `GET /tenants/{t}/cases`, `GET /tenants/{t}/cases/{id}` | viewer | status is `needs_review`, `deferred`, `approved` or `needs_re_review` |
| `POST /tenants/{t}/cases/{id}/decisions` | reviewer | body `{"decisions": {field: {type, ...}}, "expected_version": n}`. Types: `choose_source` (`source`), `override` (`value`, `rationale` of 20+ characters), `defer` (`question`). Stale version: 409 `{"detail":"review_conflict","current_version":n}` |
| `POST /tenants/{t}/cases/{id}/amendments` | reviewer | body `{"source","fields"}`; 201 with the diff, 409 if one is already open or the case is not approved |
| `GET /audit/verify?tenant_id=t` | admin | recomputes the tenant hash chain: `{"valid","entries","first_invalid_id"}` |
| `GET /auth/oidc/{provider}/start`, `.../callback` | none | only when providers are configured; the subject must be linked to an account first |

A case is approvable when every conflict and every required field without a value has a decision and none is deferred. A deferred submission records a version with state `deferred` and the customer questions. With `two_person_override: true` in the tenant contract, an override needs an approver or admin.
