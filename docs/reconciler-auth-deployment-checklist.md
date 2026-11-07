# Reconciler identity deployment gate — staging only

**No live deployment is authorized by this document.** A bearer token accepted by an HTTPS endpoint is not proof of a separate database identity unless the receiving gateway validates it and maps it to restricted database permissions.

## Required receiving-side implementation

1. Provision a dedicated reconciler identity at the gateway or identity provider, with short-lived, audience-bound credentials. Never reuse Supabase `service_role` or trading executor credentials.
2. Verify the credential's signature (or introspect it), issuer, audience, expiration, not-before, and reconciler-specific role/scope on **every** request. Reject missing, revoked, replayed, expired, wrong-audience or wrong-scope credentials. Never trust a caller-provided `authorized` boolean.
3. Route only the fixed reconciliation operations through the callable receiver. Its server-side RPC transport allowlists the required intent-read, handoff, close, and release functions; callers cannot select an RPC. Validate parameter types and request sizes, and independently verify exchange evidence before invoking any privileged state transition.
4. Bind the gateway's database connection to the separately scoped `bot_reconciler` permissions, with no direct DML on protected tables. Do not assume a Supabase service-role token becomes restricted because the application checks scopes.
5. Keep routine executors on their own restricted reservation-RPC principal. Remove service-role direct table writes and routine RPC rights **only after** migrating and testing every caller.
6. Configure secret storage, rotation, revocation, TLS trust, audit logging and an emergency fail-closed disable switch outside source control.

## Approval evidence before cutover

- End-to-end tests using a real gateway-issued test identity and a separate executor identity: permitted reconciler RPC succeeds; routine executor cannot release or mark closed; reconciler cannot reserve or directly write.
- Invalid/expired/revoked token, wrong audience, wrong role, duplicate requests, stale or partial exchange evidence, restart and transport-failure tests all fail closed.
- Review database grants against the actual deployed connection identity, not just disposable PostgreSQL roles.
- Explicit approval for credentials, migrations, rollout and rollback; keep all bots OFF until approved.

**Implementation update:** `trusted_reconciler_receiver_staging.py` now provides a callable-only WSGI receiving boundary. It verifies bot-specific JWTs through the existing dispatcher, binds each bot to server-configured exchange and restricted PostgreSQL principals, and rejects caller-supplied credentials, RPC names, or evidence assertions. The internal `authenticated_rpc(..., authorized=True)` helper is still only a caller assertion and must not be exposed as an endpoint.

**Remaining blocker:** The receiver is not deployed, does not create a listener, and has no real identity provider, secret manager, TLS ingress, or staging identities. Disposable tests do not establish staging grants or operational readiness.

## Database identity preflight

The repository now includes `db/entry_reservation_identity_preflight_staging.sql`, a read-only assertion script that checks effective privileges and the presence of distinct roles in a disposable CI database. It does not create credentials or prove a production identity mapping. The `bot_entry_executor_trial` role is NOLOGIN and is **not** a deployable production executor principal. A database administrator must inspect actual staging grants, role inheritance, credential mapping, and caller migration before proposing any production change.
