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
  status?: number;
  details?: unknown;

  constructor(message: string, hint?: string, code?: string, status?: number, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.hint = hint;
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

interface ErrorPayload {
  message?: string;
  detail?: string;
  hint?: string;
  code?: string;
  request_id?: string;
  error?: ErrorPayload;
}

const configuredApiBase = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim().replace(/\/$/, "");

export function apiUrl(path: string): string {
  if (configuredApiBase) return `${configuredApiBase}${path}`;
  if (import.meta.env.DEV || typeof window === "undefined") return path;
  throw new ApiError(
    "The DripCut processing server is not configured.",
    "Set VITE_API_BASE_URL to the public backend URL before building the frontend.",
    "API_BASE_URL_MISSING",
  );
}

const resolveApiUrl = (value?: string): string | undefined => {
  if (!value || !value.startsWith("/api/")) return value;
  return apiUrl(value);
};

function normalizeApiError(status: number, data: unknown): ApiError {
  if (typeof data === "object" && data !== null) {
    const outer = data as ErrorPayload;
    const payload = outer.error ?? outer;
    const requestHint = payload.request_id ? `Request ID: ${payload.request_id}` : undefined;
    return new ApiError(
      payload.message || payload.detail || `DripCut API returned ${status}.`,
      payload.hint || requestHint,
      payload.code,
      status,
      data,
    );
  }
  if (typeof data === "string" && data.trim()) {
    const isHtml = /<\s*!doctype|<\s*html/i.test(data);
    return new ApiError(
      isHtml ? "The server returned an invalid response. Please try again." : data.trim(),
      undefined,
      isHtml ? "INVALID_SERVER_RESPONSE" : undefined,
      status,
      data,
    );
  }
  return new ApiError(
    "The server returned an empty response.",
    "Please try again. If this continues, restart the DripCut processing server.",
    "EMPTY_SERVER_RESPONSE",
    status,
  );
}

export async function parseApiResponse(response: Response): Promise<unknown | null> {
  const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";
  const text = await response.text();
  let data: unknown = null;

  if (text && contentType.includes("application/json")) {
    try {
      data = JSON.parse(text) as unknown;
    } catch {
      throw new ApiError(
        "The server returned an invalid response. Please try again.",
        undefined,
        "INVALID_JSON_RESPONSE",
        response.status,
        import.meta.env.DEV ? text : undefined,
      );
    }
  } else if (text) {
    data = text;
  }

  if (!response.ok) throw normalizeApiError(response.status, data);
  if (response.status === 204) return null;
  if (!text) {
    throw new ApiError(
      "The server returned an empty response.",
      "Please try again. If this continues, restart the DripCut processing server.",
      "EMPTY_SERVER_RESPONSE",
      response.status,
    );
  }
  if (!contentType.includes("application/json")) {
    throw new ApiError(
      "The server returned an invalid response. Please try again.",
      undefined,
      "UNEXPECTED_CONTENT_TYPE",
      response.status,
      import.meta.env.DEV ? data : undefined,
    );
  }
  return data;
}

export async function requestJson<T>(path: string, init: RequestInit = {}, timeoutMs = 15_000): Promise<T> {
  const method = init.method ?? "GET";
  const startedAt = performance.now();
  const controller = new AbortController();
  const timeout = globalThis.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(apiUrl(path), { ...init, signal: controller.signal });
    if (import.meta.env.DEV) {
      console.debug("[DripCut API]", {
        method,
        endpoint: path.split("?")[0],
        status: response.status,
        contentType: response.headers.get("content-type") ?? "",
        durationMs: Math.round(performance.now() - startedAt),
      });
    }
    return await parseApiResponse(response) as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError(
        "The DripCut processing server took too long to respond.",
        "The render may still be running. DripCut will retry automatically.",
        "REQUEST_TIMEOUT",
      );
    }
    throw new ApiError(
      "Unable to reach the DripCut processing server.",
      "Check that the backend is running and try again.",
      "NETWORK_ERROR",
      undefined,
      import.meta.env.DEV ? error : undefined,
    );
  } finally {
    globalThis.clearTimeout(timeout);
  }
}

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
  thumbnailUrl: resolveApiUrl(payload.poster_url),
  channel: payload.channel,
  mediaUrl: resolveApiUrl(payload.media_url) ?? payload.media_url,
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
  streamUrl: resolveApiUrl(payload.stream_url),
  downloadUrl: resolveApiUrl(payload.download_url) ?? payload.download_url,
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
    try {
      request.open("POST", apiUrl("/api/sources/upload"));
    } catch (error) {
      reject(error);
      return;
    }
    request.responseType = "text";
    request.timeout = 120_000;
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(Math.round((event.loaded / event.total) * 100));
    };
    request.onerror = () => reject(new ApiError("Unable to reach the DripCut processing server.", "Check that the backend is running and try again.", "NETWORK_ERROR"));
    request.ontimeout = () => reject(new ApiError("The video upload took too long.", "Try a smaller file or check the connection to the processing server.", "REQUEST_TIMEOUT"));
    request.onload = () => {
      let payload: SourcePayload | ErrorPayload | null = null;
      if (request.responseText) {
        try {
          payload = JSON.parse(request.responseText) as SourcePayload | ErrorPayload;
        } catch {
          reject(new ApiError("The server returned an invalid response. Please try again.", undefined, "INVALID_JSON_RESPONSE", request.status));
          return;
        }
      }
      if (request.status >= 200 && request.status < 300) {
        if (!payload) {
          reject(new ApiError("The server returned an empty response.", undefined, "EMPTY_SERVER_RESPONSE", request.status));
          return;
        }
        resolve(sourceFromPayload(payload as SourcePayload));
      } else {
        reject(normalizeApiError(request.status, payload));
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
  let job = jobFromPayload(await requestJson<JobPayload>("/api/jobs/youtube", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, rights_confirmed: rightsConfirmed }),
  }, 30_000));
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
  return sourceFromPayload(await requestJson<SourcePayload>(`/api/sources/${encodeURIComponent(job.sourceId)}`, { cache: "no-store" }));
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
  const payload = await requestJson<JobPayload>("/api/jobs/clips", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_id: sourceId,
      segments,
      output_format: options.outputFormat,
      portrait_mode: "center_crop",
      auto_captions: options.autoCaptions,
      platforms: options.platforms,
      fast_mode: true,
    }),
  }, 30_000);
  return jobFromPayload(payload);
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
  return (await requestJson<ProjectPayload[]>(`/api/projects?limit=${limit}`, { cache: "no-store" })).map(projectFromPayload);
}

