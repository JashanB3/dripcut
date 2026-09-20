import { CalendarClock, CheckCircle2, ExternalLink, Instagram, Youtube } from "lucide-react";
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
  const [artifactIds, setArtifactIds] = useState<string[]>(() => {
    try {
      const stored = JSON.parse(window.localStorage.getItem("dripcut.scheduleArtifactIds") ?? "[]");
      return Array.isArray(stored) ? stored.filter((item): item is string => typeof item === "string") : [];
    } catch {
      return [];
    }
  });
  const [connections, setConnections] = useState<SocialConnection[]>([]);
  const [selectedPlatforms, setSelectedPlatforms] = useState<Array<"youtube" | "instagram">>(() => {
    try {
      const stored = JSON.parse(window.localStorage.getItem("dripcut.schedulePlatforms") ?? '["youtube"]');
      return Array.isArray(stored) ? stored.filter((item): item is "youtube" | "instagram" => item === "youtube" || item === "instagram") : ["youtube"];
    } catch { return ["youtube"]; }
  });
  const [title, setTitle] = useState(() => cleanTitle(window.localStorage.getItem("dripcut.scheduleClipName") ?? ""));
  const [description, setDescription] = useState("");
  const [publishMode, setPublishMode] = useState<PublishMode>("schedule");
  const [privacy, setPrivacy] = useState<Privacy>("public");
  const [startAt, setStartAt] = useState(defaultFutureTime);
  const [intervalMinutes, setIntervalMinutes] = useState(30);
  const [schedule, setSchedule] = useState<SavedSchedule | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [connectionBusy, setConnectionBusy] = useState(false);
  const timezone = useMemo(() => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC", []);

  const refreshConnection = async () => {
    const statuses = await fetchSocialConnections();
    setConnections(statuses);
  };

  useEffect(() => {
    void Promise.all([fetchProjects(100), fetchSocialConnections()]).then(([items, statuses]) => {
      const ready = items.filter((item) => item.status === "completed" && item.latestJobId);
      setProjects(ready);
      setProjectId((current) => ready.some((item) => item.id === current) ? current : ready[0]?.id ?? "");
      setConnections(statuses);
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
      setArtifactIds((current) => {
        const valid = current.filter((id) => available.some((item) => item.id === id));
        return valid.length ? valid : available.map((item) => item.id);
      });
    }).catch(setError);
  }, [projectId, projects]);

  useEffect(() => {
    window.localStorage.setItem("dripcut.scheduleArtifactIds", JSON.stringify(artifactIds));
    if (!title.trim()) {
      const first = clips.find((item) => item.id === artifactIds[0]);
      if (first) setTitle(cleanTitle(first.name));
    }
  }, [artifactIds, clips, title]);

  useEffect(() => {
    if (!schedule || !schedule.posts.some((post) => ["scheduled", "uploading", "youtube_processing"].includes(post.status))) return;
    const timer = window.setInterval(() => void fetchSchedule(schedule.id).then(setSchedule).catch(() => undefined), 4000);
    return () => window.clearInterval(timer);
  }, [schedule]);

  const changeConnection = async (platformName: "youtube" | "instagram") => {
    const platform = connections.find((item) => item.platform === platformName);
    if (!platform) return;
    setConnectionBusy(true);
    setError(null);
    try {
      if (platform.connected) {
        await disconnectSocial(platform.platform);
        await refreshConnection();
      } else {
        window.location.assign(await beginSocialOAuth(platform.platform));
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
        artifactIds,
        platforms: selectedPlatforms,
        startAt: publishMode === "now" ? "now" : startAt,
        intervalMinutes,
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

  const connectedPlatforms = selectedPlatforms.filter((platform) => connections.find((item) => item.platform === platform)?.connected);
  const canSubmit = selectedPlatforms.length > 0 && connectedPlatforms.length === selectedPlatforms.length && projectId && artifactIds.length > 0 && title.trim() && (publishMode === "now" || startAt);
  const allSelected = clips.length > 0 && artifactIds.length === clips.length;
  const toggleAll = () => setArtifactIds(allSelected ? [] : clips.map((clip) => clip.id));
  const togglePlatform = (platform: "youtube" | "instagram") => setSelectedPlatforms((current) => {
    const next = current.includes(platform) ? current.filter((item) => item !== platform) : [...current, platform];
    return next.length ? next : current;
  });
  useEffect(() => { window.localStorage.setItem("dripcut.schedulePlatforms", JSON.stringify(selectedPlatforms)); }, [selectedPlatforms]);

  return <div className="schedule-page product-page">
    <header className="page-heading-row"><div><span className="eyebrow">Multi-platform publishing</span><h1>Schedule your finished clips.</h1><p>Publish the same clip to YouTube Shorts and Instagram Reels at the same time.</p></div></header>
    {error !== null && <CustomerError error={error} fallback="Scheduling could not be completed." />}
    <div className="connection-cards">
      {connections.map((item) => <article key={item.platform} data-connected={item.connected}>
        {item.avatarUrl ? <img className="social-avatar" src={item.avatarUrl} alt="" /> : item.platform === "youtube" ? <Youtube /> : <Instagram />}
        <div><strong>{item.platform === "youtube" ? "YouTube Shorts" : "Instagram Reels"}</strong><span>{item.connected ? item.detail : `Connect ${item.platform === "youtube" ? "a YouTube channel" : "an Instagram professional account"}.`}</span>{item.channelId && <small>Account ID: {item.channelId}</small>}<small>{item.connected ? "Access is encrypted and stored on the server." : item.configured ? "OAuth is ready." : item.setupHint}</small></div>
        <button disabled={!item.configured || connectionBusy} onClick={() => void changeConnection(item.platform)}>{connectionBusy ? "Working…" : item.connected ? "Disconnect" : item.configured ? `Connect ${item.platform === "youtube" ? "YouTube" : "Instagram"}` : "Admin setup required"}</button>
      </article>)}
    </div>
    <div className="schedule-workspace">
      <section className="schedule-builder">
        {selectedPlatforms.some((platform) => !connections.find((item) => item.platform === platform)?.connected) && <div className="social-notice"><CalendarClock size={16} /> Connect every selected platform before scheduling.</div>}
        <div className="control-group"><span>Publish to</span><div className="platform-options">
          {(["youtube", "instagram"] as const).map((platform) => <button key={platform} type="button" data-selected={selectedPlatforms.includes(platform)} disabled={!connections.find((item) => item.platform === platform)?.connected} onClick={() => togglePlatform(platform)}>{platform === "youtube" ? <Youtube size={17} /> : <Instagram size={17} />} {platform === "youtube" ? "YouTube Shorts" : "Instagram Reels"}</button>)}
        </div><small>Both platforms use the same clip and publish time.</small></div>
        <label><span>Finished project</span><select value={projectId} onChange={(event) => { setProjectId(event.target.value); setArtifactIds([]); }}><option value="">Choose a project</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.title}</option>)}</select></label>
        <div className="schedule-clip-picker"><div className="schedule-clip-picker__header"><span>Clips to publish</span><button type="button" onClick={toggleAll} disabled={!clips.length}>{allSelected ? "Clear all" : "Select all"}</button></div>{clips.length ? clips.map((clip) => <label key={clip.id} className="schedule-clip-option"><input type="checkbox" checked={artifactIds.includes(clip.id)} onChange={() => setArtifactIds((current) => current.includes(clip.id) ? current.filter((id) => id !== clip.id) : [...current, clip.id])} /><span>{clip.index ? `Clip ${clip.index} · ` : ""}{clip.name}</span></label>) : <span className="schedule-clip-picker__empty">No finished clips found in this project.</span>}<small>{artifactIds.length} of {clips.length} clips selected</small></div>
        <label><span>Title</span><input required maxLength={100} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="YouTube title" /></label>
        <label><span>Description (optional)</span><textarea maxLength={5000} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Add context, links, or hashtags" /></label>
        <div><span>Publish</span><div className="platform-options"><button type="button" data-selected={publishMode === "now"} onClick={() => changeMode("now")}>Publish now</button><button type="button" data-selected={publishMode === "schedule"} onClick={() => changeMode("schedule")}>Schedule</button></div></div>
        {publishMode === "schedule" && <><label><span>First upload · {timezone}</span><input type="datetime-local" value={startAt} min={minimumFutureTime()} onChange={(event) => setStartAt(event.target.value)} /></label><label><span>Upload one clip every</span><select value={intervalMinutes} onChange={(event) => setIntervalMinutes(Number(event.target.value))}><option value={10}>10 minutes</option><option value={20}>20 minutes</option><option value={30}>30 minutes</option><option value={60}>1 hour</option><option value={120}>2 hours</option></select></label></>}
        <label><span>Privacy</span><select value={privacy} onChange={(event) => setPrivacy(event.target.value as Privacy)} disabled={publishMode === "schedule"}>{publishMode === "schedule" ? <option value="public">Public at scheduled time</option> : <><option value="private">Private</option><option value="unlisted">Unlisted</option><option value="public">Public</option></>}</select></label>
        <button className="primary-action" disabled={!canSubmit || busy} onClick={() => void submit()}><CalendarClock size={16} /> {busy ? "Saving…" : publishMode === "now" ? `Publish ${artifactIds.length} clips` : `Schedule ${artifactIds.length} clips`}</button>
      </section>
      <section className="saved-schedule">
        {!schedule && <div className="projects-empty projects-empty--large"><CalendarClock size={28} /><strong>No publishing job yet</strong><span>Select clips, connect one or both platforms, choose an interval, and publish.</span></div>}
        {schedule && <><header><CheckCircle2 size={20} /><div><strong>Publishing schedule accepted</strong><span>{schedule.archiveName}</span></div><em>{friendlyStatus(schedule.posts[0]?.status)}</em></header>{schedule.posts.map((post) => <article key={post.id} data-status={post.status}><strong>{post.title || post.clipName}</strong><span>{post.platform === "youtube" ? "YouTube Shorts" : "Instagram Reels"} · {friendlyStatus(post.status)}</span><small>{post.publishMode === "schedule" ? new Date(post.publishAt).toLocaleString([], { timeZone: post.timezone }) : `${post.privacy} upload`}</small>{post.externalPostId && <small>Post ID: {post.externalPostId}</small>}{post.externalUrl && <a href={post.externalUrl} target="_blank" rel="noreferrer">Open post <ExternalLink size={13} /></a>}{post.errorMessage && <small>{post.errorMessage}</small>}</article>)}</>}
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
