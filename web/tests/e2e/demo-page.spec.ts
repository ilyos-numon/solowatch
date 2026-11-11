import { test, expect, type Page, type Route } from '@playwright/test';
import path from 'node:path';

// 데모 서버 없이 돈다: /api/demo/** 응답을 고정 JSON 으로 대신한다.
const SHOT_DIR = process.env.ILLY_SHOT_DIR ?? 'tests/e2e/screenshots';
const DEMO_HID = '11111111-1111-4111-8111-111111111111';
const SENTENCE = '이상 가능성 있음 · 아침 (6~12시) 물 사용 없음 · 평소와 다릅니다';
const SENSORS = ['water_main', 'plug_fridge', 'plug_tv', 'plug_light'];
const WINDOWS = ['night', 'morning', 'afternoon', 'evening'];
const KINDS = ['no_morning_water', 'fridge_off', 'light_all_night', 'night_flow', 'normal'];

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

function scores(waterMorning: { score: number; flagged: boolean; expected?: number }) {
  return SENSORS.flatMap((sid) =>
    WINDOWS.map((window) => {
      const focus = sid === 'water_main' && window === 'morning';
      return {
        sensor_id: sid,
        window,
        day_type: 'weekday',
        score: focus ? waterMorning.score : 0.12,
        expected: focus ? (waterMorning.expected ?? 30.1) : 10,
        actual: focus ? 0 : 10.2,
        flagged: focus ? waterMorning.flagged : false,
      };
    }),
  );
}

const INJECT_RETRAINED = {
  kind: 'no_morning_water',
  day: '2026-11-04',
  day_type: 'weekday',
  readings: 1152,
  alerts: [{ remote_id: 'r-3', sentence: SENTENCE, window_start: '2026-11-04T06:00:00+09:00' }],
  scores: scores({ score: 0.99679, flagged: true, expected: 24.3 }),
  previous_scores: scores({ score: 0.9999991, flagged: true, expected: 25.9 }),
  daily_sent: true,
  auto_reset: false,
};

const INJECT = {
  kind: 'no_morning_water',
  day: '2026-11-03',
  day_type: 'weekday',
  readings: 1152,
  alerts: [{ remote_id: 'r-2', sentence: SENTENCE, window_start: '2026-11-03T06:00:00+09:00' }],
  scores: scores({ score: 0.91, flagged: true }),
  previous_scores: scores({ score: 0.97, flagged: true }),
  daily_sent: true,
  auto_reset: false,
};

function state(dayIndex: number, lastInject: unknown = null) {
  return {
    ready: true,
    virtual_now: dayIndex === 0 ? '2026-11-02T00:00:00+09:00' : '2026-11-04T00:00:00+09:00',
    day_index: dayIndex,
    household_id: DEMO_HID,
    readings_total: 32256 + dayIndex * 1152,
    recent: recent(),
    outbox: [
      {
        at: '2026-11-03T10:00:05+09:00',
        direction: 'in',
        table: 'alert_feedback',
        summary: '괜찮았음 · 아침 (6~12시) 창 평소 30.1 → 27.4 L',
        row: { verdict: 'ok' },
      },
      {
        at: '2026-11-03T10:00:01+09:00',
        direction: 'out',
        table: 'alerts',
        summary: SENTENCE,
        row: { kind: 'anomaly', sentence: SENTENCE },
      },
      {
        at: '2026-11-03T10:00:00+09:00',
        direction: 'out',
        table: 'daily_reports',
        summary: '일일 요약 2026-11-01 · 평소와 비슷한 하루였습니다',
        row: { day: '2026-11-01' },
      },
    ],
    last_inject: lastInject,
    history: dayIndex === 0 ? [] : [{ day: '2026-11-03', kind: 'no_morning_water', alerts: 1 }],
    error: null,
  };
}

const json = (route: Route, status: number, body: unknown) =>
  route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

