import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "./container-tests",
  workers: 1,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: "http://experiment-doctor.local:8080",
    headless: true,
    channel: "chrome",
    launchOptions: {
      args: ["--host-resolver-rules=MAP experiment-doctor.local 127.0.0.1"],
    },
    trace: "retain-on-failure",
  },
  projects: [
    { name: "container-desktop", use: { ...devices["Desktop Chrome"] } },
    {
      name: "container-mobile",
      use: { ...devices["iPhone 13"], defaultBrowserType: "chromium" },
    },
  ],
});
