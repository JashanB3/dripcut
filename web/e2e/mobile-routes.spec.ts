import { expect, test } from "@playwright/test";

const signedInRoutes = ["/home", "/projects", "/templates", "/auto-clip", "/schedule", "/usage", "/settings"];

for (const viewport of [{ width: 390, height: 844 }, { width: 412, height: 915 }]) {
  test(`launch pages remain usable at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    for (const path of ["/login", "/signup"]) {
      await page.goto(path);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    }

    await page.goto("/signup");
    await page.getByLabel("Name").fill("Mobile audit");
    await page.getByLabel("Email").fill(`mobile-audit-${viewport.width}-${Date.now()}@example.test`);
    await page.getByLabel("Password").fill("disposable-local-qa-only");
    await page.getByRole("button", { name: "Create free account" }).click();
    await expect(page).toHaveURL(/\/home$/);

    for (const path of signedInRoutes) {
      await page.goto(path);
      await expect(page.locator("main")).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    }

    await expect(page.getByRole("button", { name: "Create", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Create", exact: true }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });
}
