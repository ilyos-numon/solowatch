-- 라이브 데모: 웹 푸시 구독 테이블 + alerts(anomaly) insert → pg_net → Edge Function push-alert.
-- URL·헤더 값은 Vault 에서 읽는다 (로컬은 seed.sql, 호스팅은 deploy/cloudrun.md 의 SQL).
create extension if not exists pg_net with schema extensions;
create extension if not exists supabase_vault;

create table public.push_subscriptions(
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references public.households,
  user_id uuid not null references auth.users on delete cascade,
  endpoint text not null unique,
  p256dh text not null,
  auth text not null,
  created_at timestamptz default now());
create index push_subscriptions_household_idx on public.push_subscriptions(household_id);
alter table public.push_subscriptions enable row level security;
create policy push_subscriptions_select_own on public.push_subscriptions for select to authenticated using (user_id = auth.uid());
create policy push_subscriptions_insert_family on public.push_subscriptions for insert to authenticated
  with check (user_id = auth.uid() and public.is_member(household_id, 'family'));
create policy push_subscriptions_delete_own on public.push_subscriptions for delete to authenticated using (user_id = auth.uid());
grant select, insert, delete on public.push_subscriptions to authenticated;      -- 이 테이블만 authenticated delete 허용(구독 해지)
grant select, insert, update, delete on public.push_subscriptions to service_role;

-- alerts(anomaly) insert → Edge Function. URL·헤더 값은 Vault: push_alert_url, push_alert_bearer(anon key), push_alert_secret. url 이 없으면 아무것도 하지 않는다.
create function public.push_alert_webhook() returns trigger language plpgsql security definer set search_path = public as $$
declare v_url text; v_bearer text; v_secret text;
begin
  if new.kind <> 'anomaly' then return new; end if;
  select decrypted_secret into v_url from vault.decrypted_secrets where name = 'push_alert_url' limit 1;
  if v_url is null then return new; end if;
  select decrypted_secret into v_bearer from vault.decrypted_secrets where name = 'push_alert_bearer' limit 1;
  select decrypted_secret into v_secret from vault.decrypted_secrets where name = 'push_alert_secret' limit 1;
  perform net.http_post(url := v_url,
    headers := jsonb_build_object('Content-Type','application/json','apikey', coalesce(v_bearer,''),
                                  'Authorization', 'Bearer ' || coalesce(v_bearer,''), 'x-push-secret', coalesce(v_secret,'')),
    body := jsonb_build_object('alert_id', new.id), timeout_milliseconds := 5000);
  return new;
end $$;
create trigger alerts_push_webhook after insert on public.alerts for each row execute function public.push_alert_webhook();
