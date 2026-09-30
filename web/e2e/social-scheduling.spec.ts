import { expect, test } from "@playwright/test";

for (const width of [390, 1440]) {
  test(`Instagram-only scheduling and reload work at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/signup");
    await page.getByLabel("Name").fill("Social QA");
    await page.getByLabel("Email").fill(`social-${width}-${Date.now()}@example.test`);
    await page.getByLabel("Password").fill("disposable-local-qa-only");
    await page.getByRole("button", { name: "Create free account" }).click();
    await expect(page).toHaveURL(/\/home$/);
    const connections = ["youtube", "instagram"].map((platform) => ({ platform, label: platform, configured: true, connected: platform === "instagram", detail: "Connected as creator", setup_hint: "", channel_id: "", avatar_url: "" }));
    await page.route("**/api/social/connections", (route) => route.fulfill({ json: connections }));
    await page.route("**/api/projects?*", (route) => route.fulfill({ json: [{ id: "project-qa", title: "Finished project", status: "completed", latest_job_id: "job-qa", artifact_ids: ["clip-qa"], created_at: 1, updated_at: 1 }] }));
    await page.route("**/api/jobs/job-qa", (route) => route.fulfill({ json: { id: "job-qa", status: "succeeded", artifacts: [{ id: "clip-qa", kind: "clip", name: "My-clip.mp4", download_url: "/clip.mp4" }] } }));
    const saved = { id: "schedule-qa", project_id: "project-qa", archive_name: "1 clip", created_at: 1, publish_ready: true, posts: [{ id: "post-qa", platform: "instagram", clip_name: "My-clip.mp4", title: "My clip", publish_at: "2030-01-01T10:00:00Z", timezone: "UTC", publish_mode: "schedule", status: "scheduled", privacy: "public" }] };
    let accepted = false;
    await page.route("**/api/schedules/latest", (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify(accepted ? saved : null) }));
    await page.route("**/api/schedules/schedule-qa", (route) => route.fulfill({ json: saved }));
    await page.route("**/api/schedules", async (route) => {
      expect(route.request().postDataJSON().platforms).toEqual(["instagram"]);
      expect(route.request().postDataJSON().artifact_ids).toEqual(["clip-qa"]);
      accepted = true;
      await route.fulfill({ json: saved });
    });
    await page.goto("/schedule");
    await page.getByRole("button", { name: "Instagram Reels", exact: true }).click();
    await page.getByRole("button", { name: "YouTube Shorts", exact: true }).click();
    await expect(page.getByRole("button", { name: "YouTube Shorts", exact: true })).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByLabel("YouTube privacy")).toHaveCount(0);
    await expect(page.getByText(/YouTube privacy settings do not apply/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Schedule 1 clip" })).toBeEnabled();
    await page.getByRole("button", { name: "Schedule 1 clip" }).click();
    await expect(page.getByText("Publishing schedule accepted")).toBeVisible();
    await page.reload();
    await expect(page.getByText("Publishing schedule accepted")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `test-results/social-schedule-${width}.png`, fullPage: true });
    await page.getByRole("button", { name: "Schedule 1 clip" }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: `test-results/social-schedule-form-${width}.png` });
  });
}
