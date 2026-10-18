-- Optional notification outbox only; no quiz, answer or learner schema is changed.
create table if not exists public.study_email_events (
 id text primary key,
 payload jsonb not null check (jsonb_typeof(payload)='array' and jsonb_array_length(payload) between 1 and 2),
 status text not null default 'pending' check (status in ('pending','sending','sent','failed')),
 lease_token uuid,
 lease_until timestamptz,
 created_at timestamptz not null default now(),
 sent_at timestamptz,
 last_error text
);
alter table public.study_email_events enable row level security;
revoke all on public.study_email_events from anon,authenticated;
grant all on public.study_email_events to service_role;
