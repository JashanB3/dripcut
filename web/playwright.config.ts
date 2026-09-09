import { defineConfig, devices } from "@playwright/test";

const apiPort = process.env.DRIPCUT_E2E_API_PORT || "8011";
const webPort = process.env.DRIPCUT_E2E_WEB_PORT || "5175";
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
      command: `PYTHON_DOTENV_DISABLED=1 DRIPCUT_HOME=/tmp/dripcut-playwright DRIPCUT_OUTPUT=/tmp/dripcut-playwright/out DRIPCUT_ENV=development DRIPCUT_AUTH_PROVIDER=local DRIPCUT_TENANT_PROVIDER=local DRIPCUT_USAGE_PROVIDER=local DRIPCUT_CONTENT_STORE=local DRIPCUT_SOCIAL_STORE=local DRIPCUT_STORAGE_PROVIDER=local DRIPCUT_COOKIE_SECURE=0 DRIPCUT_ALLOWED_ORIGINS=${webUrl} DRIPCUT_FRONTEND_URL=${webUrl} DRIPCUT_AUTH_REQUIRED=1 ../.venv/bin/python -m uvicorn dripcut.api.app:create_app --factory --host 127.0.0.1 --port ${apiPort}`,
      url: `${apiUrl}/api/health`,
      cwd: ".",
      timeout: 120_000,
      reuseExistingServer: false,
    },
    {
      command: `DRIPCUT_WEB_PORT=${webPort} DRIPCUT_API_PROXY_URL=${apiUrl} npm run dev`,
      url: webUrl,
      cwd: ".",
      timeout: 120_000,
      reuseExistingServer: false,
    },
  ],
});
