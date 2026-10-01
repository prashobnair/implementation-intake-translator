# API contracts

No live vendor endpoint is called in v0.3.0; fixtures are synthetic, not captures of vendor responses. The new webhook ingress receives data and does not make Zoho writes.

| Claim | Verified source | Consequence |
|---|---|---|
| Zoho CRM v8 Create Webhook supports custom headers with static custom parameters on POST/PUT | [Zoho CRM Create Webhook API](https://www.zoho.com/crm/developer/docs/api/v8/create-webhook.html), checked 2026-09-28 | Use a custom `X-Intake-Token` header for Zoho-origin POST. Configure a nonsecret module parameter too if required by the Zoho UI. |
| The `url_parameters` section says these apply only to GET; custom headers apply to POST/PUT | [Zoho CRM Create Webhook API](https://www.zoho.com/crm/developer/docs/api/v8/create-webhook.html), checked 2026-09-28 | Do not present a URL token as a supported Zoho POST setup. |

No live Zoho contract or org was exercised. Before a live setup, verify the exact account's UI, region, rate and security behavior separately. See [ADR-0003](adr/0003-zoho-webhook-auth.md).

## Webhook request order (WP-23 correction)

Route lookup (404) -> content type (415) -> bounded read (413/408) -> authenticate (401) -> tenant rate limit (429) -> parse and validate (400/413/422) -> raw ledger row -> process. HMAC covers the raw body, API keys use the bearer header, and a shared token is verified before parsing; `event_id` is required only after the token passes. Credentials are compared as UTF-8 bytes and non-ASCII values return 401. The raw row is written before processing, so a ledger failure leaves no processed event without its raw record; rejected events keep an audit row.
