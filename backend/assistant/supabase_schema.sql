-- Forecast assistant storage (backend/assistant/store.py). Run once in the Supabase SQL editor
-- (Project -> SQL Editor -> New query -> paste -> Run). Safe to re-run: every statement checks first.
--
-- Access: the backend uses the service-role key (a Render secret), which bypasses row-level security. RLS is
-- switched ON with no policies, so the public anon key can read or write nothing directly.

create extension if not exists pgcrypto;

-- Field reports from farmers, extension staff and researchers (sowing, rain, emergence, stage, stress, harvest,
-- advisory feedback). Contact details are optional and only shown to reviewers.
create table if not exists field_reports (
  id               uuid primary key default gen_random_uuid(),
  created_at       timestamptz not null default now(),
  report_type      text not null,
  observed_on      date,
  lat              double precision,
  lon              double precision,
  place_name       text,
  country          text,
  season           text,
  crop             text,
  payload          jsonb not null default '{}'::jsonb,
  reporter_role    text,
  reporter_contact text,
  consent          boolean not null default false,
  verification     text not null default 'unverified',   -- unverified | verified | rejected
  reviewed_by      text,
  reviewed_at      timestamptz,
  review_note      text,
  photo_path       text,
  photo_triage     jsonb
);
create index if not exists field_reports_place on field_reports (lat, lon);
create index if not exists field_reports_created on field_reports (created_at desc);
alter table field_reports enable row level security;

-- Private bucket for report photos (served to reviewers through temporary signed links)
insert into storage.buckets (id, name, public)
values ('field-photos', 'field-photos', false)
on conflict (id) do nothing;
