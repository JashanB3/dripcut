import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import { CustomerError } from "./CustomerError";

describe("customer error boundary", () => {
  it("keeps unexpected implementation errors out of customer messages", () => {
    const html = renderToStaticMarkup(<CustomerError error={new Error("/private/media/internal.mp4 decoder stack")} fallback="Please try again." />);
    expect(html).toContain("Please try again.");
    expect(html).not.toContain("/private/media");
    expect(html).not.toContain("decoder stack");
  });
  it("preserves normalized API messages and their support reference", () => {
    const error = new ApiError("We couldn’t import this video.");
    error.requestId = "request-qa-123";
    const html = renderToStaticMarkup(<CustomerError error={error} />);
    expect(html).toContain("request-qa-123");
    expect(html).toContain("import this video");
  });
});
