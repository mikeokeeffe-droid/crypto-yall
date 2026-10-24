-- Install only after review. Independent of live revision-based rollback table.
create table if not exists public.bot_state_snapshots (
  snapshot_id uuid primary key,
  bot text not null check (bot in ('aggressive','intraday','daily')),
  source_gist_id text not null,
  source_gist_version text not null,
  source_sha256 text not null check (source_sha256 ~ '^[0-9a-f]{64}$'),
  state jsonb not null check (jsonb_typeof(state) = 'object'),
  verified boolean not null default false,
  captured_at timestamptz not null default now(),
  verified_at timestamptz,
  constraint verified_timestamp_consistent check
    ((verified = false and verified_at is null) or (verified = true and verified_at is not null))
);
create index if not exists bot_state_snapshots_lookup
  on public.bot_state_snapshots(bot, captured_at desc);
alter table public.bot_state_snapshots enable row level security;
revoke all on public.bot_state_snapshots from anon, authenticated;
