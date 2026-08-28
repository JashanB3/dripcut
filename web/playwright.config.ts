import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? [["line"], ["html", { open: "never" }]] : "list",
  globalSetup: "./e2e/global.setup.ts",
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [
    {
      name: "desktop-chrome",
      use: { ...devices["Desktop Chrome"], channel: "chrome" },
    },
  ],
  webServer: [
    {
      command: "DRIPCUT_HOME=/tmp/dripcut-playwright DRIPCUT_OUTPUT=/tmp/dripcut-playwright/out DRIPCUT_ENV=development DRIPCUT_AUTH_PROVIDER=local DRIPCUT_TENANT_PROVIDER=local DRIPCUT_USAGE_PROVIDER=local DRIPCUT_AUTH_REQUIRED=1 ../.venv/bin/python -m uvicorn dripcut.api.app:create_app --factory --host 127.0.0.1 --port 8000",
      url: "http://127.0.0.1:8000/api/health",
      cwd: ".",
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
    },
    {
      command: "npm run dev",
      url: "http://127.0.0.1:5173",
      cwd: ".",
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
    },
  ],
});
