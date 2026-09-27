# Security

Please report a vulnerability privately through GitHub's **Report a vulnerability**
button in this repository's Security tab, if enabled. Otherwise open an issue
without exploit details asking for a private contact route. Do not publish
credentials, customer records or exploit details in an issue.

The current tool is an offline, synthetic-data demonstration, not a hosted
service. Its HTTP adapter binds to loopback only. Do not expose or tunnel it.
It never connects to Zoho, sends messages or approves a review automatically.
The local mock database is disposable. Do not put real customer data in fixtures,
issues, pull requests, logs or screenshots.

Supported versions: 0.2.x. There is no security SLA for older versions.
