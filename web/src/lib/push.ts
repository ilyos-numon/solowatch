import { supabase } from './supabase';

const VAPID_PUBLIC_KEY = (import.meta.env.VITE_VAPID_PUBLIC_KEY as string | undefined) ?? '';
const READY_TIMEOUT_MS = 10_000;

export type PushResult = 'subscribed' | 'denied' | 'unsupported' | 'failed';

export function isPushSupported(): boolean {
  return (
    typeof window !== 'undefined' &&
    'serviceWorker' in navigator &&
    'PushManager' in window &&
    'Notification' in window &&
    VAPID_PUBLIC_KEY.length > 0
  );
}

function urlBase64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  const padding = '='.repeat((4 - (base64.length % 4)) % 4);
  const raw = atob((base64 + padding).replace(/-/g, '+').replace(/_/g, '/'));
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

function swReady(): Promise<ServiceWorkerRegistration | null> {
  return Promise.race([
    navigator.serviceWorker.ready,
    new Promise<null>((resolve) => setTimeout(() => resolve(null), READY_TIMEOUT_MS)),
  ]);
}

export async function subscribePush(householdId: string): Promise<PushResult> {
  if (!isPushSupported()) return 'unsupported';
  try {
    if (Notification.permission === 'denied') return 'denied';
    if (Notification.permission !== 'granted') {
      const perm = await Notification.requestPermission();
      if (perm !== 'granted') return 'denied';
    }
    const reg = await swReady();
    if (!reg) return 'failed';
    const sub =
      (await reg.pushManager.getSubscription()) ??
      (await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC_KEY),
      }));
    const json = sub.toJSON();
    const p256dh = json.keys?.p256dh;
    const auth = json.keys?.auth;
    if (!json.endpoint || !p256dh || !auth) return 'failed';

    const { data: session } = await supabase.auth.getSession();
    const uid = session.session?.user.id;
    if (!uid) return 'failed';
    const { error } = await supabase
      .from('push_subscriptions')
      .insert({ household_id: householdId, user_id: uid, endpoint: json.endpoint, p256dh, auth });
    // 같은 endpoint 가 이미 저장돼 있으면(unique 위반) 구독된 것으로 본다
    if (error && error.code !== '23505') return 'failed';
    return 'subscribed';
  } catch {
    return 'failed';
  }
}

export async function unsubscribePush(): Promise<void> {
  if (!('serviceWorker' in navigator)) return;
  const reg = await swReady();
  const sub = await reg?.pushManager.getSubscription();
  if (!sub) return;
  await supabase.from('push_subscriptions').delete().eq('endpoint', sub.endpoint);
  await sub.unsubscribe();
}
