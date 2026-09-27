# ADR-0001: Offline-first intake review

Status: accepted for this prototype.

Keep the intake core pure and dependency-free. All examples use fictional data.
The loopback HTTP adapter and mock CRM are local boundaries, not real services.
This makes review, replay and rejection behavior demonstrable without access to
a customer account. Trade-off: the prototype does not authenticate requests or
model tenant isolation. Those are future changes, not promises of current safety.
