import { defineConfig } from '@playwright/test';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const baseURL = 'http://127.0.0.1:4173';

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: 'line',
  outputDir: join(tmpdir(), 'vanna-webcomponent-playwright-results'),
  use: {
    baseURL,
    headless: true,
    trace: 'off',
  },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 4173 --strictPort',
    url: `${baseURL}/tests/e2e/harness.html`,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
