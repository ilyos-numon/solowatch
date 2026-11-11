import { test, expect, type Locator, type Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

// README 30초 GIF 녹화 시나리오 (scripts/make_demo_gif.sh 가 실행한다).
// 전제: 데모 서버가 8845 에서 ready, preview 의 /api 프록시가 그쪽을 가리킨다.
// 시각은 docs/demo-script.md "라이브 30초" 진행표를 따른다 (녹화 시작 기준 초).
const SENTENCE = '이상 가능성 있음 · 아침 (6~12시) 물 사용 없음 · 평소와 다릅니다';

test.use({
  timezoneId: 'Asia/Seoul',
  locale: 'ko-KR',
  viewport: { width: 1440, height: 900 },
  video: { mode: 'on', size: { width: 1440, height: 900 } },
});

test.afterEach(async ({ page }, testInfo) => {
  const video = page.video();
  await page.close();
  if (!video) return;
  const dest = path.join(testInfo.project.outputDir, 'record', 'demo.webm');
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.copyFileSync(await video.path(), dest);
});

// 마우스가 영상에 남도록 요소 위로 옮기고 잠깐 머문 뒤 클릭
async function hoverClick(page: Page, target: Locator, pauseMs = 700) {
  await target.hover();
  await page.waitForTimeout(pauseMs);
  await target.click();
}

test('live demo: 아침 물 없음 → 가족 앱 알림 → 괜찮았음 → 재주입 점수 전후', async ({ page }) => {
  const t0 = Date.now();
  // 녹화 시작 기준 sec 초까지 머문다 (이미 지났으면 바로 진행)
  const until = async (sec: number) => {
    const left = t0 + sec * 1000 - Date.now();
    if (left > 0) await page.waitForTimeout(left);
  };

  // 0:00–0:05 라이브 데모 탭 (그래프·버튼)
  await page.goto('/demo');
  await expect(page.getByTestId('demo-page')).toBeVisible();
  await expect(page.getByTestId('demo-not-ready')).toHaveCount(0, { timeout: 90_000 });
  const injectBtn = page.getByTestId('btn-inject-no_morning_water');
  await expect(injectBtn).toBeEnabled({ timeout: 90_000 });
  await injectBtn.hover();
  await until(4.3);

  // 0:05–0:12 아침 물 없음 주입 → 그래프 재생, 가운데에 나간 행
  await hoverClick(page, injectBtn);
  // 초기화 직후 첫 주입은 가상 2026-11-02 (시드된 10/30 같은 문장 알림과 구분)
  const item = page.getByTestId('alert-item').filter({ hasText: SENTENCE }).filter({ hasText: '11/2 06:00' });
  // 가족 앱 패널은 숨겨진 채 마운트돼 있다 — 알림이 도착(attached)했는지만 확인
  await expect(item).toBeAttached({ timeout: 30_000 });
  await until(11);

  // 0:12–0:18 가족 앱 탭으로 전환, 알림 한 줄
  await hoverClick(page, page.getByTestId('tab-family'), 400);
  await expect(item).toBeVisible({ timeout: 20_000 });
  await item.scrollIntoViewIfNeeded();
  const okBtn = item.getByTestId('btn-ok');
  await okBtn.hover();
  await until(17.3);

  // 0:18–0:22 괜찮았음 → 가운데에 들어온 가족 응답
  await hoverClick(page, okBtn);
  await expect(item.getByTestId('alert-status')).toHaveText('괜찮았음', { timeout: 10_000 });
  await hoverClick(page, page.getByTestId('tab-demo'), 400);
  await injectBtn.hover();
  await until(21.3);

  // 0:22–0:28 같은 하루 재주입 → 점수 전후
  await hoverClick(page, injectBtn);
  const lastRow = page.getByTestId('demo-score-row').last();
  await expect(lastRow).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(800);
  // 점수 표 전체가 화면 안에 들어오도록 표 아래 끝을 기준으로 스크롤
  await lastRow.locator('xpath=ancestor::table[1]').evaluate((el) =>
    el.scrollIntoView({ block: 'end', behavior: 'smooth' }),
  );
  await until(26);

  // 0:28–0:30 끝: 점수 표를 4초 이상 보여 준다
  await page.waitForTimeout(4000);
  await until(30);
});
