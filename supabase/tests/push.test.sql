-- 웹 푸시 구독 (push_subscriptions RLS·alerts_push_webhook 트리거) 검증
begin;
create extension if not exists pgtap with schema extensions;
select plan(10);

select is(
  (select count(*)::int from pg_trigger
    where tgname = 'alerts_push_webhook' and tgrelid = 'public.alerts'::regclass),
  1, 'alerts_push_webhook trigger exists on alerts');

-- 가족 (demo, family)
set local role authenticated;
set local request.jwt.claims = '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-000000000001","role":"authenticated"}';

select lives_ok(
  $$insert into public.push_subscriptions (id, household_id, user_id, endpoint, p256dh, auth)
    values ('44444444-4444-4444-8444-000000000001', '11111111-1111-4111-8111-111111111111',
            'aaaaaaaa-aaaa-4aaa-8aaa-000000000001', 'https://push.example.com/own', 'p', 'a')$$,
  'family inserts own subscription');

select is(
  (select count(*)::int from public.push_subscriptions
    where id = '44444444-4444-4444-8444-000000000001'),
  1, 'family selects own subscription');

select throws_ok(
  $$insert into public.push_subscriptions (household_id, user_id, endpoint, p256dh, auth)
    values ('22222222-2222-4222-8222-222222222222', 'aaaaaaaa-aaaa-4aaa-8aaa-000000000001',
            'https://push.example.com/other-house', 'p', 'a')$$,
  '42501', null, 'family cannot subscribe to another household');

select throws_ok(
  $$insert into public.push_subscriptions (household_id, user_id, endpoint, p256dh, auth)
    values ('11111111-1111-4111-8111-111111111111', 'aaaaaaaa-aaaa-4aaa-8aaa-000000000003',
            'https://push.example.com/as-other-user', 'p', 'a')$$,
  '42501', null, 'family cannot insert a subscription for another user');

-- 다른 가구 가족
set local request.jwt.claims = '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-000000000003","role":"authenticated"}';

select is((select count(*)::int from public.push_subscriptions), 0,
  'other user selects 0 subscriptions');

delete from public.push_subscriptions where id = '44444444-4444-4444-8444-000000000001';

-- 가정 기기 (demo, device)
set local request.jwt.claims = '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-000000000002","role":"authenticated"}';

select throws_ok(
  $$insert into public.push_subscriptions (household_id, user_id, endpoint, p256dh, auth)
    values ('11111111-1111-4111-8111-111111111111', 'aaaaaaaa-aaaa-4aaa-8aaa-000000000002',
            'https://push.example.com/device', 'p', 'a')$$,
  '42501', null, 'device cannot insert subscriptions');

-- 다시 가족: 다른 사람의 delete 는 0 행이었고, 본인은 지울 수 있다
set local request.jwt.claims = '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-000000000001","role":"authenticated"}';

select is(
  (select count(*)::int from public.push_subscriptions
    where id = '44444444-4444-4444-8444-000000000001'),
  1, 'other user delete removed nothing');

select lives_ok(
  $$delete from public.push_subscriptions where id = '44444444-4444-4444-8444-000000000001'$$,
  'family deletes own subscription');

reset role;

select is(
  (select count(*)::int from public.push_subscriptions
    where id = '44444444-4444-4444-8444-000000000001'),
  0, 'own subscription is gone');

select * from finish();
rollback;
