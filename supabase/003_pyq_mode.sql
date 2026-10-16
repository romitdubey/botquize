-- Existing questions, notes and learner progress are preserved.
alter table public.study_quizzes drop constraint if exists study_quizzes_kind_check;
alter table public.study_quizzes add constraint study_quizzes_kind_check check (kind in ('daily','weekly','pyq'));
