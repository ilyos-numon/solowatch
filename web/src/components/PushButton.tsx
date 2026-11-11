import { useEffect, useState } from 'react';
import { Button } from './ui/Button';
import { Note } from './ui/Message';
import { isPushSupported, subscribePush } from '../lib/push';

const VAPID_PUBLIC_KEY = (import.meta.env.VITE_VAPID_PUBLIC_KEY as string | undefined) ?? '';
const FAIL_TEXT = '이 브라우저에서는 푸시를 켤 수 없습니다';

export default function PushButton({ householdId }: { householdId: string }) {
  const [on, setOn] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!isPushSupported()) return;
    let cancelled = false;
    navigator.serviceWorker
      .getRegistration()
      .then((reg) => reg?.pushManager.getSubscription())
      .then((sub) => {
        if (!cancelled && sub) setOn(true);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  if (!VAPID_PUBLIC_KEY) return null;

  async function onClick() {
    setBusy(true);
    setMessage(null);
    const result = await subscribePush(householdId);
    setBusy(false);
    if (result === 'subscribed') {
      setOn(true);
    } else {
      setMessage(FAIL_TEXT);
    }
  }

  return (
    <div className="push-row">
      <Button variant={on ? 'default' : 'primary'} busy={busy} disabled={on} onClick={onClick} testId="btn-push">
        {on ? '알림 받는 중' : '알림 받기'}
      </Button>
      {!on && <Note testId="push-hint">iPhone은 홈 화면에 추가한 앱에서만 알림이 옵니다.</Note>}
      {message && <Note testId="push-status">{message}</Note>}
    </div>
  );
}
