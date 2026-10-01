# ADR-0003: Zoho CRM webhook authentication

Status: proposed for WP-23 review (2026-09-28).

## Context

The inbound service prefers a per-tenant/per-source HMAC-SHA256 signature over `timestamp + "." + raw_body` with a five-minute window and two-key rotation. Zoho CRM workflow webhooks do not provide a documented way to calculate that signature over the outbound body. The weaker compatible route is a static shared token. This is authentication, not a claim that payloads are cryptographically signed.

Zoho CRM's [Create Webhook API](https://www.zoho.com/crm/developer/docs/api/v8/create-webhook.html) documents custom headers on POST/PUT. Its `url_parameters` section says these apply only to GET. Because this service ingests a POST body, configure a static secret as a custom header, not a URL parameter. A server could accept a URL token for non-Zoho custom clients, but putting a secret in a URL leaks it to logs and is not recommended. Do not claim Zoho POST supports it.

## Decision

For Zoho-origin POST, require a scoped `X-Intake-Token` custom header and nonempty `event_id`. Optionally restrict the peer IP to a maintained allowlist, but do not treat an IP address as the only authentication factor. Provision tokens outside source control. Record `auth_mode: shared_token` in the audit record/UI so reviewers see the lower assurance. For capable clients use `X-Intake-Timestamp` and `X-Intake-Signature: sha256=<hex>` HMAC. Compare in constant time, reject stale timestamps and rotate with two active keys. TLS and a trusted reverse proxy remain deployment requirements. Never log a token or raw PII.

## Consequences

A stolen token can forge an event, and a static token has no body integrity or timestamp freshness. Rotate it, keep the service behind TLS, rate-limit by tenant, cap bodies, reject reused event IDs with changed payloads and make review explicit. The HMAC route is stronger but unavailable for the documented Zoho CRM webhook shape.
