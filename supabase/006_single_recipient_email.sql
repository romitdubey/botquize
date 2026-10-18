-- Preserve historical two-recipient events; new sends are restricted to Vishu in code.
-- Run after 005 on existing projects. Safe to rerun; no study data is changed.
begin;
alter table public.study_email_events
 drop constraint if exists study_email_events_payload_check;
alter table public.study_email_events
 add constraint study_email_events_payload_check
 check (jsonb_typeof(payload)='array' and jsonb_array_length(payload) between 1 and 2);
commit;
