import type {
  AiRecommendation,
  ProjectSummary,
  RenderStage,
  WorkflowDefinition,
} from "../models";

// UI-only examples live here so they cannot be confused with persisted projects
// or production service responses.
export const exampleProjects: ProjectSummary[] = [
  {
    id: "example-podcast",
    name: "The creator economy",
    kind: "Podcast",
    detail: "6 clip concepts",
    edited: "Example project",
    status: "Clips ready",
    accent: "violet",
  },
  {
    id: "example-interview",
    name: "Founder interview",
    kind: "YouTube Shorts",
    detail: "4 moments selected",
    edited: "Example project",
    status: "Draft",
    accent: "cyan",
  },
  {
    id: "example-launch",
    name: "Product launch recap",
    kind: "Instagram Reels",
    detail: "3 post concepts",
    edited: "Example project",
    status: "Scheduled",
    accent: "coral",
  },
  {
    id: "example-course",
    name: "Course highlights",
    kind: "Education",
    detail: "8 clip concepts",
    edited: "Example project",
    status: "Clips ready",
    accent: "lime",
  },
];

export const workflows: WorkflowDefinition[] = [
  {
    id: "auto-clip",
    title: "Auto Clip & Schedule",
    description: "Turn one long video into a ready-to-publish content plan.",
    category: "For You",
    route: "auto-clip",
    status: "available",
    accent: "violet",
    badge: "DripCut Magic",
  },
  {
    id: "youtube-shorts",
    title: "YouTube Shorts",
    description: "Plan clean vertical clips for Shorts.",
    category: "Short Videos",
    route: "auto-clip",
    status: "available",
    accent: "coral",
    scriptPlatform: "youtube",
  },
  {
    id: "instagram-reels",
    title: "Instagram Reels",
    description: "Plan social-first clips for Reels.",
    category: "Short Videos",
    route: "auto-clip",
    status: "available",
    accent: "cyan",
    scriptPlatform: "instagram",
  },
  {
    id: "ai-script",
    title: "AI Script",
    description: "Write, generate, and refine a ready-to-record short-form script.",
    category: "AI Tools",
    route: "script",
    status: "available",
    accent: "violet",
    badge: "New",
  },
  {
    id: "ai-editor",
    title: "AI Video Editor",
    description: "Describe an edit in plain language. Up to one minute.",
    category: "AI Tools",
    route: "ai-editor",
    status: "available",
    accent: "lime",
  },
  {
    id: "ai-thumbnail",
    title: "AI Thumbnail",
    description: "Generate thumbnail concepts from a selected video.",
    category: "AI Tools",
    route: "ai-thumbnail",
    status: "available",
    accent: "amber",
  },
  {
    id: "schedule-content",
    title: "Schedule Content",
    description: "Plan publishing dates across YouTube and Instagram.",
    category: "Scheduling",
    route: "schedule",
    status: "available",
    accent: "cyan",
  },
  {
    id: "bulk-schedule",
    title: "Bulk Schedule ZIP",
    description: "Create a posting plan from a ZIP of finished videos.",
    category: "Scheduling",
    status: "development",
    accent: "violet",
  },
  {
    id: "extract-audio",
    title: "Extract Audio",
    description: "Pull clean audio from a video file.",
    category: "Utilities",
    status: "development",
    accent: "lime",
  },
  {
    id: "video-extractor",
    title: "Video Extractor",
    description: "Prepare a downloadable video from a supported link.",
    category: "Utilities",
    status: "development",
    accent: "coral",
  },
];

export const renderStages: RenderStage[] = [
  { id: "prepare", label: "Preparing source", detail: "Checking media and clip boundaries" },
  { id: "create", label: "Creating clips", detail: "Applying the selected clip plan" },
  { id: "captions", label: "Generating captions", detail: "Formatting captions for phone screens" },
  { id: "package", label: "Preparing videos", detail: "Collecting files for download" },
];

export const createDemoRecommendations = (duration: number): AiRecommendation[] => {
  const safeDuration = Math.max(duration, 60);
  const specs = [
    [0.08, 0.17, 92, "Strong opening + clear payoff", "Strong hook"],
    [0.34, 0.44, 87, "High energy and a complete thought", "High energy"],
    [0.61, 0.71, 84, "Useful insight with sharing potential", "Useful insight"],
    [0.79, 0.89, 81, "Surprising take with a concise ending", "Fresh perspective"],
  ] as const;

  return specs.map(([startRatio, endRatio, score, reason, label], index) => ({
    id: `demo-ai-${index + 1}`,
    start: Math.round(safeDuration * startRatio),
    end: Math.min(duration, Math.round(safeDuration * endRatio)),
    score,
    reason,
    label,
  })).filter((item) => item.end > item.start);
};
