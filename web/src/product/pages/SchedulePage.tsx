import { CalendarClock, CheckCircle2, ExternalLink, Youtube } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { beginSocialOAuth, disconnectSocial, fetchProjects, fetchSchedule, fetchSocialConnections, getClipJob, saveSchedule } from "../api/client";
import { CustomerError } from "../components/CustomerError";
import type { ApiArtifact, ApiProject, SavedSchedule, SocialConnection } from "../models";

type PublishMode = "now" | "schedule";
type Privacy = "private" | "unlisted" | "public";

export function SchedulePage() {
  const [projects, setProjects] = useState<ApiProject[]>([]);
  const [projectId, setProjectId] = useState(() => window.localStorage.getItem("dripcut.activeProjectId") ?? "");
  const [clips, setClips] = useState<ApiArtifact[]>([]);
  const [artifactId, setArtifactId] = useState(() => window.localStorage.getItem("dripcut.scheduleArtifactId") ?? "");
  const [connection, setConnection] = useState<SocialConnection | null>(null);
  const [title, setTitle] = useState(() => cleanTitle(window.localStorage.getItem("dripcut.scheduleClipName") ?? ""));
  const [description, setDescription] = useState("");
  const [publishMode, setPublishMode] = useState<PublishMode>("schedule");
  const [privacy, setPrivacy] = useState<Privacy>("public");
  const [startAt, setStartAt] = useState(defaultFutureTime);
  const [schedule, setSchedule] = useState<SavedSchedule | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [connectionBusy, setConnectionBusy] = useState(false);
  const timezone = useMemo(() => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC", []);

  const refreshConnection = async () => {
    const statuses = await fetchSocialConnections();
    setConnection(statuses.find((item) => item.platform === "youtube") ?? null);
  };

  useEffect(() => {
    void Promise.all([fetchProjects(100), fetchSocialConnections()]).then(([items, statuses]) => {
      const ready = items.filter((item) => item.status === "completed" && item.latestJobId);
      setProjects(ready);
      setProjectId((current) => ready.some((item) => item.id === current) ? current : ready[0]?.id ?? "");
      setConnection(statuses.find((item) => item.platform === "youtube") ?? null);
    }).catch(setError);
  }, []);

  useEffect(() => {
    const project = projects.find((item) => item.id === projectId);
    if (!project?.latestJobId) {
      setClips([]);
      return;
    }
    void getClipJob(project.latestJobId).then((job) => {
      const available = job.artifacts.filter((item) => item.kind === "clip");
      setClips(available);
      setArtifactId((current) => available.some((item) => item.id === current) ? current : available[0]?.id ?? "");
    }).catch(setError);
  }, [projectId, projects]);

  useEffect(() => {
    const clip = clips.find((item) => item.id === artifactId);
    if (!clip) return;
    window.localStorage.setItem("dripcut.scheduleArtifactId", clip.id);
    setTitle(cleanTitle(clip.name));
  }, [artifactId, clips]);

  useEffect(() => {
    if (!schedule || !schedule.posts.some((post) => ["scheduled", "uploading", "youtube_processing"].includes(post.status))) return;
    const timer = window.setInterval(() => void fetchSchedule(schedule.id).then(setSchedule).catch(() => undefined), 4000);
    return () => window.clearInterval(timer);
  }, [schedule]);

  const changeConnection = async () => {
    if (!connection) return;
    setConnectionBusy(true);
    setError(null);
    try {
      if (connection.connected) {
        await disconnectSocial("youtube");
        await refreshConnection();
      } else {
        window.location.assign(await beginSocialOAuth("youtube"));
      }
    } catch (reason) {
      setError(reason);
      setConnectionBusy(false);
    }
  };

  const changeMode = (mode: PublishMode) => {
    setPublishMode(mode);
    setPrivacy(mode === "schedule" ? "public" : "private");
  };

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      setSchedule(await saveSchedule({
        projectId,
        artifactId,
        platforms: ["youtube"],
        startAt: publishMode === "now" ? "now" : startAt,
        title: title.trim(),
        description: description.trim(),
        publishMode,
        privacy,
        timezone,
      }));
    } catch (reason) {
      setError(reason);
    } finally {
      setBusy(false);
    }
  };

  const connected = Boolean(connection?.connected);
  const canSubmit = connected && projectId && artifactId && title.trim() && (publishMode === "now" || startAt);

  return <div className="schedule-page product-page">
    <header className="page-heading-row"><div><span className="eyebrow">YouTube publishing</span><h1>Schedule one finished clip.</h1><p>DripCut saves the job immediately, then uploads to YouTube in the background.</p></div></header>
    {error !== null && <CustomerError error={error} fallback="Scheduling could not be completed." />}
    <div className="connection-cards">
      {connection && <article data-connected={connection.connected}>
        {connection.avatarUrl ? <img className="social-avatar" src={connection.avatarUrl} alt="" /> : <Youtube />}
        <div><strong>YouTube</strong><span>{connection.connected ? connection.detail : "Connect a YouTube channel to publish clips."}</span>{connection.channelId && <small>Channel ID: {connection.channelId}</small>}<small>{connection.connected ? "Refresh access is encrypted and stored on the server." : connection.configured ? "Google OAuth is ready." : connection.setupHint}</small></div>
        <button disabled={!connection.configured || connectionBusy} onClick={() => void changeConnection()}>{connectionBusy ? "Working…" : connection.connected ? "Disconnect" : connection.configured ? "Connect YouTube" : "Admin setup required"}</button>
      </article>}
    </div>
    <div className="schedule-workspace">
      <section className="schedule-builder">
        {!connected && <div className="social-notice"><Youtube size={16} /> Connect YouTube before scheduling this clip.</div>}
        <label><span>Finished project</span><select value={projectId} onChange={(event) => { setProjectId(event.target.value); setArtifactId(""); }}><option value="">Choose a project</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.title}</option>)}</select></label>
        <label><span>Video</span><select value={artifactId} onChange={(event) => setArtifactId(event.target.value)}><option value="">Choose one clip</option>{clips.map((clip) => <option key={clip.id} value={clip.id}>{clip.index ? `Clip ${clip.index} · ` : ""}{clip.name}</option>)}</select></label>
        <label><span>Title</span><input required maxLength={100} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="YouTube title" /></label>
        <label><span>Description (optional)</span><textarea maxLength={5000} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Add context, links, or hashtags" /></label>
        <div><span>Publish</span><div className="platform-options"><button type="button" data-selected={publishMode === "now"} onClick={() => changeMode("now")}>Publish now</button><button type="button" data-selected={publishMode === "schedule"} onClick={() => changeMode("schedule")}>Schedule</button></div></div>
        {publishMode === "schedule" && <label><span>Date and time · {timezone}</span><input type="datetime-local" value={startAt} min={minimumFutureTime()} onChange={(event) => setStartAt(event.target.value)} /></label>}
        <label><span>Privacy</span><select value={privacy} onChange={(event) => setPrivacy(event.target.value as Privacy)} disabled={publishMode === "schedule"}>{publishMode === "schedule" ? <option value="public">Public at scheduled time</option> : <><option value="private">Private</option><option value="unlisted">Unlisted</option><option value="public">Public</option></>}</select></label>
        <button className="primary-action" disabled={!canSubmit || busy} onClick={() => void submit()}><CalendarClock size={16} /> {busy ? "Saving…" : publishMode === "now" ? "Publish clip" : "Schedule clip"}</button>
      </section>
      <section className="saved-schedule">
        {!schedule && <div className="projects-empty projects-empty--large"><CalendarClock size={28} /><strong>No YouTube job yet</strong><span>Select one clip, add its metadata, and choose when to publish.</span></div>}
        {schedule && <><header><CheckCircle2 size={20} /><div><strong>{schedule.posts[0]?.status === "scheduled_on_youtube" ? "Scheduled on YouTube" : "Accepted by DripCut"}</strong><span>{schedule.archiveName}</span></div><em>{friendlyStatus(schedule.posts[0]?.status)}</em></header>{schedule.posts.map((post) => <article key={post.id} data-status={post.status}><strong>{post.title || post.clipName}</strong><span>YouTube · {friendlyStatus(post.status)}</span><small>{post.publishMode === "schedule" ? new Date(post.publishAt).toLocaleString([], { timeZone: post.timezone }) : `${post.privacy} upload`}</small>{post.externalPostId && <small>Video ID: {post.externalPostId}</small>}{post.externalUrl && <a href={post.externalUrl} target="_blank" rel="noreferrer">Open on YouTube <ExternalLink size={13} /></a>}{post.errorMessage && <small>{post.errorMessage}</small>}</article>)}</>}
      </section>
    </div>
  </div>;
}

function cleanTitle(name: string): string {
  return name.replace(/\.[^.]+$/, "").replace(/[-_]+/g, " ").trim().slice(0, 100);
}

function dateInput(minutesAhead: number): string {
  const date = new Date(Date.now() + minutesAhead * 60_000);
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function defaultFutureTime(): string { return dateInput(10); }
function minimumFutureTime(): string { return dateInput(1); }

function friendlyStatus(status = "scheduled"): string {
  return ({ scheduled: "Queued", uploading: "Uploading to YouTube", uploaded: "Uploaded privately", youtube_processing: "YouTube processing", scheduled_on_youtube: "Scheduled on YouTube", published: "Published", failed: "Needs attention", cancelled: "Cancelled", draft: "Connect YouTube" } as Record<string, string>)[status] ?? status;
}
