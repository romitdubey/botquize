-- Safe existing-project upgrade. Existing notes remain legacy content for Vishu.
alter table public.study_notes add column if not exists owner_id uuid references auth.users(id) on delete cascade;
create index if not exists study_notes_owner_date_idx on public.study_notes(owner_id,study_date);
