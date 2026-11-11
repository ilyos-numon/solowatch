-- 홀로안심 가족 백엔드: 가구·역할·알림·피드백·외출·일일 요약.
-- 인증·권한·실시간은 Supabase(Auth·RLS·Realtime)가 맡는다. 별도 서버 없음.
-- 집 밖으로 나오는 데이터는 알림 문장과 일일 요약(시간별 참/거짓)뿐이다.

create table public.households(
  id uuid primary key,
  slug text unique not null,
  name text not null,
  created_at timestamptz default now()
);

create table public.household_members(
  household_id uuid references public.households on delete cascade,
  user_id uuid references auth.users on delete cascade,
  role text not null check (role in ('family','device')),
  primary key(household_id, user_id)
);

create table public.alerts(
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references public.households,
  kind text not null check (kind in ('anomaly','daily_ok')),
  window_start timestamptz not null,
  window_end timestamptz not null,
  sentence text not null,
  details jsonb not null default '{}'::jsonb,
  status text not null default 'open' check (status in ('open','ok','checking','confirmed')),
  created_at timestamptz default now()
);

create table public.alert_feedback(
  id uuid primary key default gen_random_uuid(),
  alert_id uuid references public.alerts,
  household_id uuid not null references public.households,
  user_id uuid not null references auth.users,
  verdict text not null check (verdict in ('ok','checking','confirmed','missed')),
  day date,
  note text default '',
  created_at timestamptz default now()
);

create table public.away_periods(
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references public.households,
  start_date date not null,
  end_date date not null,
  note text default '',
  created_by uuid not null references auth.users,
  created_at timestamptz default now()
);

create table public.daily_reports(
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references public.households,
  day date not null,
  sentence text not null,
  rhythm jsonb not null default '{}'::jsonb,
  first_events jsonb not null default '{}'::jsonb,
  created_at timestamptz default now(),
  unique(household_id, day)
);

create index alerts_household_created_idx on public.alerts(household_id, created_at desc);
create index alert_feedback_household_created_idx on public.alert_feedback(household_id, created_at);
create index away_periods_household_idx on public.away_periods(household_id, start_date);

-- 멤버 여부 (RLS 재귀를 피하려고 security definer)
create function public.is_member(hid uuid, want_role text default null)
returns boolean language sql stable security definer set search_path = public as $$
  select exists(
    select 1 from public.household_members m
    where m.household_id = hid and m.user_id = auth.uid()
      and (want_role is null or m.role = want_role)
  )
$$;

-- RLS: 6개 테이블
alter table public.households enable row level security;
alter table public.household_members enable row level security;
alter table public.alerts enable row level security;
alter table public.alert_feedback enable row level security;
alter table public.away_periods enable row level security;
alter table public.daily_reports enable row level security;

-- select: 같은 가구 멤버만
create policy households_select on public.households
  for select to authenticated using (public.is_member(id));
create policy household_members_select on public.household_members
  for select to authenticated using (public.is_member(household_id));
create policy alerts_select on public.alerts
  for select to authenticated using (public.is_member(household_id));
create policy alert_feedback_select on public.alert_feedback
  for select to authenticated using (public.is_member(household_id));
create policy away_periods_select on public.away_periods
  for select to authenticated using (public.is_member(household_id));
create policy daily_reports_select on public.daily_reports
  for select to authenticated using (public.is_member(household_id));

-- insert: 알림·일일 요약은 가정 기기(device)만
create policy alerts_insert_device on public.alerts
  for insert to authenticated with check (public.is_member(household_id, 'device'));
create policy daily_reports_insert_device on public.daily_reports
  for insert to authenticated with check (public.is_member(household_id, 'device'));

-- insert: 피드백·외출은 가족(family)만, 본인 이름으로
create policy alert_feedback_insert_family on public.alert_feedback
  for insert to authenticated
  with check (public.is_member(household_id, 'family') and user_id = auth.uid());
create policy away_periods_insert_family on public.away_periods
  for insert to authenticated
  with check (public.is_member(household_id, 'family') and created_by = auth.uid());

-- update: 외출 기간은 만든 사람만
create policy away_periods_update_creator on public.away_periods
  for update to authenticated
  using (created_by = auth.uid())
  with check (created_by = auth.uid());

-- delete 정책 없음. alerts.status 는 아래 트리거만 바꾼다.
create function public.apply_feedback_status()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  if new.alert_id is not null and new.verdict in ('ok','checking','confirmed') then
    update public.alerts a
      set status = new.verdict
      where a.id = new.alert_id and a.household_id = new.household_id;
  end if;
  return new;
end
$$;

create trigger alert_feedback_apply_status
  after insert on public.alert_feedback
  for each row execute function public.apply_feedback_status();

alter publication supabase_realtime add table public.alerts, public.daily_reports;
