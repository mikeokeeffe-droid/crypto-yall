# PostgreSQL 18 offline test-server provisioning package

**DRAFT — disabled, offline, review-only. Do not execute this package.**

This package is for preparing a separately dedicated offline test server. It
does not authorize a migration, service start, remote access, signing, or
trading. The PostgreSQL 18 package has not been applied to the server. Keep the
existing `testnet-collector-offline-review.service` unchanged.

## Package contents and boundaries

- `sender_review/postgresql18_offline/provision.sql` is a guarded, transactional
  provisioning candidate. It refuses any database except `sender_review_test`,
  any server except PostgreSQL 18, TCP listening, a socket mode other than
  `0770`, a non-`postgres` administrator, or a non-fresh journal schema. It
  reuses `sender_review/ci_only_journal.sql` and
  `sender_review/ci_only_restricted_role.sql` verbatim.
- The review-only owner removes the global default `PUBLIC EXECUTE` grant on
  functions *before* creating the journal functions. A disposable PostgreSQL 18
  integration test verifies existing and newly created functions remain
  inaccessible to an unrelated role. This default ACL must be undone before
  deleting the owner role during a separately approved rollback.
- The database owner and all three bot roles are `NOLOGIN`,
  `NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE`, `NOREPLICATION`,
  `NOBYPASSRLS`, and `NOINHERIT`. The bot roles receive no database,
  schema, table, sequence, or function privileges and no role memberships.
- The reused CI restricted role is also `NOLOGIN`; its only intended grant is
  the fixture-only review wrapper. That wrapper accepts caller-asserted fixture
  identity and is **not authenticated ingress**. Do not grant membership to
  any service, Unix account, or human login. It must not be exposed as an
  endpoint.
- `socket_policy.py` is a read-only check for the socket directory's exact
  `0770` mode and the explicitly verified host group. PostgreSQL's
  `unix_socket_permissions=0770` controls the socket file; it does not set the
  containing directory's mode or owner. The package does not change either.
- `test_permissions.py` is an explicit-opt-in, read-only PostgreSQL 18 socket
  check. It requires a local superuser connection and verifies the effective
  socket settings, no-login/no-grant bot roles, denied operations, and the
  restricted fixture role. It does not run migrations or insert journal rows.
- `test_provisioning_integration.py` executes the exact guarded provisioning
  SQL in an isolated PostgreSQL 18 container with networking disabled. It
  verifies transactional rollback, role attributes/grants/memberships,
  ownership, direct-denial behavior, cross-bot isolation, and the fixture
  socket's `0770` mode/group. This is CI fixture evidence only, not evidence
  about the dedicated host.
- Existing disposable PostgreSQL 16 CI tests remain the concurrency evidence
  for three-bot shared-fence isolation and the current restricted-role
  privilege boundary. They are not evidence of this host's PostgreSQL 18
  configuration.

## Host-side evidence required before any later approval

Do not change the host as part of this review. A separately assigned reviewer
must privately verify the dedicated host identity and PG18 package/source
hashes; the effective service unit and drop-ins; the PostgreSQL process UID,
capabilities, mounts, and sockets; and absence of trading keys and write-capable
credentials. Do not paste secret-bearing environment values or unredacted logs
into GitHub.

Independently verify that `listen_addresses` is empty, the configured
`unix_socket_group` and the socket directory's actual group are the approved
dedicated local reviewer group, no unintended users belong to that group, and
the socket directory mode is exactly `0770`. The stated host configuration
only confirms the PostgreSQL socket-file mode; it does not establish directory
ownership. Do not change group ownership or PostgreSQL settings to make the
check pass. Stop if the existing group configuration cannot be verified. Run
the read-only socket check only after the actual group name and socket directory
have been independently confirmed:

```sh
python -m sender_review.postgresql18_offline.socket_policy \
  --socket-dir /var/run/postgresql --group "$VERIFIED_SOCKET_GROUP"
```

The proposed provisioning SQL makes no changes to `postgresql.conf`,
`pg_hba.conf`, systemd, firewall rules, DNS, proxies, or network policy. Do not
relax host-wide egress controls. No testnet network reader or application
service is included.

## Permission test procedures

The existing offline checks are:

```sh
python -m unittest sender_review.test_ci_journal_permissions_postgres -v
python -m unittest sender_review.test_ci_restricted_role_postgres -v
```

They require the disposable CI-only PostgreSQL configuration; do not point
them at the dedicated server. The PG18 host verification is separate and is
not enabled by default. Only after independent approval of the dedicated
offline test database and a later application of the reviewed package, invoke
it through the local Unix socket with explicit opt-in:

```sh
SENDER_REVIEW_PG18_OFFLINE=1 \
SENDER_REVIEW_PG18_SOCKET_GROUP=sender_review_offline \
PGHOST=/var/run/postgresql PGDATABASE=sender_review_test \
PGUSER=postgres env -u PGPORT \
python -m unittest sender_review.postgresql18_offline.test_permissions -v
```

The host test requires the socket directory to be a real directory (not a
symlink), owned by the named group, with exact `0770` mode. It refuses TCP
hosts, non-18 servers, a nonempty `listen_addresses`, and an unintended
database. It runs only read queries and denied statements under `SET ROLE`;
it never invokes the fixture wrapper.

## Rollback instructions for a separately approved future provisioning

No rollback is required now: the package has not been executed and has not
changed host or database state. If a later, separately approved review applies
it and chooses to undo that isolated database, use the local PostgreSQL
administrator only after confirming the database contains no needed evidence
and no service or other object depends on the review schema:

1. Keep all services stopped and keep TCP disabled. Do not delete journal
   evidence as a way to resolve an unknown outcome.
2. If any journal or fixture evidence is needed, retain the database unchanged
   and isolate it; do not use rollback to erase uncertain outcomes. Only after
   confirming that all evidence may be discarded, drop the package-owned schema
   and its populated objects with `CASCADE`:

   ```sql
   DROP SCHEMA sender_review_ci CASCADE;
   ```

3. Reverse the **owner's global default-function ACL change** before
   attempting to drop that owner role. Run as the local PostgreSQL
   administrator in the same isolated `sender_review_test` database, after
   confirming the package is the only source of owner default-ACL changes:

   ```sql
   ALTER DEFAULT PRIVILEGES FOR ROLE sender_review_pg18_owner
       GRANT EXECUTE ON FUNCTIONS TO PUBLIC;
   ```

   This restores PostgreSQL's built-in default for functions created **in
   the future**; it does not grant access to the already-deleted journal
   functions. If other default ACL modifications or role dependencies
   remain, stop and have the reviewer identify them rather than running a
   broad `DROP OWNED ... CASCADE` or deleting unrelated objects.

4. Revoke any grants that an operator added outside this package, then drop
   only the package's roles:

   ```sql
   DROP ROLE sender_review_ci_restricted;
   DROP ROLE sender_review_ci_untrusted;
   DROP ROLE sender_review_pg18_daily;
   DROP ROLE sender_review_pg18_intraday;
   DROP ROLE sender_review_pg18_aggressive;
   DROP ROLE sender_review_pg18_owner;
   ```

5. Restore the database's prior `PUBLIC` CONNECT/TEMPORARY grants only if they
   were present before the package was applied. Do not drop the database,
   alter socket/firewall policy, restart PostgreSQL, or change bot workflows
   as part of this rollback.
6. Privately verify the effective database and host configuration against the
   pre-change evidence. Any mismatch is a stop condition and requires the
   independent reviewer and operator to resolve it before further activity.

**Status: no provisioning performed; no migration executed; no service enabled;
no trading enabled. PR #42 remains draft.**
