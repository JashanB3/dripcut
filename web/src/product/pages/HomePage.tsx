import {
  ArrowRight,
  AudioLines,
  CalendarClock,
  Clapperboard,
  Download,
  Film,
  ImagePlus,
  Instagram,
  Play,
  Plus,
  Radio,
  Sparkles,
  WandSparkles,
  Youtube,
} from "lucide-react";
import { useEffect, useState } from "react";

import { CustomerError } from "../components/CustomerError";
import { isLaunchRoute, youtubePublishingBeta } from "../launch";
import { apiUrl, fetchLatestSchedule, fetchProjects, fetchUsage } from "../api/client";
import type { ApiProject, ProductRoute, SavedSchedule, UsageSummary } from "../models";

const quickActions = [
  ["Auto Clip", Sparkles, "auto-clip"],
  ["YouTube Shorts", Youtube, "auto-clip"],
  ["Instagram Reels", Instagram, "auto-clip"],
  ["AI Edit", WandSparkles, "ai-editor"],
  ["Schedule", CalendarClock, "schedule"],
  ["Extract Video", Download, null],
] as const;

const quickTools = [
  ["YouTube Shorts", "Frame ideas for vertical Shorts", Youtube, "coral", "auto-clip"],
  ["Instagram Reels", "Plan creator-first Reels", Instagram, "violet", "auto-clip"],
  ["Extract Audio", "Pull audio from a finished video", AudioLines, "lime", null],
  ["AI Thumbnail", "Explore thumbnail directions", ImagePlus, "amber", "ai-thumbnail"],
  ["Video Extractor", "Prepare a video from a link", Download, "cyan", null],
  ["AI Editor", "Describe the edit you want", WandSparkles, "violet", "ai-editor"],
  ["Schedule Content", "Build a publishing rhythm", CalendarClock, "coral", "schedule"],
] as const;

