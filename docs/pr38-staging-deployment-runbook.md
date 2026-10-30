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

The staging reconciliation receiver is a separate WSGI callable in
[`trusted_reconciler_receiver_staging.py`](../trusted_reconciler_receiver_staging.py);
it also starts no listener. It accepts only
`POST /staging/reconciliation` with `bot`, `operation`, `coin`, and
`intent_token`, plus a bot-specific bearer JWT. Its server configuration binds
each bot to a distinct reconciler LOGIN, restricted PostgreSQL RPC transport,
read-only exchange client, and public account address. The existing dispatcher
verifies JWT signature, issuer, audience, time bounds, scope, and bot subject
before database or exchange access. The caller cannot supply a database
credential, RPC name, exchange client/address, or evidence boolean. This is
code-level receiving logic, **not** a deployed listener, identity provider, or
staging service.

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
4. Create three distinct executor LOGIN roles. Use identifiers reserved for this
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
   For reconciliation, insert the three distinct reconciler LOGINs into
   `bot_reconciler_identities` using the same bot keys. Never map an executor
   LOGIN or shared account as a reconciler identity.

   ```sql
   insert into public.bot_reconciler_identities (bot, db_login) values
     ('aggressive', 'staging_reconciler_aggressive'),
     ('intraday',   'staging_reconciler_intraday'),
     ('daily',      'staging_reconciler_daily');
   ```

   This protected mapping is enforced by reconciliation SQL against
   `session_user`; `bot_reconciler` LOGINs must not be able to read or change it.
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

For reconciliation, provision a separate unique LOGIN per bot as well, each
with only membership in `bot_reconciler`; do not reuse executor LOGINs,
`service_role`, the NOLOGIN capability role itself, or a database owner. Supply
these three principals only through server-side connection factories, and map
each one to exactly one bot in `bot_reconciler_identities`. Position-owner SQL
routines enforce that mapping against PostgreSQL `session_user`, including the
intent-read routine; a JWT or caller parameter cannot substitute for it. The
receiver checks `session_user` and `current_user`, the mapped bot, reconciler
role membership, effective allowed RPC grants, lack of direct protected-table
read/write privileges, and lack of executor RPC grants before it returns a
WSGI callable. Reads use bot-scoped SECURITY DEFINER routines, not table
SELECT grants. Run the receiver's disposable PostgreSQL integration test as
part of this verification.

The reconciliation request body is exactly:

```json
{"bot":"intraday","operation":"reconcile_entry","coin":"SOL","intent_token":"<canonical-uuid>"}
```

The bearer token is supplied only in the Authorization header. `operation`
accepts only `reconcile_entry` or `reconcile_release`; neither an RPC name nor
exchange-evidence assertions are accepted. The server chooses all RPCs,
exchange clients, account addresses, keys, and per-bot database principals.

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
  Python gateway, and is not deployment-ready. The callable-only
  `staging_executor_gateway_host.py` adapter resolves injected secret
  references and performs startup checks. Its HTTPS client requires an exact
  allowlisted origin mapped to approved private IP addresses, verifies TLS
  certificates and hostnames, and creates no listener.
- Request fields stay limited to `bot`, `coin`, and `action`. The client must
  not choose a connection, LOGIN, signing key, RPC, or issuer. A database
  permission error, identity mismatch, timeout, malformed request, or
  authentication failure must not result in a successful claim or any
  fallback credential.

## 4. Network and service controls

The host starts no listener. A configured HTTPS client makes requests only to
its exact allowlisted staging origin and pinned private addresses. Review the
deployment separately and require:

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

`create_staging_executor_gateway_host` and
`create_staging_reconciliation_receiver` fail before returning a WSGI callable
unless their respective startup checks pass. The reconciler receiver:

- Requires exactly three distinct bot-specific signing keys, account addresses,
  read-only exchange clients, LOGINs, and connection factories.
- Connects independently as each configured reconciler LOGIN and verifies the
  authenticated PostgreSQL identity, exact bot mapping, safe role
  attributes/membership, the documented reconciliation RPC allowlist, and
  absence of direct DML or executor entry RPC permissions.
- Builds each RPC transport itself from the server-supplied connection factory
  and expected LOGIN. Request JSON has an exact field allowlist, rejects
  duplicate fields and oversized bodies, and cannot choose RPCs, principals,
  evidence booleans, exchange clients, or account addresses.
- Returns no success for uncertain, stale, conflicting, or unavailable
  evidence. Database/exchange failures return a generic non-success response;
  callers must retry reconciliation rather than infer an order outcome.

The executor host additionally:

1. Resolves all three unique signing-key and DB-password references; rejects
   missing/empty values, weak or duplicate signing keys, duplicate passwords,
   duplicate secret references, and duplicate/privileged LOGIN names. Secret
   values are not included in error messages or audit records.
2. Builds a separate DB connection factory for each bot with
   `sslmode=verify-full`, a 3-second connection timeout, a 3-second statement
   timeout, and a 1-second lock timeout. At startup it verifies PostgreSQL TLS
   is active and checks `session_user` and `current_user` equal the configured
   dedicated LOGIN.
3. Checks effective schema/table/column/RPC privileges, LOGIN attributes,
   membership in only the restricted executor capability role, and absence of
   superuser, database/schema creation, mapping-table access, direct mutation,
   intent resolution, close/owner RPCs, and unlisted public routine execution.
4. Calls reserve/claim for that LOGIN's configured bot and verifies an
   attempted other-bot call fails with PostgreSQL `42501`. Both probes execute
   inside savepoints and roll back before startup completes; they leave no
   startup reservation or intent behind. Failure aborts host creation.

The host wrapper emits a fixed allowlist of audit fields: timestamp, generated
request ID, validated bot/action labels, status, and outcome. It never logs
coins, request bodies, authorization headers, tokens, SQL, database endpoints,
passwords, or signing keys. A missing or failing audit sink prevents a normal
response from being returned. The hosting deployment must still provide an
access-controlled append-only sink, retention policy, alerting, and protected
operations; audit-sink availability and operational behavior must be tested
before mounting the route.

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
python -m unittest discover -s tests -p 'test_trusted_reconciler_postgres_e2e_staging.py' -v
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

- Independently review the HTTPS transport configuration and approve the
  endpoint-to-private-IP allowlist and staging CA trust. Hosting ingress,
  monitoring, and secret-manager integration remain outstanding. The adapter
  is callable-only and intentionally does not create a listener.
- Verify the actual secret manager, audit sink, TLS CA/hostname validation,
  request timeout enforcement, and operational alerts in a controlled staging
  host; tests here use injected fake services.
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