async function mockApi(
  page: Page,
  opts: { injectStatus?: number; stateStatus?: number; inject?: typeof INJECT } = {},
) {
  const injectBody = opts.inject ?? INJECT;
  let injected = false;
  await page.route('**/api/demo/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/state')) {
      if (opts.stateStatus) return json(route, opts.stateStatus, { error: 'not_ready' });
      return json(route, 200, injected ? state(2, injectBody) : state(0));
    }
    if (url.pathname.endsWith('/inject')) {
      if (opts.injectStatus === 400) return json(route, 400, { error: 'unknown_kind', kinds: KINDS });
      injected = true;
      return json(route, 200, injectBody);
    }
    if (url.pathname.endsWith('/reset')) return json(route, 200, state(0));
    return route.fulfill({ status: 404 });
  });
}

async function expectNoHorizontalScroll(page: Page, max = 1440) {
  const width = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(width).toBeLessThanOrEqual(max);
}

test.describe('live demo page with two tabs', () => {
  test('header, two tabs, live demo selected by default with all panels', async ({ page }) => {
    await mockApi(page);
    await page.goto('/demo');
    await expect(page.getByRole('heading', { level: 1, name: '홀로안심' })).toBeVisible();
    await expect(page.getByRole('tab')).toHaveCount(2);
    await expect(page.getByTestId('tab-family')).toHaveText('가족 앱');
    await expect(page.getByTestId('tab-demo')).toHaveText('라이브 데모');
    await expect(page.getByTestId('tab-demo')).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByTestId('tab-family')).toHaveAttribute('aria-selected', 'false');
    await expect(page.getByTestId('pane-family')).toBeHidden();
    await expect(page.getByTestId('pane-family')).toHaveAttribute('hidden', '');
    await expect(page.getByTestId('pane-demo')).toBeVisible();
    await expect(page.getByTestId('demo-page')).toBeVisible();
    await expect(page.getByTestId('demo-inside')).toContainText('집 안');
    await expect(page.getByTestId('demo-inside')).toContainText('집 밖으로 나가지 않음');
    await expect(page.getByTestId('demo-outbox')).toContainText('집 밖으로 나간 것');
    for (const sid of SENSORS) {
      await expect(page.getByTestId(`inside-chart-${sid}`)).toBeVisible();
      await expect(page.getByTestId(`inside-chart-${sid}`).locator('svg path')).toHaveCount(1);
    }
    await expect(page.getByTestId('inside-chart-water_main')).toContainText('물 (L, 최근 24시간 · 5분 단위)');
    for (const h of ['0시', '6시', '12시', '18시', '24시']) {
      await expect(page.getByTestId('inside-chart-water_main').locator('svg text', { hasText: new RegExp(`^${h}$`) })).toHaveCount(1);
    }
    for (const kind of KINDS) {
      await expect(page.getByTestId(`btn-inject-${kind}`)).toBeEnabled();
      await expect(page.getByTestId(`btn-inject-${kind}`)).toHaveAttribute('aria-pressed', 'false');
    }
    await expect(page.locator('[data-testid^="btn-inject-"]')).toHaveCount(5);
    await expect(page.getByTestId('btn-reset')).toBeVisible();
    await expect(page.getByTestId('btn-reset')).toHaveText('처음부터');
    await expect(page.getByTestId('demo-day-index')).toContainText('0일째');
    await expect(page.getByTestId('demo-day-index')).toContainText('/ 14일');
    await expect(page.getByTestId('demo-virtual-now')).toContainText('2026-11-02');
    await expect(page.getByTestId('outbox-item')).toHaveCount(3);
    await expect(page.locator('[data-testid="outbox-item"][data-direction="in"]')).toHaveCount(1);
    await expect(page.getByTestId('demo-outbox')).toContainText('집 → 밖');
    await expect(page.getByTestId('demo-outbox')).toContainText('밖 → 집');
    await expect(page.getByTestId('demo-score-title')).toHaveText('버튼을 누르면 가상 집이 그 하루를 삽니다');
    await expect(page.getByTestId('demo-not-ready')).toHaveCount(0);
    await expect(page.getByTestId('demo-auto-reset')).toHaveCount(0);
    await expectNoHorizontalScroll(page);
  });

  test('inject shows score before/after for the focus window and presses the button', async ({ page }) => {
    await mockApi(page);
    await page.goto('/demo');
    await page.getByTestId('btn-inject-no_morning_water').click();
    const rows = page.getByTestId('demo-score-row');
    await expect(rows).toHaveCount(1);
    await expect(rows.getByTestId('demo-score-before')).toHaveText(/^\d+(\.\d+)?%$/);
    await expect(rows.getByTestId('demo-score-after')).toHaveText(/^\d+(\.\d+)?%$/);
    await expect(rows.getByTestId('demo-score-before')).toHaveText('97.0%');
    await expect(rows.getByTestId('demo-score-after')).toHaveText('91.0%');
    await expect(rows).toContainText('30.1 → 30.1 L');
    await expect(rows).toContainText('0.0 L');
    await expect(page.getByText('괜찮았음을 받으면 그 시간대의 평소 기준을 다시 배웁니다', { exact: false })).toBeVisible();
    await expect(rows.getByTestId('demo-score-verdict')).toHaveText('알림');
    await expect(page.getByTestId('demo-score-title')).toHaveText('2026-11-03 · 아침 물 없음');
    await expect(page.getByText(SENTENCE)).toHaveCount(2); // 결과 카드 + outbox
    await expect(page.getByTestId('btn-inject-no_morning_water')).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByTestId('btn-inject-fridge_off')).toHaveAttribute('aria-pressed', 'false');
    // 이상 창(아침) 음영이 물 그래프에만 있다
    await expect(page.getByTestId('inside-chart-water_main').locator('svg rect')).toHaveCount(1);
    await expect(page.getByTestId('inside-chart-plug_fridge').locator('svg rect')).toHaveCount(0);
    await expect(page.getByTestId('demo-day-index')).toContainText('2일째');
    await expect(page.getByTestId('demo-error')).toHaveCount(0);
    await expectNoHorizontalScroll(page);
    // 하루 재생 애니메이션(3 초)이 끝난 뒤 찍는다
    await page.waitForTimeout(3500);
    await expect(page.getByTestId('inside-chart-water_main').locator('svg path')).not.toHaveAttribute('stroke-dasharray', /.+/);
    await page.screenshot({ path: path.join(SHOT_DIR, 'demo-page.png'), fullPage: true });
  });

  test('chart tooltip follows the pointer', async ({ page }) => {
    await mockApi(page);
    await page.goto('/demo');
    const chart = page.getByTestId('inside-chart-water_main');
    const svg = chart.locator('svg');
    await expect(svg).toBeVisible();
    const box = (await svg.boundingBox())!;
    // 8시 근처 (x = 8/24)
    await page.mouse.move(box.x + box.width * (8 / 24), box.y + box.height / 2);
    const tip = chart.locator('.tip');
    await expect(tip).toBeVisible();
    await expect(tip).toContainText(/^0[78]:\d\d/);
    await expect(tip).toContainText('2.50 L');
    await page.mouse.move(box.x + box.width / 2, box.y + box.height + 200);
    await expect(tip).toBeHidden();
  });

  test('near-1 scores stay distinguishable after retraining', async ({ page }) => {
    await mockApi(page, { inject: INJECT_RETRAINED });
    await page.goto('/demo');
    await page.getByTestId('btn-inject-no_morning_water').click();
    const rows = page.getByTestId('demo-score-row');
    await expect(rows).toHaveCount(1);
    const before = rows.getByTestId('demo-score-before');
    const after = rows.getByTestId('demo-score-after');
    await expect(before).toHaveText('99.9999%');
    await expect(after).toHaveText('99.68%');
    expect(await before.textContent()).not.toBe(await after.textContent());
    await expect(rows).toContainText('25.9 → 24.3 L');
    await expect(rows.getByTestId('demo-score-verdict')).toHaveText('알림');
  });

  test('normal day has no score table', async ({ page }) => {
    await mockApi(page, { inject: { ...INJECT, kind: 'normal', alerts: [] } });
    await page.goto('/demo');
    await page.getByTestId('btn-inject-normal').click();
    await expect(page.getByText('평범한 하루는 따로 살펴볼 시간대가 없습니다')).toBeVisible();
    await expect(page.getByText('이 날은 알림이 없었습니다')).toBeVisible();
    await expect(page.getByTestId('demo-score-row')).toHaveCount(0);
    await expect(page.getByTestId('btn-inject-normal')).toHaveAttribute('aria-pressed', 'true');
  });

  test('400 from inject shows demo-error', async ({ page }) => {
    await mockApi(page, { injectStatus: 400 });
    await page.goto('/demo');
    await page.getByTestId('btn-inject-fridge_off').click();
    await expect(page.getByTestId('demo-error')).toContainText('unknown_kind');
    await expect(page.getByTestId('demo-error')).toHaveText('알 수 없는 이벤트입니다 (unknown_kind)');
    await expect(page.getByTestId('demo-score-row')).toHaveCount(0);
  });

  test('503 from state shows demo-not-ready', async ({ page }) => {
    await mockApi(page, { stateStatus: 503 });
    await page.goto('/demo');
    await expect(page.getByTestId('demo-not-ready')).toHaveText('가상 집을 준비하는 중입니다');
    await expect(page.getByTestId('btn-inject-normal')).toBeDisabled();
    await expect(page.getByTestId('btn-reset')).toBeDisabled();
  });

  test('auto_reset after 14 days shows demo-auto-reset', async ({ page }) => {
    await mockApi(page, { inject: { ...INJECT, auto_reset: true } });
    await page.goto('/demo');
    await expect(page.getByTestId('demo-auto-reset')).toHaveCount(0);
    await page.getByTestId('btn-inject-no_morning_water').click();
    await expect(page.getByTestId('demo-auto-reset')).toHaveText('14일이 지나 가상 집을 처음부터 다시 시작했습니다');
  });

  test('family tab shows the inline family home signed in as the demo account', async ({ page }) => {
    await mockApi(page);
    await page.goto('/demo');
    await page.getByTestId('tab-family').click();
    await expect(page).toHaveURL(/\/demo#family$/);
    await expect(page.getByTestId('tab-family')).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByTestId('pane-family')).toBeVisible();
    await expect(page.getByTestId('pane-demo')).toBeHidden();
    await expect(page.getByTestId('family-home')).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId('household-name')).toHaveText('어머니 댁');
    // 다시 데모 탭으로: 패널은 마운트된 채 숨는다
    await page.getByTestId('tab-demo').click();
    await expect(page).toHaveURL(/\/demo#demo$/);
    await expect(page.getByTestId('pane-family')).toBeHidden();
    await expect(page.getByTestId('family-home')).toHaveCount(1);
    await expect(page.getByTestId('demo-page')).toBeVisible();
  });

  test('/demo#family opens the family tab', async ({ page }) => {
    await mockApi(page);
    await page.goto('/demo#family');
    await expect(page.getByTestId('tab-family')).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByTestId('tab-demo')).toHaveAttribute('aria-selected', 'false');
    await expect(page.getByTestId('pane-family')).toBeVisible();
    await expect(page.getByTestId('pane-demo')).toBeHidden();
    await expect(page.getByTestId('demo-page')).toHaveCount(1);
    await expect(page.getByTestId('household-name')).toHaveText('어머니 댁', { timeout: 20_000 });
  });

  test('390px wide: no horizontal scroll on either tab', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await mockApi(page);
    await page.goto('/demo');
    await expect(page.getByTestId('outbox-item')).toHaveCount(3);
    await page.getByTestId('btn-inject-no_morning_water').click();
    await expect(page.getByTestId('demo-score-row')).toHaveCount(1);
    await expectNoHorizontalScroll(page, 390);
    const resetBox = (await page.getByTestId('btn-reset').boundingBox())!;
    const toggleBox = (await page.getByTestId('theme-toggle').boundingBox())!;
    const overlap =
      resetBox.x < toggleBox.x + toggleBox.width &&
      toggleBox.x < resetBox.x + resetBox.width &&
      resetBox.y < toggleBox.y + toggleBox.height &&
      toggleBox.y < resetBox.y + resetBox.height;
    expect(overlap).toBe(false);
    await page.getByTestId('tab-family').click();
    await expect(page.getByTestId('household-name')).toHaveText('어머니 댁', { timeout: 20_000 });
    await expectNoHorizontalScroll(page, 390);
  });
});
