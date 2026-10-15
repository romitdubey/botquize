-- Run once in the Supabase SQL editor. Re-running is safe.
create table if not exists public.study_quizzes (
 id uuid primary key,
 study_date date not null,
 topic text not null,
 description text not null default '',
 status text not null default 'draft' check (status in ('draft','open','closed')),
 kind text not null default 'daily' check (kind in ('daily','weekly')),
 owner_id uuid references auth.users(id) on delete cascade,
 duration_seconds integer not null check (duration_seconds between 60 and 21600),
 questions jsonb not null check (jsonb_typeof(questions)='array'),
 created_at timestamptz not null default now()
);
create index if not exists study_quizzes_date_idx on public.study_quizzes(study_date);
create table if not exists public.study_learners (
 user_id uuid primary key references auth.users(id) on delete cascade,
 data jsonb not null default '{}',
 version bigint not null default 0
);
create table if not exists public.study_admins (
 telegram_id bigint primary key,
 data jsonb not null default '{}',
 version bigint not null default 0
);
alter table public.study_quizzes enable row level security;
alter table public.study_learners enable row level security;
alter table public.study_admins enable row level security;
-- All application access is through the authenticated backend. There are deliberately
-- no browser SELECT policies on answer keys or study records.
revoke all on public.study_quizzes, public.study_learners, public.study_admins from anon, authenticated;
grant all on public.study_quizzes, public.study_learners, public.study_admins to service_role;
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values ('question-images','question-images',false,10485760,array['image/jpeg','image/png','image/webp'])
on conflict(id) do update set public=false,file_size_limit=10485760,
allowed_mime_types=array['image/jpeg','image/png','image/webp'];
