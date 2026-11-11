export type DemoEventKind = 'normal' | 'no_morning_water' | 'fridge_off' | 'light_all_night' | 'night_flow';

export const DEMO_EVENTS: { kind: DemoEventKind; label: string }[] = [
  { kind: 'no_morning_water', label: '아침 물 없음' },
  { kind: 'fridge_off', label: '냉장고 전원 끊김' },
  { kind: 'light_all_night', label: '밤새 거실등' },
  { kind: 'night_flow', label: '밤중 물 흐름' },
  { kind: 'normal', label: '평범한 하루' },
];

export type ScoreEntry = {
  sensor_id: string;
  window: string;
  day_type: string;
  score: number;
  expected: number;
  actual: number;
  flagged: boolean;
};

export type OutboxEntry = {
  at: string;
  direction: 'out' | 'in';
  table: string;
  summary: string;
  row: Record<string, unknown>;
};

export type InjectResult = {
  kind: DemoEventKind;
  day: string;
  day_type: string;
  readings: number;
  alerts: { remote_id: string; sentence: string; window_start: string }[];
  scores: ScoreEntry[];
  previous_scores: ScoreEntry[];
  daily_sent: boolean;
  auto_reset: boolean;
};

export type DemoState = {
  ready: boolean;
  virtual_now: string;
  day_index: number;
  household_id: string;
  readings_total: number;
  recent: Record<string, [string, number][]>;
  outbox: OutboxEntry[];
  last_inject: InjectResult | null;
  history: { day: string; kind: string; alerts: number }[];
  error: string | null;
};

export class DemoApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'DemoApiError';
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/demo/${path}`, init);
  if (!res.ok) {
    let code = `http_${res.status}`;
    try {
      const body = (await res.json()) as { error?: unknown };
      if (typeof body.error === 'string') code = body.error;
    } catch {
      // 본문이 JSON 이 아니면 상태 코드만 쓴다
    }
    throw new DemoApiError(res.status, code);
  }
  return (await res.json()) as T;
}

export function getState(): Promise<DemoState> {
  return request<DemoState>('state');
}

export function inject(kind: DemoEventKind): Promise<InjectResult> {
  return request<InjectResult>('inject', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind }),
  });
}

export function reset(): Promise<DemoState> {
  return request<DemoState>('reset', { method: 'POST' });
}

export const SENSOR_LABEL_KO: Record<string, string> = {
  water_main: '물',
  plug_fridge: '냉장고',
  plug_tv: 'TV',
  plug_light: '거실등',
};

export const WINDOW_LABEL_KO: Record<string, string> = {
  night: '밤 (0~6시)',
  morning: '아침 (6~12시)',
  afternoon: '오후 (12~18시)',
  evening: '저녁 (18~24시)',
};
