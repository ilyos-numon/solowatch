-- 일일 요약 upsert: 같은 날 두 번째 전송은 update 가 되므로 가정 기기(device)에게 update 를 허용한다.
create policy daily_reports_update_device on public.daily_reports
  for update to authenticated
  using (public.is_member(household_id, 'device'))
  with check (public.is_member(household_id, 'device'));

-- 이 스택의 public 기본 권한은 anon/authenticated/service_role 에 DML·함수 실행을 주지 않는다.
-- RLS 정책이 실제로 적용되도록 필요한 권한만 명시적으로 준다 (delete 는 주지 않음, anon 은 없음).
grant select on public.households, public.household_members, public.alerts,
  public.alert_feedback, public.away_periods, public.daily_reports to authenticated;
grant insert on public.alerts, public.daily_reports, public.alert_feedback, public.away_periods to authenticated;
grant update on public.daily_reports, public.away_periods to authenticated;
grant execute on function public.is_member(uuid, text) to authenticated;

-- service_role: 데몬 관리 작업·E2E 시드용 (RLS 우회, 앱 번들에는 없음)
grant select, insert, update, delete on public.households, public.household_members, public.alerts,
  public.alert_feedback, public.away_periods, public.daily_reports to service_role;
grant execute on function public.is_member(uuid, text) to service_role;

-- 외출 기간 update: 만든 사람이어도 다른 가구로 옮길 수 없게 with check 에 가족 멤버 조건을 더한다.
drop policy away_periods_update_creator on public.away_periods;
create policy away_periods_update_creator on public.away_periods
  for update to authenticated
  using (created_by = auth.uid())
  with check (created_by = auth.uid() and public.is_member(household_id, 'family'));
