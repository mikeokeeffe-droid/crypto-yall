-- READ-ONLY PREFLIGHT. Run manually against the intended staging database
-- using a migration/admin connection; never use as a migration or grant script.
-- Stops on any unexpected effective privileges. Does not provision identities.
do $$
declare
  v_count integer;
  v_table text;
  v_privilege text;
  v_signature text;
  v_role_name text;
  v_expected boolean;
  v_effective boolean;
  v_column_effective boolean;
begin
  if not exists (select 1 from pg_roles where rolname = 'bot_entry_executor_trial')
     or not exists (select 1 from pg_roles where rolname = 'bot_reconciler') then
    raise exception 'missing separate executor or reconciler database role';
  end if;
  if (select count(*) from public.bot_entry_executor_identities) <> 3
     or exists (
       select expected.bot
       from unnest(array['aggressive', 'intraday', 'daily']) as expected(bot)
       where not exists (
         select 1 from public.bot_entry_executor_identities i
         where i.bot = expected.bot
       )
     ) then
    raise exception 'executor LOGIN-to-bot identity map must contain all three bots';
  end if;
  if (select count(*) from public.bot_reconciler_identities) <> 3
     or exists (
       select expected.bot
       from unnest(array['aggressive', 'intraday', 'daily']) as expected(bot)
       where not exists (
         select 1 from public.bot_reconciler_identities i
         where i.bot = expected.bot
       )
     ) then
    raise exception 'reconciler LOGIN-to-bot identity map must contain all three bots';
  end if;
  if exists (
    select 1
    from public.bot_entry_executor_identities i
    left join pg_roles r on r.rolname = i.db_login
    where r.oid is null or not r.rolcanlogin or r.rolsuper
      or not pg_has_role(r.oid, 'bot_entry_executor_trial'::regrole, 'MEMBER')
  ) then
    raise exception 'mapped executor identity must be a restricted LOGIN member';
  end if;
  if exists (
    select 1
    from public.bot_reconciler_identities i
    left join pg_roles r on r.rolname = i.db_login
    where r.oid is null or not r.rolcanlogin or r.rolsuper
      or not pg_has_role(r.oid, 'bot_reconciler'::regrole, 'MEMBER')
      or exists (
        select 1 from public.bot_entry_executor_identities e
        where e.db_login = i.db_login
      )
  ) then
    raise exception 'mapped reconciler identity must be a distinct restricted LOGIN';
  end if;
  if exists (
    select 1
    from pg_roles privileged_role
    where privileged_role.rolname in ('service_role', 'postgres', 'supabase_admin')
      and (
        pg_has_role('bot_entry_executor_trial', privileged_role.oid, 'MEMBER')
        or pg_has_role('bot_reconciler', privileged_role.oid, 'MEMBER')
      )
  ) then
    raise exception 'restricted role inherits a privileged database role';
  end if;
  if exists (
    select 1
    from pg_roles r
    where r.oid <> 'bot_entry_executor_trial'::regrole
      and pg_has_role('bot_entry_executor_trial', r.oid, 'MEMBER')
  ) then
    raise exception 'executor inherits an unapproved database role';
  end if;
  if has_schema_privilege('service_role', 'public', 'CREATE')
     or has_schema_privilege('bot_entry_executor_trial', 'public', 'CREATE')
     or has_schema_privilege('bot_reconciler', 'public', 'CREATE') then
    raise exception 'untrusted role can create objects in the SECURITY DEFINER search path';
  end if;
  if has_table_privilege('service_role', 'public.bot_entry_reservations', 'SELECT')
     or has_table_privilege('service_role', 'public.bot_entry_reservations', 'INSERT')
     or has_table_privilege('service_role', 'public.bot_entry_reservations', 'UPDATE')
     or has_table_privilege('service_role', 'public.bot_entry_reservations', 'DELETE')
     or has_table_privilege('service_role', 'public.bot_entry_reservations', 'TRUNCATE')
     or has_table_privilege('service_role', 'public.bot_entry_reservations', 'REFERENCES')
     or has_table_privilege('service_role', 'public.bot_entry_reservations', 'TRIGGER')
     or has_table_privilege('service_role', 'public.bot_entry_intents', 'SELECT')
     or has_table_privilege('service_role', 'public.bot_entry_intents', 'INSERT')
     or has_table_privilege('service_role', 'public.bot_entry_intents', 'UPDATE')
     or has_table_privilege('service_role', 'public.bot_entry_intents', 'DELETE')
     or has_table_privilege('service_role', 'public.bot_entry_intents', 'TRUNCATE')
     or has_table_privilege('service_role', 'public.bot_entry_intents', 'REFERENCES')
     or has_table_privilege('service_role', 'public.bot_entry_intents', 'TRIGGER')
     or has_table_privilege('service_role', 'public.bot_entry_executor_identities', 'SELECT')
     or has_table_privilege('service_role', 'public.bot_entry_executor_identities', 'INSERT')
     or has_table_privilege('service_role', 'public.bot_entry_executor_identities', 'UPDATE')
     or has_table_privilege('service_role', 'public.bot_entry_executor_identities', 'DELETE')
     or has_table_privilege('service_role', 'public.bot_reconciler_identities', 'SELECT')
     or has_table_privilege('service_role', 'public.bot_reconciler_identities', 'INSERT')
     or has_table_privilege('service_role', 'public.bot_reconciler_identities', 'UPDATE')
     or has_table_privilege('service_role', 'public.bot_reconciler_identities', 'DELETE')
     or has_table_privilege('service_role', 'public.bot_position_owners', 'SELECT')
     or has_table_privilege('service_role', 'public.bot_position_owners', 'INSERT')
     or has_table_privilege('service_role', 'public.bot_position_owners', 'UPDATE')
     or has_table_privilege('service_role', 'public.bot_position_owners', 'DELETE')
     or has_table_privilege('service_role', 'public.bot_position_owners', 'TRUNCATE')
     or has_table_privilege('service_role', 'public.bot_position_owners', 'REFERENCES')
     or has_table_privilege('service_role', 'public.bot_position_owners', 'TRIGGER')
     or has_function_privilege('service_role',
       'public.try_reserve_bot_entry(text,text,uuid,integer)', 'EXECUTE')
     or has_function_privilege('service_role',
       'public.claim_bot_entry_intent(text,text,uuid)', 'EXECUTE')
     or has_function_privilege('service_role',
       'public.release_bot_entry(text,text,uuid)', 'EXECUTE')
     or has_function_privilege('service_role',
       'public.record_bot_entry_order(text,text,uuid,text,bigint,numeric,text)', 'EXECUTE')
     or has_function_privilege('service_role',
       'public.resolve_bot_entry_intent(text,text,uuid)', 'EXECUTE')
     or has_function_privilege('service_role',
       'public.record_bot_position_owner(text,text,uuid,text,boolean)', 'EXECUTE')
     or has_function_privilege('service_role',
       'public.mark_bot_position_closed(text,text,uuid,boolean,boolean)', 'EXECUTE')
     or has_function_privilege('service_role',
       'public.release_closed_bot_position(text,text,uuid,boolean,boolean)', 'EXECUTE')
     or has_function_privilege('service_role',
       'public.release_resolved_bot_entry_intent(text,text,uuid,text,text,boolean,boolean,boolean)', 'EXECUTE')
     or has_function_privilege('service_role',
       'public.get_bot_entry_reconciliation_intent(text,text,uuid)', 'EXECUTE')
     or has_function_privilege('service_role',
       'public.is_bot_reconciler_identity(text)', 'EXECUTE')
  then
    raise exception 'service_role has forbidden effective mutation privilege';
  end if;
  for v_table, v_privilege in
    select t.table_name, p.privilege_name
    from (values
      ('public.bot_entry_reservations'),
      ('public.bot_entry_intents'),
      ('public.bot_entry_executor_identities'),
      ('public.bot_position_owners'),
      ('public.bot_reconciler_identities')
    ) as t(table_name)
    cross join (values
      ('SELECT'), ('INSERT'), ('UPDATE'), ('DELETE'),
      ('TRUNCATE'), ('REFERENCES'), ('TRIGGER')
    ) as p(privilege_name)
  loop
    v_expected := v_privilege = 'SELECT'
      and v_table in (
        'public.bot_entry_reservations',
        'public.bot_entry_intents'
      );
    v_effective := has_table_privilege(
      'bot_entry_executor_trial', v_table, v_privilege
    );
    if v_privilege in ('SELECT', 'INSERT', 'UPDATE', 'REFERENCES') then
      v_column_effective := has_any_column_privilege(
        'bot_entry_executor_trial', v_table, v_privilege
      );
      v_effective := v_effective or v_column_effective;
    end if;
    if v_effective is distinct from v_expected then
      raise exception 'executor has unexpected effective table privilege: %.%',
        v_table, v_privilege;
    end if;
  end loop;

  for v_signature, v_expected in
    select f.signature, f.allowed
    from (values
      ('public.try_reserve_bot_entry(text,text,uuid,integer)', true),
      ('public.claim_bot_entry_intent(text,text,uuid)', true),
      ('public.release_bot_entry(text,text,uuid)', true),
      ('public.record_bot_entry_order(text,text,uuid,text,bigint,numeric,text)', true),
      ('public.resolve_bot_entry_intent(text,text,uuid)', false),
      ('public.record_bot_position_owner(text,text,uuid,text,boolean)', false),
      ('public.mark_bot_position_closed(text,text,uuid,boolean,boolean)', false),
      ('public.release_closed_bot_position(text,text,uuid,boolean,boolean)', false),
      ('public.get_bot_entry_reconciliation_intent(text,text,uuid)', false),
      ('public.is_bot_reconciler_identity(text)', false)
    ) as f(signature, allowed)
  loop
    v_effective := has_function_privilege(
      'bot_entry_executor_trial', v_signature, 'EXECUTE'
    );
    if v_effective is distinct from v_expected then
      raise exception 'executor has unexpected effective RPC privilege: %',
        v_signature;
    end if;
  end loop;
  if exists (
    select 1
    from pg_proc p
    join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public'
      and has_function_privilege('bot_entry_executor_trial', p.oid, 'EXECUTE')
      and p.oid not in (
        to_regprocedure('public.try_reserve_bot_entry(text,text,uuid,integer)'),
        to_regprocedure('public.claim_bot_entry_intent(text,text,uuid)'),
        to_regprocedure('public.release_bot_entry(text,text,uuid)'),
        to_regprocedure('public.record_bot_entry_order(text,text,uuid,text,bigint,numeric,text)')
      )
  ) then
    raise exception 'executor has EXECUTE on an unapproved public routine';
  end if;

  for v_role_name in
    with recursive executor_members(role_oid) as (
      select m.member
      from pg_auth_members m
      where m.roleid = 'bot_entry_executor_trial'::regrole
      union
      select m.member
      from pg_auth_members m
      join executor_members e on e.role_oid = m.roleid
    )
    select r.rolname
    from executor_members e
    join pg_roles r on r.oid = e.role_oid
    where r.rolcanlogin
  loop
    if exists (
      select 1
      from pg_roles r
      where r.rolname = v_role_name and r.rolsuper
    ) then
      raise exception 'executor login % is a superuser', v_role_name;
    end if;
    if exists (
      select 1
      from pg_roles r
      where r.rolname not in (v_role_name, 'bot_entry_executor_trial')
        and pg_has_role(v_role_name, r.oid, 'MEMBER')
    ) then
      raise exception 'executor login % inherits an unapproved database role',
        v_role_name;
    end if;
    if not exists (
      select 1 from public.bot_entry_executor_identities i
      where i.db_login = v_role_name::name
    ) then
      raise exception 'executor login % has no bot identity mapping', v_role_name;
    end if;
    if has_schema_privilege(v_role_name, 'public', 'CREATE') then
      raise exception 'executor login % can create objects in public', v_role_name;
    end if;

    for v_table, v_privilege in
      select t.table_name, p.privilege_name
      from (values
        ('public.bot_entry_reservations'),
        ('public.bot_entry_intents'),
        ('public.bot_position_owners'),
        ('public.bot_reconciler_identities')
      ) as t(table_name)
      cross join (values
        ('SELECT'), ('INSERT'), ('UPDATE'), ('DELETE'),
        ('TRUNCATE'), ('REFERENCES'), ('TRIGGER')
      ) as p(privilege_name)
    loop
      v_expected := v_privilege = 'SELECT'
        and v_table in (
          'public.bot_entry_reservations',
          'public.bot_entry_intents'
        );
      v_effective := has_table_privilege(v_role_name, v_table, v_privilege);
      if v_privilege in ('SELECT', 'INSERT', 'UPDATE', 'REFERENCES') then
        v_column_effective := has_any_column_privilege(
          v_role_name, v_table, v_privilege
        );
        v_effective := v_effective or v_column_effective;
      end if;
      if v_effective is distinct from v_expected then
        raise exception 'executor login % has unexpected table privilege: %.%',
          v_role_name, v_table, v_privilege;
      end if;
    end loop;

    for v_signature, v_expected in
      select f.signature, f.allowed
      from (values
        ('public.try_reserve_bot_entry(text,text,uuid,integer)', true),
        ('public.claim_bot_entry_intent(text,text,uuid)', true),
        ('public.release_bot_entry(text,text,uuid)', true),
        ('public.record_bot_entry_order(text,text,uuid,text,bigint,numeric,text)', true),
        ('public.resolve_bot_entry_intent(text,text,uuid)', false),
        ('public.record_bot_position_owner(text,text,uuid,text,boolean)', false),
        ('public.mark_bot_position_closed(text,text,uuid,boolean,boolean)', false),
        ('public.release_closed_bot_position(text,text,uuid,boolean,boolean)', false),
        ('public.get_bot_entry_reconciliation_intent(text,text,uuid)', false),
        ('public.is_bot_reconciler_identity(text)', false)
      ) as f(signature, allowed)
    loop
      v_effective := has_function_privilege(v_role_name, v_signature, 'EXECUTE');
      if v_effective is distinct from v_expected then
        raise exception 'executor login % has unexpected RPC privilege: %',
          v_role_name, v_signature;
      end if;
    end loop;

    if exists (
      select 1
      from pg_proc p
      join pg_namespace n on n.oid = p.pronamespace
      where n.nspname = 'public'
        and has_function_privilege(v_role_name, p.oid, 'EXECUTE')
        and p.oid not in (
          to_regprocedure('public.try_reserve_bot_entry(text,text,uuid,integer)'),
          to_regprocedure('public.claim_bot_entry_intent(text,text,uuid)'),
          to_regprocedure('public.release_bot_entry(text,text,uuid)'),
          to_regprocedure('public.record_bot_entry_order(text,text,uuid,text,bigint,numeric,text)')
        )
    ) then
      raise exception 'executor login % has EXECUTE on an unapproved public routine',
        v_role_name;
    end if;
  end loop;

  for v_role_name in
    select db_login::text from public.bot_reconciler_identities
  loop
    if exists (
      select 1 from pg_roles r
      where r.rolname = v_role_name
        and (r.rolsuper or not r.rolcanlogin or not r.rolinherit
          or r.rolcreatedb or r.rolcreaterole or r.rolreplication
          or r.rolbypassrls)
    ) or not pg_has_role(v_role_name, 'bot_reconciler'::regrole, 'MEMBER') then
      raise exception 'reconciler LOGIN % has unsafe role attributes', v_role_name;
    end if;
    if exists (
      select 1 from pg_roles r
      where r.rolname not in (v_role_name, 'bot_reconciler')
        and pg_has_role(v_role_name, r.oid, 'MEMBER')
    ) then
      raise exception 'reconciler LOGIN % inherits an unapproved role',
        v_role_name;
    end if;
    if has_schema_privilege(v_role_name, 'public', 'CREATE') then
      raise exception 'reconciler LOGIN % can create objects in public',
        v_role_name;
    end if;
    if has_function_privilege(v_role_name,
         'public.try_reserve_bot_entry(text,text,uuid,integer)', 'EXECUTE')
       or has_function_privilege(v_role_name,
         'public.claim_bot_entry_intent(text,text,uuid)', 'EXECUTE')
       or has_function_privilege(v_role_name,
         'public.release_bot_entry(text,text,uuid)', 'EXECUTE')
       or has_function_privilege(v_role_name,
         'public.record_bot_entry_order(text,text,uuid,text,bigint,numeric,text)', 'EXECUTE')
       or has_function_privilege(v_role_name,
         'public.resolve_bot_entry_intent(text,text,uuid)', 'EXECUTE')
       or not has_function_privilege(v_role_name,
         'public.get_bot_entry_reconciliation_intent(text,text,uuid)', 'EXECUTE')
       or not has_function_privilege(v_role_name,
         'public.record_bot_position_owner(text,text,uuid,text,boolean)', 'EXECUTE')
       or not has_function_privilege(v_role_name,
         'public.mark_bot_position_closed(text,text,uuid,boolean,boolean)', 'EXECUTE')
       or not has_function_privilege(v_role_name,
         'public.release_closed_bot_position(text,text,uuid,boolean,boolean)', 'EXECUTE')
       or not has_function_privilege(v_role_name,
         'public.release_resolved_bot_entry_intent(text,text,uuid,text,text,boolean,boolean,boolean)', 'EXECUTE')
       or not has_function_privilege(v_role_name,
         'public.is_bot_reconciler_identity(text)', 'EXECUTE')
    then
      raise exception 'reconciler LOGIN % has unexpected effective RPC grants',
        v_role_name;
    end if;
    for v_table, v_privilege in
      select t.table_name, p.privilege_name
      from (values
        ('public.bot_entry_intents'),
        ('public.bot_entry_reservations'),
        ('public.bot_position_owners'),
        ('public.bot_reconciler_identities')
      ) as t(table_name)
      cross join (values
        ('SELECT'), ('INSERT'), ('UPDATE'), ('DELETE'),
        ('TRUNCATE'), ('REFERENCES'), ('TRIGGER')
      ) as p(privilege_name)
    loop
      v_effective := has_table_privilege(v_role_name, v_table, v_privilege);
      if v_privilege in ('SELECT', 'INSERT', 'UPDATE', 'REFERENCES') then
        v_column_effective := has_any_column_privilege(
          v_role_name, v_table, v_privilege
        );
        v_effective := v_effective or v_column_effective;
      end if;
      if v_effective then
        raise exception 'reconciler LOGIN % has direct table privilege: %.%',
          v_role_name, v_table, v_privilege;
      end if;
    end loop;
  end loop;

  if not has_function_privilege('bot_reconciler',
       'public.record_bot_position_owner(text,text,uuid,text,boolean)', 'EXECUTE')
     or has_function_privilege('bot_reconciler',
       'public.try_reserve_bot_entry(text,text,uuid,integer)', 'EXECUTE')
     or has_function_privilege('bot_reconciler',
       'public.claim_bot_entry_intent(text,text,uuid)', 'EXECUTE')
     or has_function_privilege('bot_reconciler',
       'public.record_bot_entry_order(text,text,uuid,text,bigint,numeric,text)', 'EXECUTE')
     or has_function_privilege('bot_reconciler',
       'public.resolve_bot_entry_intent(text,text,uuid)', 'EXECUTE')
     or not has_function_privilege('bot_reconciler',
       'public.release_resolved_bot_entry_intent(text,text,uuid,text,text,boolean,boolean,boolean)', 'EXECUTE')
     or not has_function_privilege('bot_reconciler',
       'public.get_bot_entry_reconciliation_intent(text,text,uuid)', 'EXECUTE')
     or not has_function_privilege('bot_reconciler',
       'public.is_bot_reconciler_identity(text)', 'EXECUTE')
  then
    raise exception 'reconciler role is not restricted to position RPCs';
  end if;
  for v_table, v_privilege in
    select t.table_name, p.privilege_name
    from (values
      ('public.bot_entry_intents'),
      ('public.bot_entry_reservations'),
      ('public.bot_position_owners'),
      ('public.bot_reconciler_identities')
    ) as t(table_name)
    cross join (values
      ('SELECT'), ('INSERT'), ('UPDATE'), ('DELETE'),
      ('TRUNCATE'), ('REFERENCES'), ('TRIGGER')
    ) as p(privilege_name)
  loop
    v_effective := has_table_privilege('bot_reconciler', v_table, v_privilege);
    if v_privilege in ('SELECT', 'INSERT', 'UPDATE', 'REFERENCES') then
      v_column_effective := has_any_column_privilege(
        'bot_reconciler', v_table, v_privilege
      );
      v_effective := v_effective or v_column_effective;
    end if;
    if v_effective then
      raise exception 'reconciler role has direct table privilege: %.%',
        v_table, v_privilege;
    end if;
  end loop;
  select count(*) into v_count
  from pg_proc p
  where p.oid in (
    to_regprocedure('public.record_bot_position_owner(text,text,uuid,text,boolean)'),
    to_regprocedure('public.mark_bot_position_closed(text,text,uuid,boolean,boolean)'),
    to_regprocedure('public.release_closed_bot_position(text,text,uuid,boolean,boolean)'),
    to_regprocedure('public.release_resolved_bot_entry_intent(text,text,uuid,text,text,boolean,boolean,boolean)'),
    to_regprocedure('public.get_bot_entry_reconciliation_intent(text,text,uuid)'),
    to_regprocedure('public.is_bot_reconciler_identity(text)')
  )
    and p.prosecdef
    and p.proconfig @> array['search_path=pg_catalog, public']::text[]
    and pg_get_userbyid(p.proowner) not in (
      'anon', 'authenticated', 'service_role',
      'bot_entry_executor_trial', 'bot_reconciler'
    );
  if v_count <> 6 then
    raise exception 'SECURITY DEFINER routines have unsafe owner or search_path';
  end if;
  select count(*) into v_count
  from pg_proc p
  where p.oid in (
    to_regprocedure('public.try_reserve_bot_entry(text,text,uuid,integer)'),
    to_regprocedure('public.claim_bot_entry_intent(text,text,uuid)'),
    to_regprocedure('public.release_bot_entry(text,text,uuid)'),
    to_regprocedure('public.record_bot_entry_order(text,text,uuid,text,bigint,numeric,text)')
  )
    and p.prosecdef
    and p.proconfig @> array['search_path=pg_catalog, public']::text[]
    and pg_get_userbyid(p.proowner) not in (
      'anon', 'authenticated', 'service_role',
      'bot_entry_executor_trial', 'bot_reconciler'
    );
  if v_count <> 4 then
    raise exception 'executor entry RPCs must be safe SECURITY DEFINER routines';
  end if;
end $$;
