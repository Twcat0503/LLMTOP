import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 30000,
  workers: 1,
  outputDir: '../artifacts/playwright',
  reporter: [['list'], ['json', { outputFile: '../artifacts/playwright-results.json' }]],
  use: { baseURL: 'http://127.0.0.1:8787', headless: true, screenshot: 'only-on-failure', trace: 'off' },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1505, height: 1045 } } },
    { name: 'mobile', use: { viewport: { width: 375, height: 812 } } },
    { name: 'small-desktop', use: { viewport: { width: 1024, height: 768 } } },
  ],
});
