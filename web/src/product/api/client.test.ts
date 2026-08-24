import { afterEach, describe, expect, it, vi } from "vitest";

import { createClipJob, parseApiResponse, requestJson } from "./client";

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
    });
  });
});
