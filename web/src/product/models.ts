export type ProductRoute =
  | "home"
  | "projects"
  | "templates"
  | "ai-editor"
  | "auto-clip"
  | "ai-thumbnail"
  | "script"
  | "schedule"
  | "usage"
  | "admin"
  | "settings";
export type SourceKind = "upload" | "youtube";
export type Platform = "youtube" | "instagram";
export type ContentSourceType = "video_upload" | "youtube_url" | "script" | "ai_script" | "ai_prompt";
export type ContentType = "video_clip" | "script" | "ai_script" | "ai_video";
export type ContentStatus = "draft" | "generating" | "review" | "ready" | "scheduled" | "partially_published" | "published" | "failed" | "archived";
export type TargetPlatform = Platform | "facebook" | "tiktok" | "bilibili" | "linkedin";
export type PlatformTargetStatus = "draft" | "ready" | "scheduled" | "queued" | "uploading" | "processing" | "published" | "failed" | "cancelled";
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
  retryable: boolean;
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

export interface ContentSource {
  id: string;
  workspaceId: string;
  ownerId: string;
  projectId: string;
  sourceType: ContentSourceType;
  title: string;
  textContent?: string;
  sourceAssetId?: string;
  externalUrl?: string;
  metadata: Record<string, unknown>;
  status: "draft" | "importing" | "ready" | "failed";
  rightsConfirmed: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface ContentItem {
  id: string;
  workspaceId: string;
  ownerId: string;
  projectId: string;
  sourceId?: string;
  contentType: ContentType;
  title: string;
  script?: string;
  hook?: string;
  body?: string;
  description?: string;
  caption?: string;
  hashtags: string[];
  thumbnailArtifactId?: string;
  videoArtifactId?: string;
  audioArtifactId?: string;
  durationSeconds?: number;
  aspectRatio?: string;
  language?: string;
  status: ContentStatus;
  metadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface ScriptBrief {
  topic: string;
  platform: Platform;
  audience: string;
  tone: string;
  language: string;
  targetDurationSeconds: number;
  contentGoal: string;
  cta: string;
  referenceText: string;
}

export type ScriptAction =
  | "rewrite_hook"
  | "generate_hooks"
  | "shorten"
  | "expand"
  | "conversational"
  | "educational"
  | "engaging"
  | "rewrite_cta"
  | "adapt_youtube"
  | "adapt_instagram";

export interface ScriptWorkspace {
  source: ContentSource;
  item: ContentItem;
  alternateHooks: string[];
}

export interface PlatformTarget {
  id: string;
  workspaceId: string;
  ownerId: string;
  contentItemId: string;
  platform: TargetPlatform;
  socialConnectionId?: string;
  scheduledAt?: string;
  sourceTimezone?: string;
  publishStatus: PlatformTargetStatus;
  providerPostId?: string;
  providerMetadata: Record<string, unknown>;
  idempotencyKey?: string;
  attemptCount: number;
  lastErrorCode?: string;
  lastErrorMessage?: string;
  publishedAt?: string;
  createdAt: string;
  updatedAt: string;
}

export interface ProviderCapabilities {
  platform: Platform;
  canUploadVideo: boolean;
  canPublishShort: boolean;
  canSchedule: boolean;
  canPublishThumbnail: boolean;
  canEditMetadata: boolean;
  canFetchAnalytics: boolean;
  supportedAspectRatios: string[];
  maxVideoDurationSeconds?: number;
  supportedContentTypes: ContentType[];
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
  scriptPlatform?: Platform;
}

export interface RenderStage {
  id: string;
  label: string;
  detail: string;
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
