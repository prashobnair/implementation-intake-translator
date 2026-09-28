# API contracts

No live vendor endpoint is called in v0.3.0; fixtures are synthetic, not captures of vendor responses. The new webhook ingress receives data and does not make Zoho writes.

| Claim | Verified source | Consequence |
|---|---|---|
| Zoho CRM v8 Create Webhook supports custom headers with static custom parameters on POST/PUT | [Zoho CRM Create Webhook API](https://www.zoho.com/crm/developer/docs/api/v8/create-webhook.html), checked 2026-09-28 | Use a custom `X-Intake-Token` header for Zoho-origin POST. Configure a nonsecret module parameter too if required by the Zoho UI. |
| The `url_parameters` section says these apply only to GET; custom headers apply to POST/PUT | [Zoho CRM Create Webhook API](https://www.zoho.com/crm/developer/docs/api/v8/create-webhook.html), checked 2026-09-28 | Do not present a URL token as a supported Zoho POST setup. |

No live Zoho contract or org was exercised. Before a live setup, verify the exact account's UI, region, rate and security behavior separately. See [ADR-0003](adr/0003-zoho-webhook-auth.md).
