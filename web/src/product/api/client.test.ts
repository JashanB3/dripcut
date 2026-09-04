import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createClipJob,
  fetchAdminOverview,
  fetchProjectContent,
  fetchProjectContentSources,
  fetchProviderCapabilities,
  fetchUsage,
  parseApiResponse,
  requestJson,
} from "./client";

const jsonResponse = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status,
  headers: { "Content-Type": "application/json" },
});

describe("parseApiResponse", () => {
  it("parses a successful JSON response", async () => {
    await expect(parseApiResponse(jsonResponse({ ok: true }))).resolves.toEqual({ ok: true });
  });

  it("reports an empty successful response", async () => {
    await expect(parseApiResponse(new Response(null, { status: 200 }))).rejects.toMatchObject({
      code: "EMPTY_SERVER_RESPONSE",
      message: "The server returned an empty response.",
    });
  });

  it("accepts 204 without parsing a body", async () => {
    await expect(parseApiResponse(new Response(null, { status: 204 }))).resolves.toBeNull();
  });

  it("normalizes a 400 JSON error", async () => {
    await expect(parseApiResponse(jsonResponse({ error: { code: "BAD_INPUT", message: "Try another value." } }, 400)))
      .rejects.toMatchObject({ status: 400, code: "BAD_INPUT", message: "Try another value." });
  });

  it("preserves retry guidance and the request reference", async () => {
    await expect(parseApiResponse(jsonResponse({ error: {
      code: "AUTH_PROVIDER_UNAVAILABLE",
      message: "We could not sign you in right now.",
      hint: "Try again in a moment.",
      request_id: "request-123",
      retryable: true,
    } }, 503))).rejects.toMatchObject({
      code: "AUTH_PROVIDER_UNAVAILABLE",
      requestId: "request-123",
      retryable: true,
      hint: "Try again in a moment. · Request ID: request-123",
    });
  });

  it("normalizes a 500 JSON error", async () => {
    await expect(parseApiResponse(jsonResponse({ error: { code: "INTERNAL_SERVER_ERROR", message: "Try again." } }, 500)))
      .rejects.toMatchObject({ status: 500, code: "INTERNAL_SERVER_ERROR" });
  });

  it("turns an HTML error page into a useful error", async () => {
    const response = new Response("<!doctype html><title>Proxy error</title>", {
      status: 500,
      headers: { "Content-Type": "text/html" },
    });
    await expect(parseApiResponse(response)).rejects.toMatchObject({
      status: 500,
      code: "INVALID_SERVER_RESPONSE",
      message: "The server returned an invalid response. Please try again.",
    });
  });

  it("reports malformed JSON without exposing a SyntaxError", async () => {
    const response = new Response("{", { status: 200, headers: { "Content-Type": "application/json" } });
    await expect(parseApiResponse(response)).rejects.toMatchObject({
      code: "INVALID_JSON_RESPONSE",
      message: "The server returned an invalid response. Please try again.",
    });
  });
});

describe("requestJson", () => {
  afterEach(() => vi.restoreAllMocks());

  it("normalizes a network failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("connection refused")));
    await expect(requestJson("/api/health")).rejects.toEqual(expect.objectContaining({
      code: "NETWORK_ERROR",
      message: "Unable to reach the DripCut processing server.",
    }));
  });

  it("includes HttpOnly session cookies on API requests", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    await requestJson("/api/session-test");
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ credentials: "include" });
  });
});

describe("createClipJob", () => {
  afterEach(() => vi.restoreAllMocks());

  it("uses fast center crop for the standard portrait workflow", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      id: "job-1",
      source_id: "source-1",
      project_id: "project-1",
      status: "queued",
      progress: 0,
      percent: 0,
      stage: "Queued",
      elapsed: 0,
      artifacts: [],
    }));
    vi.stubGlobal("fetch", fetchMock);

    await createClipJob(
      "source-1",
      [{ id: "clip-1", index: 1, start: 0, end: 30, strategy: "standard" }],
      { outputFormat: "portrait", autoCaptions: true, platforms: ["youtube"] },
    );

    const options = fetchMock.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(String(options.body))).toMatchObject({
      portrait_mode: "center_crop",
      fast_mode: true,
      auto_captions: true,
      caption_style: "clean",
    });
  });
});

