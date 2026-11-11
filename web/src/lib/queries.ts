import { supabase } from './supabase';
import type { Database } from './database.types';

type T = Database['public']['Tables'];
export type Household = T['households']['Row'];
export type Alert = T['alerts']['Row'];
export type DailyReport = T['daily_reports']['Row'];
export type AwayPeriod = T['away_periods']['Row'];
export type Verdict = 'ok' | 'checking' | 'confirmed' | 'missed';

function localDate(d = new Date()): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

async function currentUserId(): Promise<string> {
  const { data, error } = await supabase.auth.getSession();
  if (error) throw error;
  const uid = data.session?.user.id;
  if (!uid) throw new Error('no session');
  return uid;
}

export async function getMyHousehold(): Promise<Household | null> {
  const uid = await currentUserId();
  const { data: members, error: mErr } = await supabase
    .from('household_members')
    .select('household_id')
    .eq('user_id', uid)
    .limit(1);
  if (mErr) throw mErr;
  const hid = members?.[0]?.household_id;
  if (!hid) return null;
  const { data, error } = await supabase.from('households').select('*').eq('id', hid).maybeSingle();
  if (error) throw error;
  return data;
}

export async function listAlerts(hid: string, limit = 20): Promise<Alert[]> {
  const { data, error } = await supabase
    .from('alerts')
    .select('*')
    .eq('household_id', hid)
    .order('created_at', { ascending: false })
    .limit(limit);
  if (error) throw error;
  return data ?? [];
}

export async function latestDailyReport(hid: string): Promise<DailyReport | null> {
  const { data, error } = await supabase
    .from('daily_reports')
    .select('*')
    .eq('household_id', hid)
    .order('day', { ascending: false })
    .limit(1);
  if (error) throw error;
  return data?.[0] ?? null;
}

export async function listDailyReports(hid: string, days = 14): Promise<DailyReport[]> {
  const { data, error } = await supabase
    .from('daily_reports')
    .select('*')
    .eq('household_id', hid)
    .order('day', { ascending: false })
    .limit(days);
  if (error) throw error;
  return data ?? [];
}

export async function insertFeedback(alertId: string, hid: string, verdict: Verdict): Promise<void> {
  const uid = await currentUserId();
  const { error } = await supabase
    .from('alert_feedback')
    .insert({ alert_id: alertId, household_id: hid, user_id: uid, verdict });
  if (error) throw error;
}

export async function listAway(hid: string): Promise<AwayPeriod[]> {
  const { data, error } = await supabase
    .from('away_periods')
    .select('*')
    .eq('household_id', hid)
    .gte('end_date', localDate())
    .order('start_date', { ascending: true });
  if (error) throw error;
  return data ?? [];
}

export async function insertAway(hid: string, start: string, end: string, note: string): Promise<void> {
  const uid = await currentUserId();
  const { error } = await supabase
    .from('away_periods')
    .insert({ household_id: hid, start_date: start, end_date: end, note, created_by: uid });
  if (error) throw error;
}

export async function endAway(id: string, endDate: string): Promise<number> {
  const { data, error } = await supabase.from('away_periods').update({ end_date: endDate }).eq('id', id).select('id');
  if (error) throw error;
  return data?.length ?? 0;
}

export function subscribeAlerts(hid: string, cb: (alert: Alert) => void): () => void {
  const channel = supabase
    .channel(`alerts-${hid}-${Math.random().toString(36).slice(2)}`)
    .on(
      'postgres_changes',
      { event: '*', schema: 'public', table: 'alerts', filter: `household_id=eq.${hid}` },
      (payload) => {
        const row = payload.new as Alert;
        if (row && row.id) cb(row);
      },
    )
    .subscribe();
  return () => {
    void supabase.removeChannel(channel);
  };
}
