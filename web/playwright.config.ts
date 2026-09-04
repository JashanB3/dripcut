import { defineConfig, devices } from "@playwright/test";

const apiPort = process.env.DRIPCUT_E2E_API_PORT || "8000";
const webPort = process.env.DRIPCUT_E2E_WEB_PORT || "5173";
const apiUrl = `http://127.0.0.1:${apiPort}`;
const webUrl = `http://127.0.0.1:${webPort}`;

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
    baseURL: webUrl,
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
      command: `DRIPCUT_HOME=/tmp/dripcut-playwright DRIPCUT_OUTPUT=/tmp/dripcut-playwright/out DRIPCUT_ENV=development DRIPCUT_AUTH_PROVIDER=local DRIPCUT_TENANT_PROVIDER=local DRIPCUT_USAGE_PROVIDER=local DRIPCUT_AUTH_REQUIRED=1 ../.venv/bin/python -m uvicorn dripcut.api.app:create_app --factory --host 127.0.0.1 --port ${apiPort}`,
      url: `${apiUrl}/api/health`,
      cwd: ".",
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
    },
    {
      command: `DRIPCUT_WEB_PORT=${webPort} DRIPCUT_API_PROXY_URL=${apiUrl} npm run dev`,
      url: webUrl,
      cwd: ".",
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
    },
  ],
});
