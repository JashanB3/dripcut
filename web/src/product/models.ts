export type ProductRoute =
  | "home"
  | "projects"
  | "templates"
  | "ai-editor"
  | "auto-clip"
  | "ai-thumbnail"
  | "schedule"
  | "usage"
  | "admin"
  | "settings";
export type SourceKind = "upload" | "youtube";
export type Platform = "youtube" | "instagram";
export type ClipDuration = 15 | 30 | 45 | 60 | "custom";
export type OutputFormat = "source" | "landscape" | "portrait" | "square";

export interface SourceAsset {
  id: string;
  kind: SourceKind;
  name: string;
  duration: number;
  width: number;
  height: number;
  mimeType: string;
  youtubeUrl?: string;
  thumbnailUrl?: string;
  channel?: string;
  sizeBytes?: number;
  mediaUrl: string;
  projectId?: string;
}

export interface RuntimeSource {
  id: string;
  url: string;
  file?: File;
}

export interface ApiArtifact {
  id: string;
  jobId: string;
  kind: "clip" | "zip" | "thumbnail";
  name: string;
  sizeBytes: number;
  mimeType: string;
  index?: number;
  duration?: number;
  outputFormat: OutputFormat;
  captionsEnabled: boolean;
  streamUrl?: string;
  downloadUrl: string;
}

export interface ApiJob {
  id: string;
  sourceId: string;
  projectId: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  progress: number;
  percent: number;
  stage: string;
  elapsed: number;
  error?: string;
  errorCode?: string;
  hint?: string;
  artifacts: ApiArtifact[];
  zipArtifact?: ApiArtifact;
}

export interface ClipSegment {
  id: string;
  index: number;
  start: number;
  end: number;
  duration: number;
  strategy: "standard" | "ai";
  score?: number;
  reason?: string;
}

export interface AiRecommendation {
  id: string;
  start: number;
  end: number;
  score: number;
  reason: string;
  label: string;
  hookScore?: number;
  retentionScore?: number;
  shareabilityScore?: number;
}

export interface ProjectSummary {
  id: string;
  name: string;
  kind: string;
  detail: string;
  edited: string;
  status: "Draft" | "Clips ready" | "Scheduled";
  accent: "violet" | "cyan" | "coral" | "lime";
}

export interface ApiProject {
  id: string;
  title: string;
  projectType: string;
  sourceAssetId?: string;
  thumbnailUrl?: string;
  createdAt: number;
  updatedAt: number;
  status: string;
  platform: string;
  outputFormat: OutputFormat;
  clipCount: number;
  artifactIds: string[];
  downloadArtifactId?: string;
  schedulingStatus: string;
  latestJobId?: string;
  captionsEnabled: boolean;
  workflowRoute: ProductRoute;
  source?: SourceAsset;
}

export interface WorkflowDefinition {
  id: string;
  title: string;
  description: string;
  category: "For You" | "Short Videos" | "AI Tools" | "Scheduling" | "Utilities";
  route?: ProductRoute;
  status: "available" | "development";
  accent: "violet" | "cyan" | "coral" | "lime" | "amber";
  badge?: string;
}

export interface RenderStage {
  id: string;
  label: string;
  detail: string;
}

export interface ScheduleDraft {
  platforms: Platform[];
  startDate: string;
  frequency: "6h" | "12h" | "1d" | "2d" | "custom";
  bestTime: boolean;
}

export interface AIEditPlan {
  sourceId: string;
  summary: string;
  actions: Array<{ kind: "selection" | "platform" | "trim" | "format" | "captions" | "style" | "reframe"; label: string; value: string | number | boolean }>;
  segments: ClipSegment[];
  outputFormat: OutputFormat;
  autoCaptions: boolean;
  platform: Platform;
  selection: "standard" | "viral";
  count: number;
  duration: number;
  captionStyle: "clean" | "dynamic" | "minimal" | "bold";
  reframe: "source" | "center" | "speaker" | "blur_background";
}

export interface SocialMetadataPackage {
  projectId: string;
  artifactId?: string;
  youtubeTitle: string;
  youtubeDescription: string;
  youtubeHashtags: string[];
  instagramCaption: string;
  instagramHashtags: string[];
  instagramCta: string;
  hook: string;
  category: string;
  postingDescription: string;
}

export interface ThumbnailGeneration {
  candidates: ApiArtifact[];
  brief: {
    headline: string;
    visualFocus: string;
    emotion: string;
    composition: string;
    frameGuidance: string;
    avoid: string[];
  };
  ranking: Array<{ artifactId: string; score: number; reason: string }>;
}

export interface SocialConnection {
  platform: Platform;
  label: string;
  connected: boolean;
  configured: boolean;
  detail: string;
  setupHint: string;
}

export interface SavedSchedule {
  id: string;
  projectId: string;
  archiveName: string;
  createdAt: number;
  posts: Array<{
    id: string;
    platform: Platform;
    clipName: string;
    publishAt: string;
    caption: string;
    status: string;
    externalPostId?: string;
    errorMessage?: string;
  }>;
  publishReady: boolean;
}

export interface UsageMetric {
  key: string;
  label: string;
  used: number;
  reserved: number;
  limit: number | null;
  unit: string;
  percent: number;
  unlimited: boolean;
}

export interface UsageSummary {
  plan: string;
  planLabel: string;
  periodStart: string;
  periodEnd: string;
  resetAt: string;
  metrics: UsageMetric[];
}

export interface AdminOverview {
  metrics: Record<string, number>;
  users: Array<{
    id: string;
    email: string;
    name: string;
    workspaceId: string;
    role: string;
    createdAt: string;
    lastActiveAt: string;
  }>;
  jobs: Array<{
    id: string;
    title: string;
    status: string;
    stage: string;
    projectId: string;
    errorCode: string;
    errorMessage: string;
    createdAt: string;
    elapsedSeconds: number;
  }>;
  errors: AdminOverview["jobs"];
  usage: Array<{ metric: string; quantity: number; unit: string }>;
  generatedAt: string;
}
