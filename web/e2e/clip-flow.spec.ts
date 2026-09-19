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

    const universalContent = await page.evaluate(async () => {
      const projectsResponse = await fetch("/api/projects?limit=10");
      const projects = await projectsResponse.json();
      const project = projects.find((item: { status: string }) => item.status === "completed");
      const [contentResponse, capabilitiesResponse] = await Promise.all([
        fetch(`/api/projects/${encodeURIComponent(project.id)}/content`),
        fetch("/api/social/capabilities"),
      ]);
      return {
        content: await contentResponse.json(),
        capabilities: await capabilitiesResponse.json(),
      };
    });
    expect(universalContent.content).toEqual([
      expect.objectContaining({ content_type: "video_clip", status: "ready" }),
    ]);
    expect(universalContent.capabilities).toEqual(expect.arrayContaining([
      expect.objectContaining({ platform: "youtube", can_schedule: true }),
      expect.objectContaining({ platform: "instagram", can_schedule: true }),
    ]));

    await page.goto("/schedule");
    await expect(page.getByRole("heading", { name: /What will you/ })).toBeVisible();
    await expect(page.getByRole("button", { name: "Schedule", exact: true })).toHaveCount(0);

    await page.goto("/logout");
    await expect(page).toHaveURL(/\/login$/);
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(password);
    await page.locator("form").getByRole("button", { name: "Log in", exact: true }).click();
    await expect(page).toHaveURL(/\/home$/);
    await expect(page.getByRole("heading", { name: "Continue creating" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Open sample" })).toBeVisible();

    await page.route("**/api/jobs/youtube", async (route) => {
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({
          id: "blocked-youtube-job",
          source_id: "",
          project_id: "youtube-project",
          status: "failed",
          progress: 0,
          percent: 0,
          stage: "Failed",
          elapsed: 1,
          error: "YouTube asked the processing server for additional verification.",
          error_code: "BOT_CHALLENGE",
          hint: "Retry once, or upload a copy you are allowed to use and continue.",
          retryable: true,
          artifacts: [],
        }),
      });
    });
    await page.goto("/auto-clip");
    await page.getByLabel("YouTube video URL").fill("https://www.youtube.com/watch?v=jNQXAC9IVRw");
    await page.getByLabel("I own this video or have permission to edit and republish it.").check();
    await page.getByRole("button", { name: "Import video" }).click();
    await expect(page.getByText("Keep going with this project")).toBeVisible();
    await expect(page.getByRole("button", { name: "Retry YouTube" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Upload video instead" })).toBeVisible();
  });
});
