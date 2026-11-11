-- family-backend 접근 규칙 (RLS·트리거·Realtime) 검증
begin;
create extension if not exists pgtap with schema extensions;
select plan(16);

-- 준비: 관리자 권한으로 데모 가구 알림·일일 요약 1건씩
insert into public.alerts (id, household_id, kind, window_start, window_end, sentence)
values ('33333333-3333-4333-8333-000000000001', '11111111-1111-4111-8111-111111111111',
        'anomaly', '2026-11-01 06:00+09', '2026-11-01 10:00+09', '아침 물 사용 없음');
insert into public.daily_reports (household_id, day, sentence)
values ('11111111-1111-4111-8111-111111111111', '2026-11-01', '오늘 리듬 정상');

-- 가족 (demo, family)
set local role authenticated;
set local request.jwt.claims = '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-000000000001","role":"authenticated"}';

select is(
  (select count(*)::int from public.alerts where id = '33333333-3333-4333-8333-000000000001'),
  1, 'family selects own household alert');

select throws_ok(
  $$insert into public.alerts (household_id, kind, window_start, window_end, sentence)
    values ('11111111-1111-4111-8111-111111111111', 'anomaly', now(), now(), 'x')$$,
  '42501', null, 'family cannot insert alerts');

select lives_ok(
  $$insert into public.alert_feedback (alert_id, household_id, user_id, verdict)
    values ('33333333-3333-4333-8333-000000000001', '11111111-1111-4111-8111-111111111111',
            'aaaaaaaa-aaaa-4aaa-8aaa-000000000001', 'ok')$$,
  'family inserts feedback');

select is(
  (select status from public.alerts where id = '33333333-3333-4333-8333-000000000001'),
  'ok', 'feedback trigger sets alert status to ok');

select lives_ok(
  $$insert into public.away_periods (household_id, start_date, end_date, created_by)
    values ('11111111-1111-4111-8111-111111111111', '2026-11-03', '2026-11-05',
            'aaaaaaaa-aaaa-4aaa-8aaa-000000000001')$$,
  'family inserts away period');

select lives_ok(
  $$update public.away_periods set end_date = '2026-11-06'
    where created_by = 'aaaaaaaa-aaaa-4aaa-8aaa-000000000001'$$,
  'creator updates own away period in same household');

select throws_ok(
  $$update public.away_periods set household_id = '22222222-2222-4222-8222-222222222222'
    where created_by = 'aaaaaaaa-aaaa-4aaa-8aaa-000000000001'$$,
  '42501', null, 'creator cannot move away period to another household');

update public.daily_reports set sentence = 'family 수정'
  where household_id = '11111111-1111-4111-8111-111111111111' and day = '2026-11-01';

select is(
  (select sentence from public.daily_reports
    where household_id = '11111111-1111-4111-8111-111111111111' and day = '2026-11-01'),
  '오늘 리듬 정상', 'family update on daily_reports is rejected (0 rows changed)');

-- 다른 가구 가족
set local request.jwt.claims = '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-000000000003","role":"authenticated"}';

select is((select count(*)::int from public.alerts), 0, 'other household selects 0 alerts');

-- 가정 기기 (demo, device)
set local request.jwt.claims = '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-000000000002","role":"authenticated"}';

select lives_ok(
  $$insert into public.alerts (household_id, kind, window_start, window_end, sentence)
    values ('11111111-1111-4111-8111-111111111111', 'anomaly', now(), now(), '저녁 TV 사용 없음')$$,
  'device inserts alerts');

select throws_ok(
  $$insert into public.alert_feedback (alert_id, household_id, user_id, verdict)
    values ('33333333-3333-4333-8333-000000000001', '11111111-1111-4111-8111-111111111111',
            'aaaaaaaa-aaaa-4aaa-8aaa-000000000002', 'ok')$$,
  '42501', null, 'device cannot insert alert_feedback');

select lives_ok(
  $$insert into public.daily_reports (household_id, day, sentence)
    values ('11111111-1111-4111-8111-111111111111', '2026-11-01', '오늘 알림 1건 · 앱에서 확인해 주세요')
    on conflict (household_id, day) do update set sentence = excluded.sentence$$,
  'device upserts daily_reports for same day (update allowed)');

reset role;

select is(
  (select sentence from public.daily_reports
    where household_id = '11111111-1111-4111-8111-111111111111' and day = '2026-11-01'),
  '오늘 알림 1건 · 앱에서 확인해 주세요',
  'device update on daily_reports applied');

select ok(
  (select count(*) = 2 from pg_publication_tables
    where pubname = 'supabase_realtime' and schemaname = 'public'
      and tablename in ('alerts', 'daily_reports')),
  'realtime publication includes alerts and daily_reports');

select is(
  (select count(*)::int from pg_policies where schemaname = 'public' and cmd in ('DELETE', 'ALL')
     and tablename <> 'push_subscriptions'),
  0, 'no delete policies on public tables');

select ok(
  (select count(*) = 1 and bool_and(qual like '%auth.uid()%') from pg_policies
    where schemaname = 'public' and tablename = 'push_subscriptions' and cmd in ('DELETE', 'ALL')),
  'push_subscriptions has exactly one own-only delete policy');

select * from finish();
rollback;
