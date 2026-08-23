import type {
  ApiArtifact,
  ApiJob,
  ApiProject,
  AIEditPlan,
  OutputFormat,
  Platform,
  SavedSchedule,
  SocialConnection,
  SourceAsset,
} from "../models";

interface SourcePayload {
  id: string;
  kind: "upload" | "youtube";
  name: string;
  title: string;
  duration: number;
  width: number;
  height: number;
  mime_type: string;
  size_bytes: number;
  channel?: string;
  youtube_url?: string;
  media_url: string;
  poster_url?: string;
  project_id?: string;
}

interface ArtifactPayload {
  id: string;
  job_id: string;
  kind: "clip" | "zip" | "thumbnail";
  name: string;
  size_bytes: number;
  mime_type: string;
  index?: number;
  duration?: number;
  output_format?: OutputFormat;
  captions_enabled?: boolean;
  stream_url?: string;
  download_url: string;
}

interface JobPayload {
  id: string;
  source_id: string;
  project_id?: string;
  status: ApiJob["status"];
  progress: number;
  percent: number;
  stage: string;
  elapsed: number;
  error?: string;
  error_code?: string;
  hint?: string;
  artifacts: ArtifactPayload[];
  zip_artifact?: ArtifactPayload;
}

interface ProjectPayload {
  id: string;
  title: string;
  project_type: string;
  source_asset_id?: string;
  thumbnail_url?: string;
  created_at: number;
  updated_at: number;
  status: string;
  platform: string;
  output_format: OutputFormat;
  clip_count: number;
  artifact_ids: string[];
  download_artifact_id?: string;
  scheduling_status: string;
  latest_job_id?: string;
  captions_enabled: boolean;
  workflow_route: ApiProject["workflowRoute"];
  source?: SourcePayload;
}

export class ApiError extends Error {
  hint?: string;
  code?: string;

  constructor(message: string, hint?: string, code?: string) {
    super(message);
    this.name = "ApiError";
    this.hint = hint;
    this.code = code;
  }
}

const errorFromResponse = async (response: Response) => {
  try {
    const payload = await response.json() as { message?: string; detail?: string; hint?: string; code?: string };
    return new ApiError(payload.message || payload.detail || "DripCut could not complete that request.", payload.hint, payload.code);
  } catch {
    return new ApiError(`DripCut API returned ${response.status}.`, "Make sure the Python API is running on port 8000.");
  }
};

const sourceFromPayload = (payload: SourcePayload): SourceAsset => ({
  id: payload.id,
  kind: payload.kind,
  name: payload.title || payload.name,
  duration: payload.duration,
  width: payload.width,
  height: payload.height,
  mimeType: payload.mime_type,
  sizeBytes: payload.size_bytes,
  youtubeUrl: payload.youtube_url,
  thumbnailUrl: payload.poster_url,
  channel: payload.channel,
  mediaUrl: payload.media_url,
  projectId: payload.project_id,
});

const artifactFromPayload = (payload: ArtifactPayload): ApiArtifact => ({
  id: payload.id,
  jobId: payload.job_id,
  kind: payload.kind,
  name: payload.name,
  sizeBytes: payload.size_bytes,
  mimeType: payload.mime_type,
  index: payload.index,
  duration: payload.duration,
  outputFormat: payload.output_format ?? "source",
  captionsEnabled: payload.captions_enabled ?? false,
  streamUrl: payload.stream_url,
  downloadUrl: payload.download_url,
});

const jobFromPayload = (payload: JobPayload): ApiJob => ({
  id: payload.id,
  sourceId: payload.source_id,
  projectId: payload.project_id ?? "",
  status: payload.status,
  progress: payload.progress,
  percent: payload.percent,
  stage: payload.stage,
  elapsed: payload.elapsed,
  error: payload.error,
  errorCode: payload.error_code,
  hint: payload.hint,
  artifacts: payload.artifacts.map(artifactFromPayload),
  zipArtifact: payload.zip_artifact ? artifactFromPayload(payload.zip_artifact) : undefined,
});

export async function uploadSource(file: File, onProgress?: (percent: number) => void): Promise<SourceAsset> {
  return await new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", "/api/sources/upload");
    request.responseType = "json";
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(Math.round((event.loaded / event.total) * 100));
    };
    request.onerror = () => reject(new ApiError("The upload could not reach DripCut.", "Start the Python API and try again."));
    request.onload = () => {
      if (request.status >= 200 && request.status < 300) {
        resolve(sourceFromPayload(request.response as SourcePayload));
      } else {
        const payload = request.response as { message?: string; detail?: string; hint?: string } | null;
        reject(new ApiError(payload?.message || payload?.detail || "DripCut could not import this video.", payload?.hint));
      }
    };
    const body = new FormData();
    body.append("video", file);
    request.send(body);
  });
}

export async function importYouTube(
  url: string,
  rightsConfirmed: boolean,
  onProgress?: (percent: number, stage: string) => void,
): Promise<SourceAsset> {
  const response = await fetch("/api/jobs/youtube", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, rights_confirmed: rightsConfirmed }),
  });
  if (!response.ok) throw await errorFromResponse(response);
  let job = jobFromPayload(await response.json() as JobPayload);
  onProgress?.(job.percent, job.stage);
  while (job.status === "queued" || job.status === "running") {
    await new Promise((resolve) => window.setTimeout(resolve, 500));
    job = await getClipJob(job.id);
    onProgress?.(job.percent, job.stage);
  }
  if (job.status !== "succeeded" || !job.sourceId) {
    throw new ApiError(
      job.error || "YouTube import failed.",
      job.hint,
      job.errorCode,
    );
  }
  const source = await fetch(`/api/sources/${encodeURIComponent(job.sourceId)}`, { cache: "no-store" });
  if (!source.ok) throw await errorFromResponse(source);
  return sourceFromPayload(await source.json() as SourcePayload);
}

