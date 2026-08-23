import type {
  AiRecommendation,
  ClipDuration,
  ClipSegment,
  Platform,
  OutputFormat,
  SourceAsset,
} from "../models";

export type AutoClipPhase = "source" | "configure" | "render-preview" | "results";

export interface AutoClipState {
  phase: AutoClipPhase;
  source: SourceAsset | null;
  durationChoice: ClipDuration;
  customDuration: number;
  count: number;
  platforms: Platform[];
  outputFormat: OutputFormat;
  autoCaptions: boolean;
  aiEnabled: boolean;
  recommendations: AiRecommendation[];
  acceptedRecommendationIds: string[];
  ignoredRecommendationIds: string[];
  currentTime: number;
  playing: boolean;
  renderStage: number;
}

export type AutoClipAction =
  | { type: "source-loaded"; source: SourceAsset; recommendations: AiRecommendation[] }
  | { type: "set-duration"; value: ClipDuration }
  | { type: "set-custom-duration"; value: number }
  | { type: "set-count"; value: number }
  | { type: "use-max" }
  | { type: "toggle-platform"; platform: Platform }
  | { type: "set-output-format"; value: OutputFormat }
  | { type: "toggle-captions" }
  | { type: "toggle-ai" }
  | { type: "accept-recommendation"; id: string }
  | { type: "ignore-recommendation"; id: string }
  | { type: "set-current-time"; value: number }
  | { type: "set-playing"; value: boolean }
  | { type: "preview-render" }
  | { type: "set-render-stage"; value: number }
  | { type: "show-results" }
  | { type: "back-to-configure" }
  | { type: "reset" };

export const initialAutoClipState: AutoClipState = {
  phase: "source",
  source: null,
  durationChoice: 30,
  customDuration: 30,
  count: 1,
  platforms: ["youtube", "instagram"],
  outputFormat: "portrait",
  autoCaptions: true,
  aiEnabled: false,
  recommendations: [],
  acceptedRecommendationIds: [],
  ignoredRecommendationIds: [],
  currentTime: 0,
  playing: false,
  renderStage: 0,
};

export const selectedDuration = (state: AutoClipState): number =>
  state.durationChoice === "custom" ? state.customDuration : state.durationChoice;

export const maximumClipCount = (state: AutoClipState): number => {
  if (!state.source) return 0;
  return Math.max(0, Math.floor(state.source.duration / Math.max(selectedDuration(state), 1)));
};

export const selectedSegments = (state: AutoClipState): ClipSegment[] => {
  if (!state.source) return [];
  const accepted = state.recommendations.filter((item) =>
    state.acceptedRecommendationIds.includes(item.id),
  );
  if (state.aiEnabled && accepted.length > 0) {
    return accepted.map((item, index) => ({
      id: `ai-segment-${item.id}`,
      index: index + 1,
      start: item.start,
      end: item.end,
      duration: item.end - item.start,
      strategy: "ai",
      score: item.score,
      reason: item.reason,
    }));
  }

  const duration = selectedDuration(state);
  return Array.from({ length: Math.min(state.count, maximumClipCount(state)) }, (_, index) => {
    const start = index * duration;
    const end = Math.min(state.source!.duration, start + duration);
    return {
      id: `standard-segment-${index + 1}`,
      index: index + 1,
      start,
      end,
      duration: end - start,
      strategy: "standard" as const,
    };
  });
};

const clampCount = (state: AutoClipState, value: number): number =>
  Math.max(0, Math.min(Math.round(value), maximumClipCount(state)));

export function autoClipReducer(state: AutoClipState, action: AutoClipAction): AutoClipState {
  switch (action.type) {
    case "source-loaded":
      return {
        ...initialAutoClipState,
        phase: "configure",
        source: action.source,
        recommendations: action.recommendations,
        count: Math.min(5, Math.max(0, Math.floor(action.source.duration / 30))),
      };
    case "set-duration": {
      const next = { ...state, durationChoice: action.value };
      return { ...next, count: clampCount(next, next.count) };
    }
    case "set-custom-duration": {
      const next = { ...state, customDuration: Math.max(5, Math.min(300, action.value)) };
      return { ...next, count: clampCount(next, next.count) };
    }
    case "set-count":
      return { ...state, count: clampCount(state, action.value) };
    case "use-max":
      return { ...state, count: maximumClipCount(state) };
    case "toggle-platform": {
      const included = state.platforms.includes(action.platform);
      const platforms = included
        ? state.platforms.filter((item) => item !== action.platform)
        : [...state.platforms, action.platform];
      return { ...state, platforms: platforms.length ? platforms : state.platforms };
    }
    case "set-output-format":
      return { ...state, outputFormat: action.value };
    case "toggle-captions":
      return { ...state, autoCaptions: !state.autoCaptions };
    case "toggle-ai":
      return {
        ...state,
        aiEnabled: !state.aiEnabled,
        acceptedRecommendationIds: [],
        ignoredRecommendationIds: [],
      };
    case "accept-recommendation":
      return {
        ...state,
        acceptedRecommendationIds: [...state.acceptedRecommendationIds, action.id],
        ignoredRecommendationIds: state.ignoredRecommendationIds.filter((id) => id !== action.id),
      };
    case "ignore-recommendation":
      return {
        ...state,
        ignoredRecommendationIds: [...state.ignoredRecommendationIds, action.id],
        acceptedRecommendationIds: state.acceptedRecommendationIds.filter((id) => id !== action.id),
      };
    case "set-current-time":
      return { ...state, currentTime: action.value };
    case "set-playing":
      return { ...state, playing: action.value };
    case "preview-render":
      return { ...state, phase: "render-preview", renderStage: 0, playing: false };
    case "set-render-stage":
      return { ...state, renderStage: action.value };
    case "show-results":
      return { ...state, phase: "results" };
    case "back-to-configure":
      return { ...state, phase: "configure", renderStage: 0 };
    case "reset":
      return initialAutoClipState;
  }
}
