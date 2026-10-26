# Reconciler identity deployment gate — staging only

**No live deployment is authorized by this document.** A bearer token accepted by an HTTPS endpoint is not proof of a separate database identity unless the receiving gateway validates it and maps it to restricted database permissions.

## Required receiving-side implementation

1. Provision a dedicated reconciler identity at the gateway or identity provider, with short-lived, audience-bound credentials. Never reuse Supabase `service_role` or trading executor credentials.
2. Verify the credential's signature (or introspect it), issuer, audience, expiration, not-before, and reconciler-specific role/scope on **every** request. Reject missing, revoked, replayed, expired, wrong-audience or wrong-scope credentials. Never trust a caller-provided `authorized` boolean.
3. Route only three allowlisted reconciler RPCs through the gateway; validate parameter types and request sizes. Independently verify exchange evidence before invoking any privileged state transition.
4. Bind the gateway's database connection to the separately scoped `bot_reconciler` permissions, with no direct DML on protected tables. Do not assume a Supabase service-role token becomes restricted because the application checks scopes.
5. Keep routine executors on their own restricted reservation-RPC principal. Remove service-role direct table writes and routine RPC rights **only after** migrating and testing every caller.
6. Configure secret storage, rotation, revocation, TLS trust, audit logging and an emergency fail-closed disable switch outside source control.

## Approval evidence before cutover

- End-to-end tests using a real gateway-issued test identity and a separate executor identity: permitted reconciler RPC succeeds; routine executor cannot release or mark closed; reconciler cannot reserve or directly write.
- Invalid/expired/revoked token, wrong audience, wrong role, duplicate requests, stale or partial exchange evidence, restart and transport-failure tests all fail closed.
- Review database grants against the actual deployed connection identity, not just disposable PostgreSQL roles.
- Explicit approval for credentials, migrations, rollout and rollback; keep all bots OFF until approved.

**Known blocker:** The repository's staging `authenticated_rpc(..., authorized=True)` is only a caller assertion; the HTTPS transport injects a token but does not verify the receiving service. Neither constitutes completed authentication.
