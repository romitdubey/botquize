-- Run once in Supabase SQL Editor before using Telegram /notes. Safe to rerun.
create table if not exists public.study_notes (
 id uuid primary key,
 study_date date not null,
 title text not null,
 filename text not null,
 mime text not null check(mime in ('application/pdf','image/jpeg','image/png','image/webp')),
 path text not null,
 created_at timestamptz not null default now()
);
create index if not exists study_notes_date_idx on public.study_notes(study_date);
alter table public.study_notes enable row level security;
revoke all on public.study_notes from anon, authenticated;
grant all on public.study_notes to service_role;
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values ('study-notes','study-notes',false,10485760,array['application/pdf','image/jpeg','image/png','image/webp'])
on conflict(id) do update set public=false,file_size_limit=10485760,
allowed_mime_types=array['application/pdf','image/jpeg','image/png','image/webp'];

-- Atomic diagram updates prevent simultaneous Telegram image uploads from
-- overwriting one another's attachments in the same JSON question bank.
create or replace function public.study_attach_image(p_quiz_id uuid,p_index integer,p_path text)
returns boolean
language plpgsql
set search_path=public
as $$
begin
 if p_index < 0 then return false; end if;
 update public.study_quizzes
 set questions=jsonb_set(
   jsonb_set(questions,array[p_index::text,'image_path'],to_jsonb(p_path),true),
   array[p_index::text,'image_url'],'""'::jsonb,true)
 where id=p_quiz_id and p_index<jsonb_array_length(questions);
 return found;
end;
$$;
revoke all on function public.study_attach_image(uuid,integer,text) from public,anon,authenticated;
grant execute on function public.study_attach_image(uuid,integer,text) to service_role;
