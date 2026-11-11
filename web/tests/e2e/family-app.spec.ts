import { test, expect, type Page } from '@playwright/test';
import { createClient } from '@supabase/supabase-js';
import path from 'node:path';

const SHOT_DIR = process.env.ILLY_SHOT_DIR ?? 'tests/e2e/screenshots';
const DEMO_HID = '11111111-1111-4111-8111-111111111111';
const PASSWORD = 'solowatch-demo-1234';
const SENTENCE = '이상 가능성 있음 · 아침 물 사용 없음 · 평소와 다릅니다';

const admin = createClient(process.env.E2E_SUPABASE_URL!, process.env.E2E_SERVICE_ROLE_KEY!, {
  auth: { persistSession: false, autoRefreshToken: false },
});

test.describe.configure({ mode: 'serial' });

async function login(page: Page, email = 'family@example.com', password = PASSWORD) {
  await page.goto('/login');
  await page.getByTestId('login-email').fill(email);
  await page.getByTestId('login-password').fill(password);
  await page.getByTestId('login-submit').click();
}

async function expectNoHorizontalScroll(page: Page) {
  const width = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(width).toBeLessThanOrEqual(390);
}

test.describe('sign in and empty household', () => {
  test('unauthenticated / redirects to /login', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveURL(/\/login$/);
  });

  test('wrong password shows error and stays on /login', async ({ page }) => {
    await login(page, 'family@example.com', 'wrong');
    await expect(page.getByTestId('login-error')).toHaveText('이메일 또는 비밀번호가 맞지 않습니다');
    await expect(page).toHaveURL(/\/login$/);
    await expectNoHorizontalScroll(page);
    await page.screenshot({ path: path.join(SHOT_DIR, 'login.png'), fullPage: true });
  });

  test('learning period card when no alerts or reports', async ({ page }) => {
    await login(page);
    await expect(page.getByTestId('household-name')).toHaveText('어머니 댁');
    await expect(page.getByTestId('today-card')).toContainText('평소 리듬을 배우는 중입니다');
    await expectNoHorizontalScroll(page);
  });

  test('logout returns to /login', async ({ page }) => {
    await login(page);
    await expect(page.getByTestId('household-name')).toHaveText('어머니 댁');
    await page.getByTestId('family-home').getByRole('button', { name: '로그아웃' }).click();
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByTestId('login-email')).toBeVisible();
  });
});

test.describe('with an open alert', () => {
  let alertId = '';

  test.beforeEach(async () => {
    const now = new Date();
    const start = new Date(now.getTime() - 6 * 3600 * 1000);
    const { data, error } = await admin
      .from('alerts')
      .insert({
        household_id: DEMO_HID,
        kind: 'anomaly',
        window_start: start.toISOString(),
        window_end: now.toISOString(),
        sentence: SENTENCE,
        details: { sensors: [{ sensor_id: 'water', reason: 'below', expected: 3, actual: 0 }] },
      })
      .select('id')
      .single();
    expect(error).toBeNull();
    alertId = data!.id as string;
  });

  test.afterEach(async () => {
    await admin.from('alert_feedback').delete().eq('alert_id', alertId);
    await admin.from('alerts').delete().eq('id', alertId);
  });

  test('today card shows the open alert sentence', async ({ page }) => {
    await login(page);
    await expect(page.getByTestId('household-name')).toHaveText('어머니 댁');
    await expect(page.getByTestId('today-card')).toContainText(SENTENCE);
    const item = page.getByTestId('alert-item').filter({ hasText: SENTENCE });
    await expect(item.getByTestId('alert-status')).toHaveText('확인 필요');
    await expectNoHorizontalScroll(page);
    await page.screenshot({ path: path.join(SHOT_DIR, 'home-today.png'), fullPage: true });
  });

  test('괜찮았음 click stores feedback and updates badge via realtime', async ({ page }) => {
    await login(page);
    const item = page.getByTestId('alert-item').filter({ hasText: SENTENCE });
    await expect(item.getByTestId('alert-status')).toHaveText('확인 필요');
    // give the realtime channel a moment to join before the change happens
    await page.waitForTimeout(1500);
    await item.getByTestId('btn-ok').click();
    await expect(item.getByTestId('alert-status')).toHaveText('괜찮았음', { timeout: 5000 });
    await expect(item.getByTestId('btn-ok')).toHaveCount(0);

    const { data, error } = await admin
      .from('alert_feedback')
      .select('verdict, user_id')
      .eq('alert_id', alertId);
    expect(error).toBeNull();
    expect(data).toEqual([{ verdict: 'ok', user_id: 'aaaaaaaa-aaaa-4aaa-8aaa-000000000001' }]);
    await expectNoHorizontalScroll(page);
    await page.screenshot({ path: path.join(SHOT_DIR, 'alert-feedback.png'), fullPage: true });
  });

  test('답 바꾸기 lets the family answer again and stores a second feedback row', async ({ page }) => {
    await login(page);
    const item = page.getByTestId('alert-item').filter({ hasText: SENTENCE });
    await expect(item.getByTestId('alert-status')).toHaveText('확인 필요');
    await page.waitForTimeout(1500);
    await item.getByTestId('btn-ok').click();
    await expect(item.getByTestId('alert-status')).toHaveText('괜찮았음', { timeout: 5000 });

    await item.getByTestId('btn-reanswer').click();
    await expect(item.getByTestId('alert-status')).toHaveText('괜찮았음 → 다시 답하는 중');
    await expect(item.getByTestId('btn-reanswer')).toHaveCount(0);
    await item.getByTestId('btn-checking').click();
    await expect(item.getByTestId('alert-status')).toHaveText('확인 중', { timeout: 5000 });
    await expect(item.getByTestId('btn-checking')).toHaveCount(0);
    await expect(item.getByTestId('btn-reanswer')).toBeVisible();

    const { data, error } = await admin.from('alert_feedback').select('verdict').eq('alert_id', alertId);
    expect(error).toBeNull();
    expect((data ?? []).map((r) => r.verdict as string).sort()).toEqual(['checking', 'ok']);
    await expectNoHorizontalScroll(page);
  });

  test('guide cards sit beside the phone at 1440px', async ({ page }) => {
    await login(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await expect(page.getByTestId('household-name')).toHaveText('어머니 댁');
    await expect(page.getByTestId('alert-item').filter({ hasText: SENTENCE })).toBeVisible();
    const guide = page.getByTestId('guide-cards');
    await expect(guide.locator('h2')).toHaveCount(3);
    const phoneBox = await page.getByTestId('family-home').boundingBox();
    const guideBox = await guide.boundingBox();
    expect(guideBox!.x).toBeGreaterThan(phoneBox!.x + phoneBox!.width - 1);
    await page.screenshot({ path: path.join(SHOT_DIR, 'home-1440.png'), fullPage: true });
  });
});
