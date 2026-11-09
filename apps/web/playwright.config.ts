import { defineConfig, devices } from "@playwright/test";
const apiPort = process.env.ED_BROWSER_PORT ?? '8000';
if (!/^\d{2,5}$/.test(apiPort) || Number(apiPort) > 65535) throw new Error('Invalid test API port');
export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  workers: 2,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:5173",
    headless: true,
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        channel: process.env.CI ? undefined : "chrome",
      },
    },
    {
      name: "mobile",
      use: {
        ...devices["iPhone 13"],
        defaultBrowserType: "chromium",
        channel: process.env.CI ? undefined : "chrome",
      },
    },
  ],
  webServer: [
    {
      command: ".venv/bin/python -m tests.browser_server",
      cwd: "../..",
      url: `http://127.0.0.1:${apiPort}/health/live`,
      ignoreHTTPSErrors: false,
      reuseExistingServer: !process.env.CI,
    },
    {
      command: "npm run dev",
      env: {ED_API_PROXY: `http://127.0.0.1:${apiPort}`},
      url: "http://127.0.0.1:5173",
      reuseExistingServer: !process.env.CI,
    },
  ],
});
