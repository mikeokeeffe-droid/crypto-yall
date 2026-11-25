# Staging Supabase entry-lock preflight (read-only)

**Do not apply staging SQL to production or enable live entries from this checklist.**

## Verify in a dedicated staging Supabase project

1. Apply `db/entry_reservations_staging.sql` to a disposable staging project.
2. Confirm RPC functions exist: `try_reserve_bot_entry`, `claim_bot_entry_intent`, `release_bot_entry`, `resolve_bot_entry_intent`.
3. Confirm `anon` and `authenticated` have no EXECUTE permission on these RPCs and no direct access to either reservation table.
4. Confirm the trusted server-side role has exactly the required EXECUTE/table privileges (the staging SQL currently only revokes access; **service_role grants must be explicitly verified**).
5. Confirm all three bot processes point to the **same** project and schema; never print or commit the service key.
6. Execute the isolated PostgreSQL concurrency tests in CI and the staging RPC contract checks.
7. Simulate exchange timeouts and verify unresolved intents block new entries indefinitely until independently reconciled.
8. Review manual reconciliation: the current `resolve_bot_entry_intent` RPC relies on trusted caller discipline and **does not itself verify Hyperliquid status**. Do not expose it to routine executor paths.
9. Confirm stale intent recovery and owner handoff procedures. Filled orders require a durable ownership record, not just releasing a fence.
10. Only after a separate dry-run executor integration and explicit approval, consider staged deployment.

## Read-only permission inspection SQL

Run in the staging SQL editor. These queries **do not modify data**.

```sql
select p.proname,
       has_function_privilege('anon', p.oid, 'EXECUTE') as anon_can_execute,
       has_function_privilege('authenticated', p.oid, 'EXECUTE') as authenticated_can_execute,
       has_function_privilege('service_role', p.oid, 'EXECUTE') as service_can_execute
from pg_proc p join pg_namespace n on n.oid=p.pronamespace
where n.nspname='public'
  and p.proname in ('try_reserve_bot_entry','claim_bot_entry_intent',
                    'release_bot_entry','resolve_bot_entry_intent')
order by p.proname;

select table_name, grantee, privilege_type
from information_schema.role_table_grants
where table_schema='public'
  and table_name in ('bot_entry_reservations','bot_entry_intents')
order by table_name, grantee, privilege_type;
```

## Deployment blocker

The current reservation/intent RPCs are staging proposals, not a complete live order coordinator. In particular, exchange verification, atomic owner handoff, cancellation/fill reconciliation, and safe privileged grants must be implemented and reviewed before activation.