describe("fetchUsage", () => {
  afterEach(() => vi.restoreAllMocks());

  it("maps the backend plan summary into product models", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({
      plan: "free",
      plan_label: "Free",
      period_start: "2026-08-01T00:00:00+00:00",
      period_end: "2026-09-01T00:00:00+00:00",
      reset_at: "2026-09-01T00:00:00+00:00",
      metrics: [{
        key: "video_processing_minutes",
        label: "Video processing",
        used: 4,
        reserved: 1,
        limit: 10,
        unit: "minutes",
        percent: 50,
        unlimited: false,
      }],
    })));

    await expect(fetchUsage()).resolves.toMatchObject({
      plan: "free",
      planLabel: "Free",
      resetAt: "2026-09-01T00:00:00+00:00",
      metrics: [{ used: 4, reserved: 1, limit: 10 }],
    });
  });
});

describe("fetchAdminOverview", () => {
  afterEach(() => vi.restoreAllMocks());

  it("maps safe internal operations data", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({
      metrics: { total_users: 3, failed_jobs: 1 },
      users: [{ id: "user-1", email: "creator@example.test", name: "Creator", workspace_id: "workspace-1", role: "owner", created_at: "2026-08-01T00:00:00Z", last_active_at: "2026-08-29T00:00:00Z" }],
      jobs: [{ id: "job-1", title: "Render", status: "failed", stage: "Encoding", project_id: "project-1", error_code: "RENDER_FAILED", error_message: "Encode stopped", created_at: "2026-08-29T00:00:00Z", elapsed_seconds: 12.4 }],
      errors: [],
      usage: [{ metric: "video_processing_minutes", quantity: 5, unit: "minutes" }],
      generated_at: "2026-08-29T00:00:00Z",
    })));

    const overview = await fetchAdminOverview();

    expect(overview.metrics.total_users).toBe(3);
    expect(overview.users[0].workspaceId).toBe("workspace-1");
    expect(overview.jobs[0].errorCode).toBe("RENDER_FAILED");
  });
});

describe("universal content mappings", () => {
  afterEach(() => vi.restoreAllMocks());

  it("loads provider-neutral source and content records", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse([{
        id: "source-1",
        workspace_id: "workspace-1",
        owner_id: "user-1",
        project_id: "project-1",
        source_type: "ai_prompt",
        title: "Launch idea",
        text_content: "Create a launch short",
        metadata: { language: "en" },
        status: "draft",
        rights_confirmed: false,
        created_at: "2026-09-01T00:00:00Z",
        updated_at: "2026-09-01T00:00:00Z",
      }]))
      .mockResolvedValueOnce(jsonResponse([{
        id: "content-1",
        workspace_id: "workspace-1",
        owner_id: "user-1",
        project_id: "project-1",
        source_id: "source-1",
        content_type: "ai_script",
        title: "Launch short",
        hashtags: ["launch"],
        status: "review",
        metadata: {},
        created_at: "2026-09-01T00:00:00Z",
        updated_at: "2026-09-01T00:00:00Z",
      }]));
    vi.stubGlobal("fetch", fetchMock);

    const sources = await fetchProjectContentSources("project-1");
    const content = await fetchProjectContent("project-1");

    expect(sources[0]).toMatchObject({
      workspaceId: "workspace-1",
      sourceType: "ai_prompt",
      textContent: "Create a launch short",
    });
    expect(content[0]).toMatchObject({
      sourceId: "source-1",
      contentType: "ai_script",
      status: "review",
    });
  });

  it("maps provider capabilities without hard-coded page assumptions", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse([{
      platform: "youtube",
      can_upload_video: true,
      can_publish_short: true,
      can_schedule: true,
      can_publish_thumbnail: false,
      can_edit_metadata: false,
      can_fetch_analytics: false,
      supported_aspect_ratios: ["9:16", "16:9"],
      max_video_duration_seconds: null,
      supported_content_types: ["video_clip"],
    }])));

    await expect(fetchProviderCapabilities()).resolves.toEqual([{
      platform: "youtube",
      canUploadVideo: true,
      canPublishShort: true,
      canSchedule: true,
      canPublishThumbnail: false,
      canEditMetadata: false,
      canFetchAnalytics: false,
      supportedAspectRatios: ["9:16", "16:9"],
      maxVideoDurationSeconds: undefined,
      supportedContentTypes: ["video_clip"],
    }]);
  });
});
