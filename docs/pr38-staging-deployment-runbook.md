# PR #38 — staging gateway deployment-readiness runbook

**Status: reviewed preparation only. Not an authorization to provision or deploy.**
This procedure is for a separately approved, isolated staging environment. It
must never be run against production or used to enable live trading. No service,
listener, or real credential is provisioned by this document.

## Current design and hard stops

The HTTP gateway is a WSGI callable in
[`staging_executor_http_gateway.py`](../staging_executor_http_gateway.py), not a
server. It accepts a bot, coin, and entry action, verifies a bot-specific JWT,
and invokes only the reservation/intent RPC allowlist using that bot's configured
database connection. A successful response means a reservation and durable
intent were claimed; it is **not** order authorization, and the handler has no
exchange-order capability.

PostgreSQL maps `aggressive`, `intraday`, and `daily` to unique LOGIN names in
`bot_entry_executor_identities`. The RPCs compare the requested bot with
`session_user`, which a client parameter or `SET ROLE` cannot change. The
`bot_entry_executor_trial` role is a shared, non-LOGIN capability role, not an
identity: each bot must use a distinct LOGIN and mapping. Database superusers
are trusted administrators and bypass this isolation; they must never be used
by the app.

**Do not proceed** unless the target is positively verified as a dedicated
staging database, an independent approver authorizes the specific change, all
callers and grants have been inventoried, and rollback has been rehearsed in a
disposable database. Keep the route unmounted and all live-entry blocks in
place if any check is absent or fails.

## 1. Target and change authorization

Before any real staging change, record:

- Staging project/database identity, owner, region, endpoint, and change window.
- A named migration operator and independent database/security approver.
- The exact SQL files and reviewed checksums to be applied.
- Current effective grants, role memberships, routine owners, schema privileges,
  active callers, and a restorable staging backup.
- A rollback owner, stop condition, evidence location, and staging-only test
  plan. Keep audit evidence free of secrets.

Use an isolated staging project with no production credentials, no production
data, and no exchange-order permission. Do not infer the environment from a
hostname alone; verify `current_database()`, server/project identity, and
operator-side environment labels through the approved staging control plane.
This runbook intentionally supplies no Supabase endpoint or credential.

## 2. Database provisioning sequence

Use the approved migration/admin connection only for the following schema and
role work. Never use that connection in the gateway. First inspect the scripts
and current catalog state; the SQL is staging-only and is not an idempotent
rollback plan.

1. In the verified disposable/staging database, apply the reviewed reservation
   schema `db/entry_reservations_staging.sql`.
2. Apply the position ownership schema `db/position_ownership_staging.sql` and
   the separately reviewed reconciler role setup
   `db/trusted_reconciler_role_staging.sql` if the intended staging contract
   includes reconciliation. Do not grant the executor permission to resolve
   durable intents or call position-owner RPCs.
3. Apply `db/entry_reservation_least_privilege_trial.sql`, then
   `db/entry_reservations_restricted_grants_trial.sql`, then
   `db/entry_reservations_staging_grants.sql`. These scripts revoke
   `service_role` table access and reservation RPC execution and intentionally
   grant no replacement writer. Applying them can stop existing callers; do
   not proceed until their inventory and migration plan are approved.
4. Create three distinct LOGIN roles. Use identifiers reserved for this
   staging environment; do not use `postgres`, `service_role`,
   `bot_reconciler`, or shared app roles. Example shape (run once per bot with
   a unique role name):

   ```sql
   create role staging_executor_aggressive
     login inherit nosuperuser nocreatedb nocreaterole noreplication;
   grant bot_entry_executor_trial to staging_executor_aggressive;
   ```

   Repeat for `staging_executor_intraday` and `staging_executor_daily`. Give
   each role a separate, independently generated password through the
   approved secret-management workflow. With `psql`, create the role without
   a password literal, then use its interactive `\password role_name` prompt;
   never put a password in SQL text, shell history, a migration, a log, CI
   output, or this repository. Ensure the LOGINs have no other role memberships
   or elevated attributes. The shared `bot_entry_executor_trial` role supplies
   only the three executor RPC capabilities; `session_user` mapping keeps the
   bot identities separate.
5. As the restricted migration owner, insert the exact bot-to-LOGIN mapping.
   The names below are examples; substitute only the three approved staging
   LOGIN identifiers:

   ```sql
   insert into public.bot_entry_executor_identities (bot, db_login) values
     ('aggressive', 'staging_executor_aggressive'),
     ('intraday',   'staging_executor_intraday'),
     ('daily',      'staging_executor_daily');
   ```

   Do not grant the mapping table to `public`, `anon`, `authenticated`,
   `service_role`, or any executor LOGIN. The mapping is not a credential
   store. Keep write access limited to the approved database owner/migration
   process.
