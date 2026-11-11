import { useCallback, useEffect, useState } from 'react';
import { supabase } from '../lib/supabase';
import {
  getMyHousehold,
  insertFeedback,
  latestDailyReport,
  listAlerts,
  subscribeAlerts,
  type Alert,
  type DailyReport,
  type Household,
  type Verdict,
} from '../lib/queries';
import { localToday } from '../lib/format';
import { Button } from './ui/Button';
import TodayCard from './TodayCard';
import AlertList from './AlertList';
import RhythmChart from './RhythmChart';
import AwayForm from './AwayForm';
import PushButton from './PushButton';
import SleepBanner from './SleepBanner';

export default function FamilyHome() {
  const [household, setHousehold] = useState<Household | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [report, setReport] = useState<DailyReport | null>(null);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async (hid: string) => {
    const [a, r] = await Promise.all([listAlerts(hid), latestDailyReport(hid)]);
    setAlerts(a);
    setReport(r);
  }, []);

  useEffect(() => {
    let unsub: (() => void) | undefined;
    let cancelled = false;
    (async () => {
      const h = await getMyHousehold();
      if (cancelled) return;
      setHousehold(h);
      if (h) {
        await load(h.id);
        if (cancelled) return;
        unsub = subscribeAlerts(h.id, (row) => {
          setAlerts((prev) => {
            const i = prev.findIndex((x) => x.id === row.id);
            if (i >= 0) {
              const next = prev.slice();
              next[i] = row;
              return next;
            }
            return [row, ...prev].slice(0, 20);
          });
        });
      }
      setLoaded(true);
    })().catch(() => {
      if (!cancelled) setLoaded(true);
    });
    return () => {
      cancelled = true;
      unsub?.();
    };
  }, [load]);

  // 실패는 AlertList 가 카드 안 문구(alert-msg)로 보여준다
  async function onFeedback(alert: Alert, verdict: Verdict) {
    await insertFeedback(alert.id, alert.household_id, verdict);
  }

  return (
    <div className="phone" data-testid="family-home">
      <div className="phone-top">
        <div>
          <p className="hs-eyebrow">지켜보는 집</p>
          <h2 className="phone-name" data-testid="household-name">
            {household?.name ?? ''}
          </h2>
        </div>
        <Button variant="ghost" onClick={() => void supabase.auth.signOut()}>
          로그아웃
        </Button>
      </div>
      <SleepBanner />
      {loaded && household && <PushButton householdId={household.id} />}
      {loaded && <TodayCard report={report} alerts={alerts} today={localToday()} />}
      <div className="sec-head">
        <h3>알림</h3>
        <span className="hs-note">최근 20건</span>
      </div>
      {loaded && <AlertList alerts={alerts} onFeedback={onFeedback} />}
      {loaded && household && <RhythmChart householdId={household.id} />}
      {loaded && household && <AwayForm householdId={household.id} />}
    </div>
  );
}