export async function getProject(projectId: string): Promise<ApiProject> {
  const payload = await requestJson<ProjectPayload>(`/api/projects/${encodeURIComponent(projectId)}`, {
    cache: "no-store",
  });
  return projectFromPayload(payload);
}

export async function createThumbnailCandidates(
  projectId: string,
  prompt: string,
  target: Platform,
): Promise<ApiArtifact[]> {
  const payload = await requestJson<ArtifactPayload[]>(`/api/projects/${encodeURIComponent(projectId)}/thumbnails`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt, target }),
  });
  return payload.map(artifactFromPayload);
}

export async function createAIEditPlan(sourceId: string, prompt: string): Promise<AIEditPlan> {
  const payload = await requestJson<{
    source_id: string;
    summary: string;
    actions: AIEditPlan["actions"];
    segments: Array<{ id: string; index: number; start: number; end: number; strategy: "standard" | "ai" }>;
    output_format: OutputFormat;
    auto_captions: boolean;
  }>("/api/ai/edit-plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_id: sourceId, prompt }),
  });
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
  const payload = await requestJson<Array<{
    platform: Platform; label: string; connected: boolean; configured: boolean; detail: string; setup_hint: string;
  }>>("/api/social/connections", { cache: "no-store" });
  return payload.map((item) => ({ ...item, setupHint: item.setup_hint }));
}

export async function saveSchedule(input: {
  projectId: string;
  platforms: Platform[];
  intervalMinutes: number;
  startAt: string;
  caption: string;
}): Promise<SavedSchedule> {
  const payload = await requestJson<{
    id: string; project_id: string; archive_name: string; created_at: number;
    posts: Array<{ platform: Platform; clip_name: string; publish_at: string; caption: string; status: string }>;
    publish_ready: boolean;
  }>("/api/schedules", {
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
  return jobFromPayload(await requestJson<JobPayload>(`/api/jobs/${encodeURIComponent(jobId)}`, { cache: "no-store" }));
}
