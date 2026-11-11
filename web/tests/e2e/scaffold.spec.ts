import { test, expect } from '@playwright/test';
import path from 'node:path';

const SHOT_DIR = process.env.ILLY_SHOT_DIR ?? 'tests/e2e/screenshots';

test('scaffold renders app title', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('홀로안심')).toBeVisible();
  await page.screenshot({ path: path.join(SHOT_DIR, 'scaffold.png'), fullPage: true });
});
