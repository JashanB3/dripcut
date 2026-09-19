import { describe, expect, it } from "vitest";

import type { SourceAsset } from "../models";
import { clipTemplates } from "../templates/catalog";
import { autoClipReducer, initialAutoClipState, maximumClipCount, selectedSegments } from "./autoClipReducer";

const source: SourceAsset = {
  id: "source-1",
  kind: "upload",
  name: "lesson.mp4",
  duration: 600,
  width: 1920,
  height: 1080,
  mimeType: "video/mp4",
  mediaUrl: "/api/sources/source-1/media",
};

describe("autoClipReducer", () => {
  it("creates sequential clips without requiring AI", () => {
    let state = autoClipReducer(initialAutoClipState, { type: "source-loaded", source });
    state = autoClipReducer(state, { type: "set-duration", value: 60 });
    state = autoClipReducer(state, { type: "set-count", value: 5 });

    expect(maximumClipCount(state)).toBe(10);
    expect(selectedSegments(state)).toHaveLength(5);
    expect(selectedSegments(state)[4]).toMatchObject({ start: 240, end: 300, strategy: "standard" });
    expect(state.aiEnabled).toBe(false);
  });

  it("applies a template before the source without losing its defaults", () => {
    const template = clipTemplates.find((item) => item.id === "quiet-cut")!;
    let state = autoClipReducer(initialAutoClipState, { type: "apply-template", template });
    state = autoClipReducer(state, { type: "source-loaded", source });

    expect(state.templateId).toBe("quiet-cut");
    expect(state.outputFormat).toBe("square");
    expect(state.durationChoice).toBe(30);
    expect(state.platforms).toEqual(["instagram"]);
    expect(state.captionStyle).toBe("minimal");
  });

  it("selects the first valid clip when a shorter duration becomes available", () => {
    const shortSource = { ...source, duration: 18 };
    let state = autoClipReducer(initialAutoClipState, { type: "source-loaded", source: shortSource });

    expect(state.count).toBe(1);
    state = autoClipReducer(state, { type: "set-duration", value: 15 });
    expect(state.count).toBe(2);
    expect(selectedSegments(state)[1]).toMatchObject({ start: 15, end: 18 });
  });
});
