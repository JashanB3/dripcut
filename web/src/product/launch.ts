import type { ProductRoute } from "./models";

// Public build flags control discoverability, not authorization.
// Enable publishing only after a controlled OAuth/upload verification.
export const youtubePublishingBeta = true;
export const experimentalTools = import.meta.env.VITE_EXPERIMENTAL_TOOLS === "true";

export function isLaunchRoute(route: ProductRoute | null | undefined): boolean {
  if (!route) return false;
  if (route === "schedule") return youtubePublishingBeta;
  if (["script", "ai-editor", "ai-thumbnail"].includes(route)) return experimentalTools;
  return true;
}
