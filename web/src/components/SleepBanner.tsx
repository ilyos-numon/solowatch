import { useEffect, useState } from 'react';
import { Msg } from './ui/Message';

const URL_BASE = import.meta.env.VITE_SUPABASE_URL;
const ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY;
const RETRY_DELAY_MS = 1500;

// true = Supabase 가 응답하지 않음 (네트워크 TypeError 또는 5xx)
async function probeFailed(): Promise<boolean> {
  try {
    const res = await fetch(`${URL_BASE}/auth/v1/health`, { headers: { apikey: ANON_KEY } });
    return res.status >= 500;
  } catch (e) {
    return e instanceof TypeError;
  }
}

export default function SleepBanner() {
  const [asleep, setAsleep] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!(await probeFailed()) || cancelled) return;
      await new Promise((r) => setTimeout(r, RETRY_DELAY_MS));
      if (cancelled) return;
      // 2 회 연속 실패해야 잠든 것으로 본다
      if (await probeFailed()) {
        if (!cancelled) setAsleep(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (!asleep) return null;
  return (
    <Msg tone="warn" testId="sleep-banner">
      데모가 잠들어 있습니다. 잠시 뒤 다시 열어 주세요
    </Msg>
  );
}