export function HomePage({ onCreate, onNavigate }: {
  onCreate: () => void;
  onNavigate: (route: ProductRoute) => void;
}) {
  const [projects, setProjects] = useState<ApiProject[]>([]);
  const [projectsError, setProjectsError] = useState<unknown>(null);
  const [projectsBusy, setProjectsBusy] = useState(true);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [schedule, setSchedule] = useState<SavedSchedule | null>(null);

  useEffect(() => {
    void Promise.allSettled([fetchProjects(8), fetchUsage(), youtubePublishingBeta ? fetchLatestSchedule() : Promise.resolve(null)])
      .then(([projectResult, usageResult, scheduleResult]) => {
        if (projectResult.status === "rejected") setProjectsError(projectResult.reason);
        setProjects(projectResult.status === "fulfilled" ? projectResult.value : []);
        setUsage(usageResult.status === "fulfilled" ? usageResult.value : null);
        setSchedule(scheduleResult.status === "fulfilled" ? scheduleResult.value : null);
      })
      .finally(() => setProjectsBusy(false));
  }, []);

  const downloadable = projects.filter((project) => project.downloadArtifactId).slice(0, 3);
  const scheduledPosts = schedule?.posts.filter((post) => ["scheduled", "uploading"].includes(post.status)) ?? [];
  const nextPost = [...scheduledPosts].sort((a, b) => a.publishAt.localeCompare(b.publishAt))[0];
  const processing = usage?.metrics.find((metric) => metric.key === "video_processing_minutes");

  const openProject = (project: ApiProject) => {
    window.localStorage.setItem("dripcut.activeProjectId", project.id);
    onNavigate(project.workflowRoute);
  };

  return (
    <div className="home-page product-page">
      {projectsError !== null && <CustomerError error={projectsError} fallback="We couldn’t load your projects. Refresh to try again." />}
      <section className="home-hero">
        <span className="hero-orbit hero-orbit--one" />
        <span className="hero-orbit hero-orbit--two" />
        <div className="home-hero__copy">
          <span className="eyebrow">Your content launchpad</span>
          <h1>What will you <span>create</span> today?</h1>
          <p>Turn long videos into scroll-stopping content.</p>
        </div>
        <button className="hero-create-field" onClick={onCreate}>
          <span><Plus size={20} /> Upload a video or paste a YouTube link</span>
          <strong>Create</strong>
        </button>
        <div className="quick-actions" aria-label="Quick actions">
          {quickActions.filter((item) => isLaunchRoute(item[2])).map(([label, Icon, route]) => (
            <button key={label} disabled={!route} onClick={() => route && onNavigate(route)} title={!route ? "This workflow is not connected yet" : undefined}>
              <span><Icon size={19} /></span>
              {label}
            </button>
          ))}
        </div>
      </section>

      <section className="workspace-pulse" aria-label="Workspace overview">
        <article><span><Download size={17} /></span><div><small>Recent exports</small><strong>{downloadable.length ? `${downloadable.length} ready` : "No clips yet"}</strong><em>{downloadable[0]?.title ?? "Your latest renders appear here"}</em></div>{downloadable[0]?.downloadArtifactId && <a href={apiUrl(`/api/artifacts/${downloadable[0].downloadArtifactId}/download`)} download>Download</a>}</article>
        {youtubePublishingBeta && <article><span><Radio size={17} /></span><div><small>Scheduled content</small><strong>{scheduledPosts.length ? `${scheduledPosts.length} upcoming` : "Nothing queued"}</strong><em>{nextPost ? `${nextPost.platform} · ${new Date(nextPost.publishAt).toLocaleString()}` : "Connect a platform when you are ready"}</em></div><button onClick={() => onNavigate("schedule")}>Open</button></article>}
        <article><span><Film size={17} /></span><div><small>{usage?.planLabel ?? "Usage"}</small><strong>{processing ? `${processing.used.toFixed(1)} / ${processing.limit ?? "∞"} min` : "Usage ready"}</strong><em>{processing ? `Resets ${new Date(usage!.resetAt).toLocaleDateString()}` : "View processing and AI allowances"}</em></div><button onClick={() => onNavigate("usage")}>View</button></article>
      </section>

      <section className="auto-clip-feature">
        <div className="auto-clip-feature__copy">
          <span className="magic-badge"><Sparkles size={14} /> DripCut Magic</span>
          <h2>One video. Ready-to-share Shorts & Reels.</h2>
          <p>Upload a long video, choose a duration and get a clear clip plan. AI moment discovery stays optional.</p>
          <div className="feature-actions">
            <button className="primary-action" onClick={() => onNavigate("auto-clip")}>Start auto clipping <ArrowRight size={17} /></button>
            <button className="secondary-action" onClick={() => onNavigate("auto-clip")}><Play size={16} /> See the workflow</button>
          </div>
        </div>
        <div className="auto-clip-visual" aria-hidden="true">
          <div className="visual-player">
            <span className="visual-player__subject"><i /><i /><i /></span>
            <span className="visual-caption">ONE VIDEO. MANY MOMENTS.</span>
            <span className="visual-play"><Play size={18} fill="currentColor" /></span>
          </div>
          <div className="visual-timeline">
            <span /><span /><span /><span /><i />
          </div>
          <div className="visual-output"><Film size={14} /> 6 clips planned <span>9:16</span></div>
        </div>
      </section>

      <section className="content-section">
        <div className="section-heading"><div><span className="eyebrow">Projects</span><h2>Continue creating</h2></div><button className="text-action" onClick={() => onNavigate("projects")}>View all <ArrowRight size={15} /></button></div>
        {projectsBusy && <div className="projects-empty"><span className="spinner" /> Loading your projects…</div>}
        {!projectsBusy && projects.length === 0 && <div className="projects-empty"><Clapperboard size={24} /><strong>No projects yet</strong><span>Upload a video or paste a YouTube link to create your first one.</span><button onClick={() => onNavigate("auto-clip")}>Create clips</button></div>}
        {!projectsBusy && projects.length > 0 && <div className="project-row">
          {projects.map((project, index) => (
            <article key={project.id} className="project-card">
              <button className="project-card__open" onClick={() => openProject(project)} aria-label={`Open ${project.title}`}>
                <div className={`project-card__art project-card__art--${["violet", "cyan", "coral", "lime"][index % 4]}`} style={project.thumbnailUrl ? { backgroundImage: `url(${project.thumbnailUrl})` } : undefined}>
                  {!project.thumbnailUrl && <Clapperboard size={24} />}
                  <span>{project.outputFormat}</span>
                </div>
                <div className="project-card__content">
                  <strong>{project.title}</strong>
                  <span>{project.clipCount} clips · {project.captionsEnabled ? "Captions on" : "Captions off"}</span>
                  <small>{new Date(project.updatedAt * 1000).toLocaleDateString()}<em>{project.status}</em></small>
                </div>
              </button>
              {project.downloadArtifactId && <a className="project-download" href={apiUrl(`/api/artifacts/${project.downloadArtifactId}/download`)} download><Download size={14} /> Download</a>}
            </article>
          ))}
        </div>}
      </section>

      <section className="content-section quick-tools-section">
        <div className="section-heading"><div><span className="eyebrow">Quick tools</span><h2>One job. Zero maze.</h2></div></div>
        <div className="quick-tool-grid">
          {quickTools.filter((item) => isLaunchRoute(item[4])).map(([title, body, Icon, accent, route], index) => (
            <button
              key={title}
              className={`quick-tool quick-tool--${accent} ${index === 0 ? "quick-tool--wide" : ""}`}
              disabled={!route}
              onClick={() => route && onNavigate(route)}
              title={!route ? "This workflow is not connected yet" : undefined}
            >
              <span><Icon size={21} /></span>
              <strong>{title}</strong>
              <small>{body}</small>
              {route ? <ArrowRight size={16} /> : <em>Coming later</em>}
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
