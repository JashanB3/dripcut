export type ProductRoute =
  | "home"
  | "projects"
  | "templates"
  | "ai-editor"
  | "auto-clip"
  | "ai-thumbnail"
  | "schedule"
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
  actions: Array<{ kind: "trim" | "format" | "captions"; label: string; value: string | number | boolean }>;
  segments: ClipSegment[];
  outputFormat: OutputFormat;
  autoCaptions: boolean;
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
  posts: Array<{ platform: Platform; clipName: string; publishAt: string; caption: string; status: string }>;
  publishReady: boolean;
}