6. Run
   `db/entry_reservation_identity_preflight_staging.sql` using the approved
   read-only/preflight operator. It must pass without exceptions. It expects
   the existing `bot_entry_executor_trial` and `bot_reconciler` role names,
   exactly three mapped bot identities, restricted LOGINs, no unsafe role
   inheritance or schema creation, no forbidden `service_role` rights, safe
   SECURITY DEFINER ownership/search paths, and only the documented RPC
   permissions. Do not edit the preflight to make a failing target pass.
7. Connect independently as each executor LOGIN and record only the verified
   database identity and privilege results:

   ```sql
   select session_user, current_user;
   select has_function_privilege(
     current_user,
     'public.try_reserve_bot_entry(text,text,uuid,integer)', 'EXECUTE');
   select has_function_privilege(
     current_user,
     'public.claim_bot_entry_intent(text,text,uuid)', 'EXECUTE');
   select has_function_privilege(
     current_user,
     'public.release_bot_entry(text,text,uuid)', 'EXECUTE');
   select has_function_privilege(
     current_user,
     'public.resolve_bot_entry_intent(text,text,uuid)', 'EXECUTE');
   ```

   Expected: `session_user` and `current_user` are the bot's own distinct
   LOGIN; the first three RPC checks are true and the resolve check is false.
   Executor table writes, mapping-table access, and position-owner RPC
   execution must be false. Do not use a superuser for these checks.
8. Run the disposable PostgreSQL integration and SQL permission suites in
   section 7 before considering a real staging change. Capture test output and
   preflight evidence in the approved audit store.

## 3. Secrets and gateway configuration

- Generate three independent random JWT signing keys of at least 256 bits.
  Bind each key to exactly one `executor:<bot>` subject and the
  `executor:entry` scope. Use a staging-only issuer and audience. Never accept
  a key, database DSN, role name, RPC name, issuer, or audience from an HTTP
  request.
- Store each JWT key and each database LOGIN password as a distinct secret
  manager item with narrowly scoped service identity access, audit trails,
  encrypted backups, and no human-readable environment dumps.
