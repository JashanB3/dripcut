import { expect, test } from "@playwright/test";
import { resolve } from "node:path";

test.describe("creator clipping journey", () => {
  const email = `playwright-${Date.now()}@example.test`;
  const password = "correct-horse";

  test("signup, upload, clip, caption choice, and ZIP download", async ({ page, request }) => {
    await page.goto("/signup");
    await page.getByLabel("Name").fill("Playwright Creator");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(password);
    await page.getByRole("button", { name: "Create free account" }).click();

    await expect(page).toHaveURL(/\/home$/);
    await page.goto("/auto-clip");
    await page.locator('input[type="file"]').setInputFiles(resolve(".e2e/sample.mp4"));
    await expect(page.getByRole("heading", { name: "Two choices. That’s it." })).toBeVisible();

    await page.getByRole("button", { name: "15s" }).click();
    await page.getByLabel("Auto captions").uncheck();
    await page.getByRole("button", { name: "Create 1 clip" }).click();

    await expect(page.getByRole("heading", { name: "Your clips are ready." })).toBeVisible({ timeout: 90_000 });
    const zip = page.getByRole("link", { name: /Download ZIP/ }).first();
    await expect(zip).toBeVisible();
    const href = await zip.getAttribute("href");
    expect(href).toBeTruthy();
    const response = await request.get(new URL(href!, page.url()).toString(), {
      headers: { Cookie: (await page.context().cookies()).map((cookie) => `${cookie.name}=${cookie.value}`).join("; ") },
    });
    expect(response.status()).toBe(200);
    expect((await response.body()).byteLength).toBeGreaterThan(1_000);

    await page.goto("/logout");
    await expect(page).toHaveURL(/\/login$/);
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(password);
    await page.locator("form").getByRole("button", { name: "Log in", exact: true }).click();
    await expect(page).toHaveURL(/\/home$/);
    await expect(page.getByRole("heading", { name: "Continue creating" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Open sample" })).toBeVisible();
  });
});
