import { expect, test } from "@playwright/test";

for (const viewport of [{ width: 390, height: 844 }, { width: 412, height: 915 }, { width: 768, height: 1024 }]) {
  test(`launch surface fits ${viewport.width}px screens`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "One video in. A week of content out." })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.getByRole("button", { name: "Start creating free" }).first().click();
    await expect(page).toHaveURL(/\/signup$/);
    await page.getByLabel("Name").fill("Mobile QA");
    await page.getByLabel("Email").fill(`mobile-${viewport.width}-${Date.now()}@example.test`);
    await page.getByLabel("Password").fill("disposable-local-qa-only");
    await page.getByRole("button", { name: "Create free account" }).click();
    await expect(page).toHaveURL(/\/home$/);
    await page.getByRole("button", { name: "Create", exact: true }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.getByRole("heading", { name: "AI Video Editor" })).toHaveCount(0);
    await page.getByLabel("Close create menu").click();
    await page.goto("/create");
    await expect(page.getByRole("heading", { name: "Start with one long video." })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: `test-results/launch-${viewport.width}.png`, fullPage: true });
    await page.reload();
    await expect(page.getByRole("heading", { name: "Start with one long video." })).toBeVisible();
  });
}
