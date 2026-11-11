import { test, expect, type Page } from '@playwright/test';
import { createClient } from '@supabase/supabase-js';
import path from 'node:path';

const SHOT_DIR = process.env.ILLY_SHOT_DIR ?? 'tests/e2e/screenshots';
const DEMO_HID = '11111111-1111-4111-8111-111111111111';
const FAMILY_UID = 'aaaaaaaa-aaaa-4aaa-8aaa-000000000001';
const PASSWORD = 'solowatch-demo-1234';
const SENSORS = ['water_main', 'plug_fridge', 'plug_tv', 'plug_light'];
// fixed past days so the rows never collide with a real daemon's "today" upsert
const REPORT_DAYS = ['2026-10-01', '2026-10-02'];
const AWAY_NOTE = '여행';
const STARTED_NOTE = '병원';
const ORDER_NOTE = '순서';

const admin = createClient(process.env.E2E_SUPABASE_URL!, process.env.E2E_SERVICE_ROLE_KEY!, {
  auth: { persistSession: false, autoRefreshToken: false },
});

test.describe.configure({ mode: 'serial' });

function localToday(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function addDays(iso: string, n: number): string {
  const [y, m, d] = iso.split('-').map(Number);
  const dt = new Date(y, m - 1, d + n);
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`;
}

function md(iso: string): string {
  const [, m, d] = iso.split('-');
  return `${Number(m)}/${Number(d)}`;
}

// future trip (예정), relative to today so the case stays a future trip on any run date
const AWAY_START = addDays(localToday(), 7);
const AWAY_END = addDays(localToday(), 9);

function hours(active: number[]): boolean[] {
  return Array.from({ length: 24 }, (_, h) => active.includes(h));
}

const RHYTHM = {
  water_main: hours([6, 7, 12, 19]),
  plug_fridge: hours(Array.from({ length: 24 }, (_, h) => h)),
  plug_tv: hours([19, 20, 21]),
  plug_light: hours([18, 19, 20, 21, 22]),
};

async function login(page: Page) {
  await page.goto('/login');
  await page.getByTestId('login-email').fill('family@example.com');
  await page.getByTestId('login-password').fill(PASSWORD);
  await page.getByTestId('login-submit').click();
  await expect(page.getByTestId('household-name')).toHaveText('어머니 댁');
}

async function expectNoHorizontalScroll(page: Page) {
  const width = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(width).toBeLessThanOrEqual(390);
}

async function cleanReports() {
  const { error } = await admin.from('daily_reports').delete().eq('household_id', DEMO_HID).in('day', REPORT_DAYS);
  expect(error).toBeNull();
}

async function cleanAway() {
  const { error } = await admin
    .from('away_periods')
    .delete()
    .eq('household_id', DEMO_HID)
    .in('note', [AWAY_NOTE, STARTED_NOTE, ORDER_NOTE]);
  expect(error).toBeNull();
}

test.beforeAll(async () => {
  await cleanReports();
  await cleanAway();
});

test.afterAll(async () => {
  await cleanReports();
  await cleanAway();
});

test.describe('rhythm chart', () => {
  test('shows empty message without reports', async ({ page }) => {
    await login(page);
    await expect(page.getByTestId('rhythm-empty')).toHaveText('아직 리듬 데이터가 없습니다');
    await expect(page.locator('[data-testid^="rhythm-chart-"]')).toHaveCount(0);
  });

  test.describe('with daily reports', () => {
    test.beforeEach(async () => {
      const rows = REPORT_DAYS.map((day, i) => ({
        household_id: DEMO_HID,
        day,
        sentence: i === REPORT_DAYS.length - 1 ? '오늘 리듬 정상 · 아침 6시 물 사용' : '오늘 리듬 정상 · 아침 7시 물 사용',
        rhythm: RHYTHM,
        first_events: {},
      }));
      const { error } = await admin.from('daily_reports').insert(rows);
      expect(error).toBeNull();
    });

    test.afterEach(cleanReports);

    test('renders four hour grids', async ({ page }) => {
      await login(page);
      for (const id of SENSORS) {
        const chart = page.getByTestId(`rhythm-chart-${id}`);
        await expect(chart).toBeVisible();
        await expect(chart.locator('span.rh-cell')).toHaveCount(48);
        expect(await chart.locator('span.rh-cell.on-usual').count()).toBeGreaterThanOrEqual(1);
        expect(await chart.locator('span.rh-cell.on-today').count()).toBeGreaterThanOrEqual(1);
      }
      await expect(page.getByTestId('rhythm-readout')).toHaveText(
        `${md(REPORT_DAYS[REPORT_DAYS.length - 1])} 요약을 오늘로 봅니다. 칸에 마우스를 올리면 시간별로 보입니다.`,
      );
      await expect(page.getByTestId('rhythm-empty')).toHaveCount(0);
      await expectNoHorizontalScroll(page);
      await page.screenshot({ path: path.join(SHOT_DIR, 'home-rhythm.png'), fullPage: true });
    });
  });
});

test.describe('away periods', () => {
  test.afterEach(cleanAway);

  test('create a future trip and cancel it', async ({ page }) => {
    const today = localToday();
    await login(page);
    await page.getByTestId('away-open').click();
    await expect(page.getByTestId('away-open')).toHaveAttribute('aria-expanded', 'true');
    await page.getByTestId('away-start').fill(AWAY_START);
    await page.getByTestId('away-end').fill(AWAY_END);
    await page.getByTestId('away-note').fill(AWAY_NOTE);
    await page.getByTestId('away-submit').click();

    const item = page.getByTestId('away-item').filter({ hasText: `${md(AWAY_START)} ~ ${md(AWAY_END)} ${AWAY_NOTE}` });
    await expect(item).toBeVisible();
    await expect(item).toContainText('예정');
    await expect(item.getByTestId('away-end-btn')).toHaveText('취소');

    const { data, error } = await admin
      .from('away_periods')
      .select('id, start_date, end_date, note, created_by')
      .eq('household_id', DEMO_HID)
      .eq('start_date', AWAY_START)
      .eq('note', AWAY_NOTE);
    expect(error).toBeNull();
    expect(data).toHaveLength(1);
    expect(data![0]).toMatchObject({ end_date: AWAY_END, created_by: FAMILY_UID });

    await expectNoHorizontalScroll(page);
    await page.screenshot({ path: path.join(SHOT_DIR, 'away-form.png'), fullPage: true });

    await item.getByTestId('away-end-btn').click();
    await expect
      .poll(async () => {
        const { data: row } = await admin.from('away_periods').select('start_date, end_date').eq('id', data![0].id).single();
        return row;
      })
      .toEqual({ start_date: AWAY_START, end_date: addDays(today, -1) });
    await expect(item).toHaveCount(0);
  });

  test('end a started trip today', async ({ page }) => {
    const today = localToday();
    const end = addDays(today, 2);
    await login(page);
    await page.getByTestId('away-open').click();
    await page.getByTestId('away-start').fill(today);
    await page.getByTestId('away-end').fill(end);
    await page.getByTestId('away-note').fill(STARTED_NOTE);
    await page.getByTestId('away-submit').click();

    const item = page.getByTestId('away-item').filter({ hasText: `${md(today)} ~ ${md(end)} ${STARTED_NOTE}` });
    await expect(item).toBeVisible();
    await expect(item).toContainText('표시 중');
    await expect(item.getByTestId('away-end-btn')).toHaveText('오늘 종료');

    const { data, error } = await admin
      .from('away_periods')
      .select('id')
      .eq('household_id', DEMO_HID)
      .eq('note', STARTED_NOTE);
    expect(error).toBeNull();
    expect(data).toHaveLength(1);

    await item.getByTestId('away-end-btn').click();
    await expect
      .poll(async () => {
        const { data: row } = await admin.from('away_periods').select('start_date, end_date').eq('id', data![0].id).single();
        return row;
      })
      .toEqual({ start_date: today, end_date: today });
    await expect(page.getByTestId('away-item').filter({ hasText: `${md(today)} ~ ${md(today)} ${STARTED_NOTE}` })).toBeVisible();
  });

  test('reversed or missing dates show a message and send nothing', async ({ page }) => {
    let posts = 0;
    await page.route('**/rest/v1/away_periods*', async (route) => {
      if (route.request().method() === 'POST') posts += 1;
      await route.continue();
    });
    const today = localToday();
    await login(page);
    await page.getByTestId('away-open').click();

    await page.getByTestId('away-submit').click();
    await expect(page.getByTestId('away-msg')).toHaveText('시작하는 날과 끝나는 날을 모두 골라 주세요.');

    await page.getByTestId('away-start').fill(addDays(today, 5));
    await page.getByTestId('away-end').fill(addDays(today, 3));
    await page.getByTestId('away-note').fill(ORDER_NOTE);
    await page.getByTestId('away-submit').click();
    await expect(page.getByTestId('away-msg')).toHaveText('끝나는 날이 시작하는 날보다 앞설 수 없습니다.');
    await expect(page.getByTestId('away-end')).toHaveAttribute('min', addDays(today, 5));
    expect(posts).toBe(0);

    await page.getByTestId('away-cancel').click();
    await expect(page.getByTestId('away-open')).toHaveAttribute('aria-expanded', 'false');
    await expect(page.getByTestId('away-start')).toHaveCount(0);
    await expect(page.getByTestId('away-msg')).toHaveCount(0);
    expect(posts).toBe(0);
  });
});
