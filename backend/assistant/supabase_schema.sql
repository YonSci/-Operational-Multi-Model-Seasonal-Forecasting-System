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

-- Bulletin Studio versions (backend/assistant/bulletins.py): each row is one version with the evidence snapshot
-- it was written from and the quality check at saving time.
create table if not exists bulletins (
  id           uuid primary key default gen_random_uuid(),
  created_at   timestamptz not null default now(),
  format       text not null,
  title        text,
  season       text,
  audience     text,
  length       text,
  sections     jsonb not null,
  sms          text,
  audio_script text,
  snapshot     jsonb not null,
  snapshot_id  text,
  quality      jsonb,
  version      integer not null default 1,
  parent_id    uuid references bulletins (id),
  status       text not null default 'draft',     -- draft | reviewed | published
  author       text
);
create index if not exists bulletins_created on bulletins (created_at desc);
alter table bulletins enable row level security;

-- Watches ("Did the advice change?", backend/assistant/watches.py): anonymous; only the hash of each watch's key
-- is stored, the key itself stays in the user's browser.
create table if not exists watches (
  id              uuid primary key default gen_random_uuid(),
  created_at      timestamptz not null default now(),
  key_hash        text not null,
  name            text,
  lat             double precision not null,
  lon             double precision not null,
  place_name      text,
  season          text not null,
  model           text not null,
  crop            text,
  planted         text,
  sowing_date     date,
  decision        text,
  objective       text,
  thresholds      jsonb,
  baseline        jsonb,
  baseline_at     timestamptz,
  last_checked_at timestamptz
);
alter table watches enable row level security;