export async function createClipJob(
  sourceId: string,
  segments: Array<{ id: string; index: number; start: number; end: number; strategy: "standard" | "ai" }>,
  options: {
    outputFormat: OutputFormat;
    autoCaptions: boolean;
    platforms: Platform[];
  },
): Promise<ApiJob> {
  const response = await fetch("/api/jobs/clips", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_id: sourceId,
      segments,
      output_format: options.outputFormat,
      portrait_mode: "ai_tracking",
      auto_captions: options.autoCaptions,
      platforms: options.platforms,
      fast_mode: true,
    }),
  });
  if (!response.ok) throw await errorFromResponse(response);
  return jobFromPayload(await response.json() as JobPayload);
}

const projectFromPayload = (payload: ProjectPayload): ApiProject => ({
  id: payload.id,
  title: payload.title,
  projectType: payload.project_type,
  sourceAssetId: payload.source_asset_id,
  thumbnailUrl: payload.thumbnail_url,
  createdAt: payload.created_at,
  updatedAt: payload.updated_at,
  status: payload.status,
  platform: payload.platform,
  outputFormat: payload.output_format,
  clipCount: payload.clip_count,
  artifactIds: payload.artifact_ids,
  downloadArtifactId: payload.download_artifact_id,
  schedulingStatus: payload.scheduling_status,
  latestJobId: payload.latest_job_id,
  captionsEnabled: payload.captions_enabled,
  workflowRoute: payload.workflow_route,
  source: payload.source ? sourceFromPayload(payload.source) : undefined,
});

export async function fetchProjects(limit = 20): Promise<ApiProject[]> {
  const response = await fetch(`/api/projects?limit=${limit}`, { cache: "no-store" });
  if (!response.ok) throw await errorFromResponse(response);
  return (await response.json() as ProjectPayload[]).map(projectFromPayload);
}

export async function getProject(projectId: string): Promise<ApiProject> {
  const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}`, {
    cache: "no-store",
  });
  if (!response.ok) throw await errorFromResponse(response);
  return projectFromPayload(await response.json() as ProjectPayload);
}

export async function createThumbnailCandidates(
  projectId: string,
  prompt: string,
  target: Platform,
): Promise<ApiArtifact[]> {
  const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/thumbnails`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt, target }),
  });
  if (!response.ok) throw await errorFromResponse(response);
  return (await response.json() as ArtifactPayload[]).map(artifactFromPayload);
}

export async function createAIEditPlan(sourceId: string, prompt: string): Promise<AIEditPlan> {
  const response = await fetch("/api/ai/edit-plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_id: sourceId, prompt }),
  });
  if (!response.ok) throw await errorFromResponse(response);
  const payload = await response.json() as {
    source_id: string;
    summary: string;
    actions: AIEditPlan["actions"];
    segments: Array<{ id: string; index: number; start: number; end: number; strategy: "standard" | "ai" }>;
    output_format: OutputFormat;
    auto_captions: boolean;
  };
  return {
    sourceId: payload.source_id,
    summary: payload.summary,
    actions: payload.actions,
    segments: payload.segments.map((segment) => ({ ...segment, duration: segment.end - segment.start })),
    outputFormat: payload.output_format,
    autoCaptions: payload.auto_captions,
  };
}

export async function fetchSocialConnections(): Promise<SocialConnection[]> {
  const response = await fetch("/api/social/connections", { cache: "no-store" });
  if (!response.ok) throw await errorFromResponse(response);
  const payload = await response.json() as Array<{
    platform: Platform; label: string; connected: boolean; configured: boolean; detail: string; setup_hint: string;
  }>;
  return payload.map((item) => ({ ...item, setupHint: item.setup_hint }));
}

export async function saveSchedule(input: {
  projectId: string;
  platforms: Platform[];
  intervalMinutes: number;
  startAt: string;
  caption: string;
}): Promise<SavedSchedule> {
  const response = await fetch("/api/schedules", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project_id: input.projectId,
      platforms: input.platforms,
      interval_minutes: input.intervalMinutes,
      start_at: input.startAt,
      caption: input.caption,
    }),
  });
  if (!response.ok) throw await errorFromResponse(response);
  const payload = await response.json() as {
    id: string; project_id: string; archive_name: string; created_at: number;
    posts: Array<{ platform: Platform; clip_name: string; publish_at: string; caption: string; status: string }>;
    publish_ready: boolean;
  };
  return {
    id: payload.id,
    projectId: payload.project_id,
    archiveName: payload.archive_name,
    createdAt: payload.created_at,
    posts: payload.posts.map((post) => ({
      platform: post.platform,
      clipName: post.clip_name,
      publishAt: post.publish_at,
      caption: post.caption,
      status: post.status,
    })),
    publishReady: payload.publish_ready,
  };
}

export async function getClipJob(jobId: string): Promise<ApiJob> {
  const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, { cache: "no-store" });
  if (!response.ok) throw await errorFromResponse(response);
  return jobFromPayload(await response.json() as JobPayload);
}
