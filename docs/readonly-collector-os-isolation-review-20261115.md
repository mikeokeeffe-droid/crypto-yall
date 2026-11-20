# Offline-only read-only collector OS isolation design — NOT A SERVICE

**15 November 2026. PR #42 remains DRAFT / LIVE NO-GO.**

`sender_review/ci_only_readonly_collector_review.service` is an intentionally
inert *systemd source fixture*. It has `ExecStart=/usr/bin/false`, a
deliberately nonexistent condition, manual-start refusal, and no
`[Install]` stanza. **Never install, link, enable or start it.**

The source-only tests check that the file cannot acquire unexpected
privileges, writable mounts, environment/credential overrides, network
families, sockets, executable commands or startup hooks. The fixture
describes a strongly isolated **non-networked** process with no access to
trading keys or database credentials.

This is not a working Hyperliquid collector: a future real read-only
collector needs restricted outbound HTTPS. Its egress policy would require
a *different*, independently reviewed unit and host firewall/proxy policy,
and verified authentication, TLS, endpoint allowlisting and actual
historical completeness rules. Turning off `PrivateNetwork` in this
fixture or adding trading credentials would violate its NO-GO purpose.

Before a real deployment, independently check effective systemd properties,
host firewall/network namespaces, file access, service user and inherited
credentials, container/runtime capabilities, actual process behavior,
monitoring, rate limits and restarts. Source tests cannot prove operational
host isolation and must never be treated as permission to deploy, submit
orders or perform emergency closes.

**No production host, original GitHub Actions trading workflow, wallet,
exchange endpoint, Supabase or deployed service was changed.**
