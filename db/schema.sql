-- Staging only. Do not enable live writers until migration and recovery tests pass.
create table if not exists public.bot_state (
  bot text primary key check (bot in ('aggressive', 'intraday', 'daily')),
  state jsonb not null check (jsonb_typeof(state) = 'object'),
  revision bigint not null default 1,
  updated_at timestamptz not null default now()
);
-- State is private. Access only from a trusted server with the service-role key.
alter table public.bot_state enable row level security;
revoke all on public.bot_state from anon, authenticated;
create table if not exists public.bot_state_backups (
  bot text not null,
  revision bigint not null,
  state jsonb not null,
  backed_up_at timestamptz not null default now(),
  primary key (bot, revision)
);
alter table public.bot_state_backups enable row level security;
revoke all on public.bot_state_backups from anon, authenticated;
