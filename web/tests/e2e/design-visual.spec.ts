import { test, expect, type Page, type Route } from '@playwright/test';
import path from 'node:path';

// 디자인 비교용 16장: 뷰 4 × 테마 2 × 뷰포트 2. 데모 API 는 고정 JSON 으로 대신한다.
const SHOT_DIR = process.env.ILLY_SHOT_DIR ?? 'tests/e2e/screenshots';
const DEMO_HID = '11111111-1111-4111-8111-111111111111';
const SENTENCE = '이상 가능성 있음 · 아침 (6~12시) 물 사용 없음 · 평소와 다릅니다';
const SENSORS = ['water_main', 'plug_fridge', 'plug_tv', 'plug_light'];
const WINDOWS = ['night', 'morning', 'afternoon', 'evening'];

function recent(): Record<string, [string, number][]> {
  const out: Record<string, [string, number][]> = {};
  for (const sid of SENSORS) {
    out[sid] = Array.from({ length: 288 }, (_, i) => {
      const h = Math.floor(i / 12);
      const m = (i % 12) * 5;
      const ts = `2026-11-02T${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:00+09:00`;
      let v = 0;
      if (sid === 'water_main') v = h >= 7 && h <= 9 ? 2.5 : h >= 18 && h <= 20 ? 1.5 : 0;
      if (sid === 'plug_fridge') v = i % 6 < 3 ? 120 : 5;
      if (sid === 'plug_tv') v = h >= 19 && h <= 22 ? 90 : 0;
      if (sid === 'plug_light') v = h >= 18 && h <= 23 ? 12 : 0;
      return [ts, v];
    });
  }
  return out;
}

function scores(score: number) {
  return SENSORS.flatMap((sid) =>
    WINDOWS.map((window) => {
      const focus = sid === 'water_main' && window === 'morning';
      return {
        sensor_id: sid,
        window,
        day_type: 'weekday',
        score: focus ? score : 0.12,
        expected: focus ? 30.1 : 10,
        actual: focus ? 0 : 10.2,
        flagged: focus,
      };
    }),
  );
}

const STATE = {
  ready: true,
  virtual_now: '2026-11-02T00:00:00+09:00',
  day_index: 0,
  household_id: DEMO_HID,
  readings_total: 32256,
  recent: recent(),
  outbox: [
    {
      at: '2026-11-03T10:00:05+09:00',
      direction: 'in',
      table: 'alert_feedback',
      summary: '괜찮았음 · 아침 (6~12시) 창 평소 30.1 → 27.4 L',
      row: { verdict: 'ok' },
    },
    { at: '2026-11-03T10:00:01+09:00', direction: 'out', table: 'alerts', summary: SENTENCE, row: { kind: 'anomaly' } },
    {
      at: '2026-11-03T10:00:00+09:00',
      direction: 'out',
      table: 'daily_reports',
      summary: '일일 요약 2026-11-01 · 평소와 비슷한 하루였습니다',
      row: { day: '2026-11-01' },
    },
  ],
  last_inject: null,
  history: [],
  error: null,
};

const json = (route: Route, status: number, body: unknown) =>
  route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

async function mockApi(page: Page) {
  await page.route('**/api/demo/**', async (route) => {
    const p = new URL(route.request().url()).pathname;
    if (p.endsWith('/state')) return json(route, 200, STATE);
    if (p.endsWith('/inject'))
      return json(route, 200, {
        kind: 'no_morning_water',
        day: '2026-11-03',
        day_type: 'weekday',
        readings: 1152,
        alerts: [{ remote_id: 'r-2', sentence: SENTENCE, window_start: '2026-11-03T06:00:00+09:00' }],
        scores: scores(0.91),
        previous_scores: scores(0.97),
        daily_sent: true,
        auto_reset: false,
      });
    if (p.endsWith('/reset')) return json(route, 200, STATE);
    return route.fulfill({ status: 404 });
  });
}

const VIEWS = [
  { name: 'login', url: '/login', ready: 'login-email' },
  { name: 'home', url: '/?demo=1', ready: 'household-name' },
  { name: 'demo-live', url: '/demo', ready: 'demo-page' },
  { name: 'demo-family', url: '/demo#family', ready: 'family-home' },
] as const;
const THEMES = ['light', 'dark'] as const;
const SIZES = [
  { width: 390, height: 844 },
  { width: 1440, height: 900 },
];

for (const view of VIEWS) {
  for (const theme of THEMES) {
    for (const size of SIZES) {
      test(`${view.name} ${theme} ${size.width}`, async ({ browser }) => {
        // 새 context: 로그아웃 상태에서 시작 (login 뷰) + 라이트 기본 테마
        const context = await browser.newContext({
          viewport: size,
          baseURL: (test.info().project.use.baseURL as string) ?? undefined,
          timezoneId: 'Asia/Seoul',
          locale: 'ko-KR',
          colorScheme: 'light',
        });
        const page = await context.newPage();
        try {
          await mockApi(page);
          await page.goto(view.url);
          await expect(page.getByTestId(view.ready)).toBeVisible({ timeout: 30_000 });
          if (theme === 'dark') {
            await page.getByTestId('theme-toggle').click();
            await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
          }
          if (view.name === 'demo-live') {
            await expect(page.getByTestId('inside-chart-water_main').locator('svg path')).toHaveCount(1);
          }
          const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
          expect(scrollWidth).toBeLessThanOrEqual(size.width);
          await page.screenshot({
            path: path.join(SHOT_DIR, `visual-${view.name}-${theme}-${size.width}.png`),
            fullPage: true,
          });
        } finally {
          await context.close();
        }
      });
    }
  }
}
