# Threat model (local prototype)

| Threat | Boundary | Current mitigation | Gap |
|---|---|---|---|
| Spoofed intake | HTTP adapter | Loopback bind and body cap | No authentication; never expose adapter |
| Payload replay | SQLite ledger | Event ID and digest, reject changed reuse | IDs not tenant-scoped |
| Unreviewed output | Review gate | Explicit source selection before local mock | No reviewer identity |
| Data leak | Fixtures / logs | Synthetic inputs, no external sends | Real data prohibited |
| Availability | Local service | Read timeout, bounded request size | Not production-hardened |
