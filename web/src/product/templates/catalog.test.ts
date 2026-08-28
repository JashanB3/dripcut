import { describe, expect, it } from "vitest";

import { clipTemplates } from "./catalog";

describe("clip template catalog", () => {
  it("contains original complete presets for every launch category", () => {
    const categories = new Set(clipTemplates.map((template) => template.category));
    expect(categories).toEqual(new Set(["Podcast", "Talking Head", "Education", "Business", "Gaming", "Motivation", "Story", "Product", "News", "Minimal"]));
    expect(new Set(clipTemplates.map((template) => template.id)).size).toBe(clipTemplates.length);
    expect(clipTemplates.every((template) => template.safeZones.bottom > 0 && template.platforms.length > 0)).toBe(true);
  });
});
