-- 로컬 데모 시드 (supabase db reset 때 실행). 알림 행은 넣지 않는다.
-- 사용자 3명: 가족 / 가정 기기 / 다른 가구 가족. 비밀번호 solowatch-demo-1234, 이메일 확인 완료.

insert into auth.users (
  instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
  raw_app_meta_data, raw_user_meta_data, created_at, updated_at,
  confirmation_token, recovery_token, email_change_token_new, email_change,
  email_change_token_current, phone_change, phone_change_token, reauthentication_token
)
select
  '00000000-0000-0000-0000-000000000000'::uuid, u.id, 'authenticated', 'authenticated', u.email,
  extensions.crypt('solowatch-demo-1234', extensions.gen_salt('bf')), now(),
  '{"provider":"email","providers":["email"]}'::jsonb, '{}'::jsonb, now(), now(),
  '', '', '', '', '', '', '', ''
from (values
  ('aaaaaaaa-aaaa-4aaa-8aaa-000000000001'::uuid, 'family@example.com'),
  ('aaaaaaaa-aaaa-4aaa-8aaa-000000000002'::uuid, 'device@example.com'),
  ('aaaaaaaa-aaaa-4aaa-8aaa-000000000003'::uuid, 'other@example.com')
) as u(id, email);

insert into auth.identities (
  id, user_id, provider_id, provider, identity_data, last_sign_in_at, created_at, updated_at
)
select
  gen_random_uuid(), u.id, u.id::text, 'email',
  jsonb_build_object('sub', u.id::text, 'email', u.email, 'email_verified', true, 'phone_verified', false),
  now(), now(), now()
from auth.users u
where u.id in (
  'aaaaaaaa-aaaa-4aaa-8aaa-000000000001',
  'aaaaaaaa-aaaa-4aaa-8aaa-000000000002',
  'aaaaaaaa-aaaa-4aaa-8aaa-000000000003'
);

insert into public.households (id, slug, name) values
  ('11111111-1111-4111-8111-111111111111', 'home-demo', '어머니 댁'),
  ('22222222-2222-4222-8222-222222222222', 'home-other', '다른 댁');

insert into public.household_members (household_id, user_id, role) values
  ('11111111-1111-4111-8111-111111111111', 'aaaaaaaa-aaaa-4aaa-8aaa-000000000001', 'family'),
  ('11111111-1111-4111-8111-111111111111', 'aaaaaaaa-aaaa-4aaa-8aaa-000000000002', 'device'),
  ('22222222-2222-4222-8222-222222222222', 'aaaaaaaa-aaaa-4aaa-8aaa-000000000003', 'family');

-- 웹 푸시 트리거(alerts_push_webhook)가 읽는 Vault 값 (로컬 전용). bearer 는 로컬 Supabase CLI 기본 anon key(공개값). 호스팅 값은 deploy/cloudrun.md 대로 따로 넣는다.
select vault.create_secret('http://host.docker.internal:57321/functions/v1/push-alert', 'push_alert_url');
select vault.create_secret('eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6ImFub24iLCJleHAiOjE5ODM4MTI5OTZ9.CRXP1A7WOeoJeXxjNni43kdQwgnWNReilDMblYTn_I0', 'push_alert_bearer');
select vault.create_secret('local-push-secret', 'push_alert_secret');
