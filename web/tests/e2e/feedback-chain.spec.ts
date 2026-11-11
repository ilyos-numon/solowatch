import { test, expect } from '@playwright/test';
import path from 'node:path';

// Runs against alerts the daemon wrote to Supabase (see tests/e2e/test_home_chain.py).
const SHOT_DIR = process.env.ILLY_SHOT_DIR ?? 'tests/e2e/screenshots';
const PASSWORD = 'solowatch-demo-1234';
const SENTENCE = '이상 가능성 있음 · 아침 (6~12시) 물 사용 없음 · 평소와 다릅니다';

test.use({ timezoneId: 'Asia/Seoul', locale: 'ko-KR' });

test('family marks the 10/30 morning alert 괜찮았음', async ({ page }) => {
  await page.goto('/login');
  await page.getByTestId('login-email').fill('family@example.com');
  await page.getByTestId('login-password').fill(PASSWORD);
  await page.getByTestId('login-submit').click();
  await expect(page.getByTestId('household-name')).toHaveText('어머니 댁');

  const item = page
    .getByTestId('alert-item')
    .filter({ hasText: SENTENCE })
    .filter({ hasText: '10/30' });
  await expect(item).toHaveCount(1);
  await expect(item.getByTestId('alert-status')).toHaveText('확인 필요');
  await page.waitForTimeout(1500); // realtime channel join
  await item.getByTestId('btn-ok').click();
  await expect(item.getByTestId('alert-status')).toHaveText('괜찮았음', { timeout: 5000 });
  await page.screenshot({ path: path.join(SHOT_DIR, 'chain-feedback.png'), fullPage: true });
});
