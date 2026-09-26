import { expect, test } from "@playwright/test";

test("public landing page exposes crawlable SEO structure", async ({ page, request }) => {
  const response = await request.get("/");
  const source = await response.text();
  expect(source.match(/<h1[\s>]/g)).toHaveLength(1);
  expect(source.match(/<h2[\s>]/g)?.length).toBeGreaterThanOrEqual(1);
  expect(source).toContain('href="/pricing"');
  expect(source).toContain('href="/about"');
  expect(source).toContain('rel="icon"');

  await page.goto("/");
  await expect(page.locator("h1")).toHaveCount(1);
  await expect(page.locator("h2")).not.toHaveCount(0);
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", "https://dripcut.onrender.com/");

  const llms = await request.get("/llms.txt");
  expect(llms.ok()).toBe(true);
  expect(await llms.text()).toContain("# DripCut");
});

for (const viewport of [{ width: 390, height: 844 }, { width: 412, height: 915 }, { width: 768, height: 1024 }]) {
  test(`launch surface fits ${viewport.width}px screens`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Paste the link. Skip the busywork." })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.getByRole("button", { name: "Try DripCut free" }).first().click();
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

test("expired confirmation links show recovery and remove URL credentials", async ({ page }) => {
  await page.goto("/auth/callback#error=access_denied&error_code=otp_expired&error_description=untrusted-provider-text&access_token=discard-me");
  await expect(page.getByText(/This confirmation link has expired or was already used/)).toBeVisible();
  await expect(page).toHaveURL(/\/auth\/callback$/);
  await expect(page.getByText("untrusted-provider-text")).toHaveCount(0);
  await expect(page.locator(".auth-card .auth-loader")).toHaveCount(0);
  await page.getByRole("button", { name: "Return to login" }).click();
  await expect(page).toHaveURL(/\/login$/);
});
