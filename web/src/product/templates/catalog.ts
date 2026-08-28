import type { OutputFormat, Platform } from "../models";

export type TemplateCategory = "Podcast" | "Talking Head" | "Education" | "Business" | "Gaming" | "Motivation" | "Story" | "Product" | "News" | "Minimal";
export type TemplateAccent = "violet" | "cyan" | "coral" | "lime" | "amber";

export interface ClipTemplate {
  id: string;
  name: string;
  category: TemplateCategory;
  tagline: string;
  duration: 15 | 30 | 45 | 60;
  aspectRatio: OutputFormat;
  captionStyle: "clean" | "dynamic" | "minimal" | "bold";
  safeZones: { top: number; right: number; bottom: number; left: number };
  textPlacement: "top" | "center" | "bottom";
  transitions: "clean-cut" | "soft-push" | "energy-cut" | "none";
  brandingOptions: { logo: boolean; accentColor: boolean; endCard: boolean };
  platforms: Platform[];
  accent: TemplateAccent;
  headline: [string, string];
}

export const clipTemplates: ClipTemplate[] = [
  { id: "podcast-pulse", name: "Podcast pulse", category: "Podcast", tagline: "Speaker-first cuts with room for captions.", duration: 45, aspectRatio: "portrait", captionStyle: "dynamic", safeZones: { top: 12, right: 8, bottom: 22, left: 8 }, textPlacement: "bottom", transitions: "soft-push", brandingOptions: { logo: true, accentColor: true, endCard: true }, platforms: ["youtube", "instagram"], accent: "violet", headline: ["SAY IT", "CLEAR"] },
  { id: "face-forward", name: "Face forward", category: "Talking Head", tagline: "A focused vertical frame for direct-to-camera ideas.", duration: 30, aspectRatio: "portrait", captionStyle: "clean", safeZones: { top: 10, right: 8, bottom: 20, left: 8 }, textPlacement: "bottom", transitions: "clean-cut", brandingOptions: { logo: true, accentColor: true, endCard: false }, platforms: ["instagram", "youtube"], accent: "cyan", headline: ["KEEP IT", "HUMAN"] },
  { id: "big-idea", name: "Big idea", category: "Education", tagline: "One lesson, one payoff, no clutter.", duration: 30, aspectRatio: "portrait", captionStyle: "bold", safeZones: { top: 16, right: 7, bottom: 18, left: 7 }, textPlacement: "center", transitions: "clean-cut", brandingOptions: { logo: false, accentColor: true, endCard: true }, platforms: ["youtube", "instagram"], accent: "lime", headline: ["LEARN IT", "FAST"] },
  { id: "clear-brief", name: "Clear brief", category: "Business", tagline: "Polished insight clips for professional feeds.", duration: 60, aspectRatio: "portrait", captionStyle: "minimal", safeZones: { top: 12, right: 9, bottom: 18, left: 9 }, textPlacement: "bottom", transitions: "none", brandingOptions: { logo: true, accentColor: true, endCard: true }, platforms: ["youtube", "instagram"], accent: "amber", headline: ["MAKE IT", "USEFUL"] },
  { id: "game-winner", name: "Game winner", category: "Gaming", tagline: "Fast reactions and high-energy moments.", duration: 30, aspectRatio: "portrait", captionStyle: "bold", safeZones: { top: 10, right: 6, bottom: 24, left: 6 }, textPlacement: "top", transitions: "energy-cut", brandingOptions: { logo: true, accentColor: true, endCard: false }, platforms: ["youtube", "instagram"], accent: "coral", headline: ["PLAY", "LOUD"] },
  { id: "daily-momentum", name: "Daily momentum", category: "Motivation", tagline: "Short statements with an intentional finish.", duration: 30, aspectRatio: "portrait", captionStyle: "dynamic", safeZones: { top: 14, right: 8, bottom: 20, left: 8 }, textPlacement: "center", transitions: "soft-push", brandingOptions: { logo: false, accentColor: true, endCard: true }, platforms: ["instagram", "youtube"], accent: "violet", headline: ["START", "NOW"] },
  { id: "story-beat", name: "Story beat", category: "Story", tagline: "A compact setup, turn, and payoff.", duration: 60, aspectRatio: "portrait", captionStyle: "clean", safeZones: { top: 11, right: 8, bottom: 20, left: 8 }, textPlacement: "bottom", transitions: "soft-push", brandingOptions: { logo: true, accentColor: true, endCard: true }, platforms: ["instagram", "youtube"], accent: "cyan", headline: ["WAIT FOR", "THE TURN"] },
  { id: "launch-energy", name: "Launch energy", category: "Product", tagline: "Product proof in a sharp fifteen seconds.", duration: 15, aspectRatio: "portrait", captionStyle: "bold", safeZones: { top: 12, right: 7, bottom: 18, left: 7 }, textPlacement: "top", transitions: "energy-cut", brandingOptions: { logo: true, accentColor: true, endCard: true }, platforms: ["instagram", "youtube"], accent: "coral", headline: ["SEE IT", "WORK"] },
  { id: "news-desk", name: "News desk", category: "News", tagline: "Readable context with a steady visual rhythm.", duration: 45, aspectRatio: "portrait", captionStyle: "clean", safeZones: { top: 14, right: 8, bottom: 19, left: 8 }, textPlacement: "bottom", transitions: "clean-cut", brandingOptions: { logo: true, accentColor: true, endCard: false }, platforms: ["youtube", "instagram"], accent: "amber", headline: ["WHAT", "CHANGED"] },
  { id: "quiet-cut", name: "Quiet cut", category: "Minimal", tagline: "Low-noise captions and confident spacing.", duration: 30, aspectRatio: "square", captionStyle: "minimal", safeZones: { top: 12, right: 10, bottom: 16, left: 10 }, textPlacement: "bottom", transitions: "none", brandingOptions: { logo: false, accentColor: false, endCard: false }, platforms: ["instagram"], accent: "lime", headline: ["LESS", "BUT BETTER"] },
];

export const findClipTemplate = (id: string | null): ClipTemplate | undefined =>
  clipTemplates.find((template) => template.id === id);
