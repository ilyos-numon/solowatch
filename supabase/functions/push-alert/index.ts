// push-alert: alerts(anomaly) insert → 가구의 구독 브라우저 전부에 웹 푸시 (VAPID).
// 호출: alerts_push_webhook 트리거(pg_net) 또는 수동 POST. 헤더 x-push-secret 필수.
import webpush from "npm:web-push@3.6.7";
import { createClient } from "npm:@supabase/supabase-js@2";

const TTL = 3600;
const TITLE = "홀로안심";

type Subscription = { id: string; endpoint: string; p256dh: string; auth: string };

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function env(name: string): string {
  const v = Deno.env.get(name);
  if (!v) throw new Error(`missing env ${name}`);
  return v;
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// web-push 가 만든 요청(암호화 본문 + Authorization: vapid … + TTL)을 fetch 로 보낸다.
// web-push 의 sendNotification 은 node https 만 써서 http 엔드포인트(E2E 수신기)로 못 보낸다.
async function send(sub: Subscription, payload: string): Promise<number> {
  const details = webpush.generateRequestDetails(
    { endpoint: sub.endpoint, keys: { p256dh: sub.p256dh, auth: sub.auth } },
    payload,
    { TTL },
  );
  const headers: Record<string, string> = {};
  for (const [k, v] of Object.entries(details.headers)) {
    if (k.toLowerCase() === "content-length") continue;
    headers[k] = String(v);
  }
  const res = await fetch(details.endpoint, {
    method: details.method,
    headers,
    body: details.body ? new Uint8Array(details.body) : undefined,
  });
  await res.body?.cancel();
  return res.status;
}

Deno.serve(async (req) => {
  if (req.method !== "POST") return json(405, { error: "method_not_allowed" });
  if (req.headers.get("x-push-secret") !== env("PUSH_ALERT_SECRET")) {
    return json(401, { error: "bad_secret" });
  }

  let alertId: unknown;
  try {
    alertId = (await req.json())?.alert_id;
  } catch {
    return json(400, { error: "bad_body" });
  }
  if (typeof alertId !== "string" || !UUID_RE.test(alertId)) {
    return json(400, { error: "bad_body" });
  }

  const db = createClient(env("SUPABASE_URL"), env("SUPABASE_SERVICE_ROLE_KEY"), {
    auth: { persistSession: false },
  });
  const { data: alert, error: alertErr } = await db
    .from("alerts").select("household_id, sentence").eq("id", alertId).maybeSingle();
  if (alertErr) return json(500, { error: "db_error" });
  if (!alert) return json(404, { error: "alert_not_found" });

  const { data: subs, error: subsErr } = await db
    .from("push_subscriptions").select("id, endpoint, p256dh, auth")
    .eq("household_id", alert.household_id);
  if (subsErr) return json(500, { error: "db_error" });

  webpush.setVapidDetails(env("VAPID_SUBJECT"), env("VAPID_PUBLIC_KEY"), env("VAPID_PRIVATE_KEY"));
  const payload = JSON.stringify({ title: TITLE, body: alert.sentence, url: "/" });

  let sent = 0;
  const gone: string[] = [];
  await Promise.all((subs ?? []).map(async (sub: Subscription) => {
    try {
      const status = await send(sub, payload);
      if (status === 404 || status === 410) gone.push(sub.id);
      else if (status >= 200 && status < 300) sent += 1;
      else console.error(`push ${sub.id} failed: HTTP ${status}`);
    } catch (e) {
      console.error(`push ${sub.id} failed: ${e instanceof Error ? e.message : e}`);
    }
  }));

  if (gone.length > 0) {
    const { error } = await db.from("push_subscriptions").delete().in("id", gone);
    if (error) console.error(`cleanup failed: ${error.message}`);
  }
  return json(200, { sent, removed: gone.length });
});