- The gateway must use a separate TLS-verified PostgreSQL connection factory
  per bot and the matching dedicated LOGIN. Use certificate verification
  (`sslmode=verify-full` or the provider's equivalent). No superuser, owner,
  `service_role`, pooled shared credential, or browser/client secret may reach
  the process.
- Use [`templates/pr38-staging-gateway-config.example.yaml`](templates/pr38-staging-gateway-config.example.yaml)
  only as a review checklist. It contains placeholders, is not loaded by the
  Python gateway, and is not deployment-ready. A separately reviewed hosting
  adapter must resolve secret references server-side and pass the values to
  `create_staging_executor_entry_app`.
- Request fields stay limited to `bot`, `coin`, and `action`. The client must
  not choose a connection, LOGIN, signing key, RPC, or issuer. A database
  permission error, identity mismatch, timeout, malformed request, or
  authentication failure must not result in a successful claim or any
  fallback credential.

## 4. Network and service controls

The application module starts no listener. Any future host integration must be
reviewed separately and must:

- Keep the service on private networking with no public IP, public DNS, or
  public ingress. Permit only explicitly authorized staging callers through a
  private ingress or service mesh.
- Require TLS from caller to ingress and TLS with certificate validation from
  service to PostgreSQL. Use mutual TLS/service identity at the private ingress
  where supported; network location alone is not caller authentication.
- Mount only the single staging route and method, with request size/time limits,
  rate limits, and no permissive CORS. Do not enable a debug server or bind to
  `0.0.0.0`.
- Keep this route disconnected from exchange-order code. Do not route a
  reservation result into a live executor; all three live-entry blocks and
  independent close/protective-exit paths remain unchanged.

## 5. Startup checks and audit

The gateway currently has no deployment adapter or startup permission-check
hook. Before any service could be mounted, that integration must fail closed
unless all of these checks succeed:

1. Resolve all three per-bot secret references; reject missing, duplicate, or
   weak keys and duplicate LOGINs. Never log resolved values.
2. Open each bot's own database connection and verify that both
   `session_user` and `current_user` equal its configured LOGIN.
3. Run the reviewed identity/grant preflight and confirm the exact allowlisted
   RPC capabilities, no table mutation, no intent resolution, and no
   unauthorized public routine execution. If startup cannot prove the required
   permissions, do not mount the route.
4. Perform a bounded synthetic staging-only reservation/claim/release check
   only on a designated test coin and clean it up with the same identity.
   Never perform this check against an exchange or production DB. Do not treat
   a failed or ambiguous cleanup as safe to proceed.

The app itself does not emit a complete security audit trail. The future host
must provide an access-controlled, append-only audit sink and alerting. Record
request ID, timestamp, verified bot identity, action, outcome/status, database
principal, and failure category. Do not record bearer tokens, JWTs, signing
keys, passwords, DSNs, SQL parameter values, or request authorization headers.
Sanitize client-controlled values and restrict audit retention/read access.
Alert on repeated authentication failures, database permission/identity
failures, startup-preflight failures, and unexpected route access. Avoid
logging coin values unless the approved staging policy explicitly requires it.

## 6. Key/password rotation and rollback

**JWT signing keys:** the current verifier accepts one key per bot and has no
key-ID or overlapping-key rotation protocol. Do not assume zero-downtime
rotation. For a staging rotation, schedule a controlled request pause, install
the new bot-specific key in the secret manager, update the trusted issuer, issue
new short-lived tokens, restart/reload the service, test the new key and reject
the old key, then resume only after approval. Keep the old value out of logs
and remove/revoke it from the issuer and secret manager after the bounded
rollback window. If overlap is required, first implement and independently
review an explicit `kid`/key-set protocol; do not temporarily accept both
through an unreviewed adapter.

**Database passwords:** rotate one dedicated LOGIN at a time through the
secret manager and an approved secure admin path. Pause requests for that bot,
change the PostgreSQL password without exposing it in SQL/logs, update that
bot's secret reference, restart its connection pool, and verify identity and
privileges. Do not copy one bot's password to another. If validation fails,
keep the route paused and rotate to a newly controlled credential; never widen
grants as a recovery shortcut.

**Rollback:** first unmount/disable the HTTP route and stop the staging app.
This is the default fail-closed rollback and does not change exchange exits.
Preserve reservation/intent rows and audit records for reconciliation; never
delete unresolved intents or restore a stale database snapshot merely to
reopen entry. Do not blindly reapply older grants or restore `service_role`
rights. Any database rollback requires a separate reviewed migration, current
backup, caller impact analysis, and independent approval. Keep live-entry
blocks in place throughout.

## 7. Disposable validation and acceptance evidence

Use only a loopback-bound disposable PostgreSQL instance, synthetic random
passwords, and synthetic JWT keys. The existing PostgreSQL integration fixture
creates three unique LOGINs and passwords, grants the restricted RPC capability,
inserts the three mappings, and drops the roles/mappings after the tests.
Provision the schema and grant roles in the same order as section 2, then run
sequentially:

```sh
export PGHOST=127.0.0.1 PGPORT=<ephemeral-loopback-port>
export PGDATABASE=safety_test PGUSER=postgres
export PGPASSWORD=<disposable-only-password> ISOLATED_POSTGRES_CI=1
python -m unittest discover -s tests -p 'test_executor_gateway_postgres_integration.py' -v
python -m unittest discover -s tests -p 'test_executor_dedicated_login_postgres.py' -v
python -m unittest discover -s tests -p 'test_entry_reservation_identity_preflight_postgres.py' -v
python -m unittest discover -s tests -p 'test_entry_reservation_postgres.py' -v
```

The tests must demonstrate all three distinct LOGINs can claim their own
reservation/intent, direct reserve/claim/release calls under each LOGIN cannot
impersonate either other bot, forbidden role grants and database permissions
are rejected, and HTTP permission/database failures do not produce a claim.
Also run the offline HTTP/JWT and gateway contract tests, plus all entry-fence
and close/protective-exit tests. Never run these commands with production
environment variables or a non-disposable endpoint. Stop and remove the
disposable container after validation.

Evidence from this procedure proves only behavior in disposable PostgreSQL.
Before real staging, separately verify the actual target catalog, repeat the
tests using approved staging-only identities, review service-host controls,
exercise audit/alerting and rollback, and obtain independent security and
database-owner approval.

## Remaining before real staging deployment

- Implement and independently review a host adapter, startup permission gate,
  private ingress/TLS policy, audit sink, monitoring, and key/password lifecycle.
- Approve and provision three real staging-only LOGIN credentials and identity
  mappings; run the preflight and per-LOGIN tests on the intended staging DB.
- Inventory and migrate all existing callers before applying revocations that
  can disable them; prove effective grants, role memberships, function owners,
  and default privileges from the actual staging catalog.
- Obtain independent security/database approval, a rehearsed fail-closed
  rollback, and explicit staging deployment authorization.
- Keep live-entry blocks and close/protective-exit paths untouched. Any live
  integration, trading enablement, production change, merge, or deployment is
  outside this runbook and requires separate explicit authorization.
