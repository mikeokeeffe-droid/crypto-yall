-- READ ONLY: run in Supabase SQL editor before any production cutover.
-- This audits grants and RLS configuration; it does not change database state.
with objects as (
  select c.oid, c.relname, c.relrowsecurity, c.relforcerowsecurity
  from pg_class c join pg_namespace n on n.oid=c.relnamespace
  where n.nspname='public' and c.relname in ('bot_state','bot_state_backups')
)
select relname, relrowsecurity as rls_enabled, relforcerowsecurity as rls_forced,
       has_table_privilege('anon',oid,'SELECT') as anon_select,
       has_table_privilege('anon',oid,'INSERT') as anon_insert,
       has_table_privilege('anon',oid,'UPDATE') as anon_update,
       has_table_privilege('authenticated',oid,'SELECT') as authenticated_select,
       has_table_privilege('authenticated',oid,'INSERT') as authenticated_insert,
       has_table_privilege('authenticated',oid,'UPDATE') as authenticated_update
from objects order by relname;

select p.proname, p.prosecdef as security_definer,
       has_function_privilege('anon',p.oid,'EXECUTE') as anon_execute,
       has_function_privilege('authenticated',p.oid,'EXECUTE') as authenticated_execute,
       has_function_privilege('service_role',p.oid,'EXECUTE') as service_role_execute
from pg_proc p join pg_namespace n on n.oid=p.pronamespace
where n.nspname='public' and p.proname='cas_bot_state';

-- EXPECTED: both tables RLS enabled; anon/authenticated table privileges false;
-- RPC SECURITY DEFINER false; anon/authenticated EXECUTE false; service_role true.
-- Also review public.bot_state and public.bot_state_backups RLS policies separately.
-- IMPORTANT: service_role can bypass RLS and may retain direct table-write access.
-- This audit cannot prove that only the CAS RPC writes state. Review every writer
-- and restrict credentials. Do not enable SUPABASE_STATE_ENABLED here.
