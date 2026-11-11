import { test, expect, type Page } from '@playwright/test';
import path from 'node:path';

const SHOT_DIR = process.env.ILLY_SHOT_DIR ?? 'tests/e2e/screenshots';

test.describe.configure({ mode: 'serial' });

async function waitForServiceWorker(page: Page) {
  return page.evaluate(async () => {
    const reg = await navigator.serviceWorker.ready;
    return Boolean(reg.active);
  });
}

test('데모로 둘러보기 버튼으로 어머니 댁에 들어간다', async ({ page }) => {
  await page.goto('/login');
  await page.getByTestId('btn-demo-login').click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByTestId('household-name')).toHaveText('어머니 댁');
  await expect(page.getByTestId('today-card')).toBeVisible();
  await expect(page.getByTestId('btn-push')).toHaveText('알림 받기');
  await expect(page.getByTestId('sleep-banner')).toHaveCount(0);
  await page.screenshot({ path: path.join(SHOT_DIR, 'pwa-entry.png'), fullPage: true });
});

test('/?demo=1 은 로그인 없이 홈으로 들어간다', async ({ page }) => {
  await page.goto('/?demo=1');
  await expect(page.getByTestId('household-name')).toHaveText('어머니 댁');
  await expect(page).toHaveURL(/\/$/);
});

test('manifest 가 홀로안심 이름으로 제공된다', async ({ request }) => {
  const res = await request.get('/manifest.webmanifest');
  expect(res.status()).toBe(200);
  const body = await res.json();
  expect(body.name).toBe('홀로안심');
});

test('서비스워커가 등록되고 활성화된다', async ({ page }) => {
  await page.goto('/login');
  await expect(page.getByTestId('login-email')).toBeVisible();
  expect(await waitForServiceWorker(page)).toBe(true);
});

test('오프라인에서 다시 열어도 앱 셸이 보인다', async ({ page, context }) => {
  await page.goto('/?demo=1');
  await expect(page.getByTestId('household-name')).toHaveText('어머니 댁');
  expect(await waitForServiceWorker(page)).toBe(true);
  // 서비스워커가 이 페이지를 제어하도록 온라인에서 한 번 다시 연다
  await page.reload();
  await expect.poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller))).toBe(true);

  await context.setOffline(true);
  await page.reload();
  // 오프라인이면 supabase-js 요청이 재시도 끝에 실패한 뒤에야 카드가 그려진다
  await expect(page.getByTestId('today-card').or(page.getByTestId('login-email'))).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('sleep-banner')).toHaveText('데모가 잠들어 있습니다. 잠시 뒤 다시 열어 주세요');
  await page.screenshot({ path: path.join(SHOT_DIR, 'pwa-offline.png'), fullPage: true });
  await context.setOffline(false);
});

test('푸시를 켤 수 없는 브라우저는 안내 문구를 보인다', async ({ page }) => {
  await page.goto('/?demo=1');
  await expect(page.getByTestId('household-name')).toHaveText('어머니 댁');
  await page.getByTestId('btn-push').click();
  await expect(page.getByTestId('push-status')).toHaveText('이 브라우저에서는 푸시를 켤 수 없습니다');
  await expect(page.getByTestId('btn-push')).toHaveText('알림 받기');
});

test('푸시 아직 안 켠 상태에서 iPhone 안내가 보인다', async ({ page }) => {
  await page.goto('/?demo=1');
  await expect(page.getByTestId('household-name')).toHaveText('어머니 댁');
  await expect(page.getByTestId('btn-push')).toHaveText('알림 받기');
  await expect(page.getByTestId('push-hint')).toHaveText('iPhone은 홈 화면에 추가한 앱에서만 알림이 옵니다.');
});

test('테마 토글로 다크 모드가 되고 새로고침 뒤에도 유지된다', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'light' });
  await page.goto('/?demo=1');
  await expect(page.getByTestId('household-name')).toHaveText('어머니 댁');
  await page.getByTestId('theme-toggle').click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.reload();
  await expect(page.getByTestId('household-name')).toHaveText('어머니 댁');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
});
