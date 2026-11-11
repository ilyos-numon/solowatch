import { defineConfig } from '@playwright/test';

const PORT = Number(process.env.E2E_PORT ?? 8841);

export default defineConfig({
  testDir: 'tests/e2e',
  // 모든 spec 이 같은 로컬 Supabase 데모 가구를 쓴다 — 파일 간 경합을 막으려고 직렬 실행
  workers: 1,
  use: {
    baseURL: `http://localhost:${PORT}`,
    viewport: { width: 390, height: 844 },
  },
  projects: [
    { name: 'app', testIgnore: [/feedback-chain\.spec\.ts/, /demo-page\.spec\.ts/, /record-demo\.spec\.ts/] },
    { name: 'chain', testMatch: /feedback-chain\.spec\.ts/ },
    { name: 'demo', testMatch: /demo-page\.spec\.ts/, use: { viewport: { width: 1440, height: 900 } } },
    {
      name: 'record',
      testMatch: /record-demo\.spec\.ts/,
      timeout: 180_000,
      use: { viewport: { width: 1280, height: 800 }, video: { mode: 'on', size: { width: 1280, height: 800 } } },
    },
  ],
  webServer: {
    command: `npm run build && npm run preview -- --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: true,
  },
});
