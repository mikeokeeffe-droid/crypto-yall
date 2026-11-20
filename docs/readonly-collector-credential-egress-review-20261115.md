# Read-only collector credential and egress policy — OFFLINE ONLY

**15 November 2026. No service installation, networking or trade authorization.**

The review fixture `sender_review/ci_only_collector_credentials_egress_policy.json`
is explicitly disabled. Its only permitted runtime state is NO-GO.

The review-only proposal records a future **testnet** HTTPS host,
`api.hyperliquid-testnet.xyz`, port 443, endpoint `/info`, and the
documented read-only query types. These are **design values only** and are
not granted to a running process.

The fixture denies any secret name, inherited credential, private key,
environment file, credential mount, writable database role, listener,
outbound socket or actual network activation. It records all runtime
isolation, source authenticity, TLS and operator evidence as **unverified**.

An offline static validator cross-checks the JSON and the previously
committed inert `.service` fixture. Its negative tests reject modified
endpoints, arbitrary DNS/proxies, redirects, network activation, altered
OS restrictions, claimed host attestation, trading permissions and
introduced credentials.

**Important limitations:** Static source checks cannot prove actual
firewall rules, TLS validation, service environment, process credentials
or effective systemd isolation. Future network-enabled read-only
collection will need a *different* independent security review of
the actual host, network proxy/firewall, executable and effective
permissions; the existing unit must never be enabled or relaxed.

No original bot workflow, production systemd unit, Render/Supabase
service, wallet or exchange endpoint has been changed.

**PR #42 remains DRAFT. TESTNET / LIVE NO-GO.**
