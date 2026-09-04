import type { Platform, ScriptBrief } from "../models";

export const SCRIPT_PLATFORM_KEY = "dripcut.script.platform";
export const LAST_SCRIPT_KEY = "dripcut.script.last-item";

export function initialScriptBrief(platform: Platform = "youtube"): ScriptBrief {
  return {
    topic: "",
    platform,
    audience: "Creators and curious learners",
    tone: "Conversational",
    language: "en",
    targetDurationSeconds: 45,
    contentGoal: "Teach one useful idea",
    cta: "Save this for later",
    referenceText: "",
  };
}

export function countScriptWords(script: string): number {
  const normalized = script.trim();
  return normalized ? normalized.split(/\s+/).length : 0;
}

export function estimateScriptDuration(script: string): number {
  const words = countScriptWords(script);
  return words ? Math.max(1, Math.round(words / 2.5)) : 0;
}

export function scriptSnapshot(title: string, hook: string, script: string): string {
  return JSON.stringify([title.trim(), hook.trim(), script.trim()]);
}
