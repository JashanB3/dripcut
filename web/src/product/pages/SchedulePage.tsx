import { CalendarClock, CheckCircle2, Instagram, Sparkles, Youtube } from "lucide-react";
import { useEffect, useState } from "react";

import { beginSocialOAuth, disconnectSocial, fetchProjects, fetchProviderCapabilities, fetchSchedule, fetchSocialConnections, generateSocialMetadata, saveSchedule, updateScheduledPost } from "../api/client";
import { CustomerError } from "../components/CustomerError";
import type { ApiProject, Platform, ProviderCapabilities, SavedSchedule, SocialConnection, SocialMetadataPackage } from "../models";

export function SchedulePage() {
  const [projects, setProjects] = useState<ApiProject[]>([]);
  const [projectId, setProjectId] = useState("");
  const [connections, setConnections] = useState<SocialConnection[]>([]);
  const [capabilities, setCapabilities] = useState<ProviderCapabilities[]>([]);
  const [platforms, setPlatforms] = useState<Platform[]>(["youtube"]);
  const [interval, setInterval] = useState(1440);
  const [startAt, setStartAt] = useState("");
  const [caption, setCaption] = useState("{clip} #shorts #reels");
  const [schedule, setSchedule] = useState<SavedSchedule | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [metadata, setMetadata] = useState<SocialMetadataPackage | null>(null);
  const [connectionBusy, setConnectionBusy] = useState<Platform | null>(null);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    const socialResult = new URLSearchParams(window.location.search).get("social");
    if (socialResult?.endsWith("-connected")) setNotice("Account connected. Your scheduled posts can now publish automatically.");
    if (socialResult?.endsWith("-denied")) setNotice("Connection cancelled. Nothing was changed.");
    void Promise.all([fetchProjects(100), fetchSocialConnections(), fetchProviderCapabilities()]).then(([items, statuses, providerCapabilities]) => {
      const ready = items.filter((item) => item.downloadArtifactId && item.status === "completed");
      setProjects(ready);
      setProjectId(ready[0]?.id ?? "");
      setConnections(statuses.filter((item) => item.platform === "youtube"));
      setCapabilities(providerCapabilities);
    }).catch(setError);
  }, []);

  useEffect(() => {
    if (!schedule || !schedule.posts.some((post) => post.status === "scheduled" || post.status === "uploading")) return;
    const timer = window.setInterval(() => {
      void fetchSchedule(schedule.id).then(setSchedule).catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [schedule]);

  const adjustPost = async (postId: string, update: { publishAt?: string; caption?: string }) => {
    if (!schedule) return;
    setError(null);
    try {
      setSchedule(await updateScheduledPost(schedule.id, postId, update));
    } catch (reason) {
      setError(reason);
    }
  };

  const changeConnection = async (connection: SocialConnection) => {
    setConnectionBusy(connection.platform);
    setError(null);
    try {
      if (connection.connected) {
        await disconnectSocial(connection.platform);
        setConnections(await fetchSocialConnections());
        setNotice(`${connection.label} disconnected.`);
      } else {
        const authorizationUrl = await beginSocialOAuth(connection.platform);
        window.location.assign(authorizationUrl);
      }
    } catch (reason) {
      setError(reason);
    } finally {
      setConnectionBusy(null);
    }
  };

  const toggle = (platform: Platform) => {
    if (!capabilities.some((item) => item.platform === platform && item.canSchedule)) return;
    const next = platforms.includes(platform) ? platforms.filter((item) => item !== platform) : [...platforms, platform];
    if (next.length) setPlatforms(next);
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      setSchedule(await saveSchedule({ projectId, platforms, intervalMinutes: interval, startAt: startAt || "now", caption }));
    } catch (reason) {
      setError(reason);
    } finally {
      setBusy(false);
    }
  };

  const createMetadata = async () => {
    if (!projectId) return;
    setBusy(true);
    setError(null);
    try {
      const generated = await generateSocialMetadata(projectId);
      setMetadata(generated);
      setCaption(
        platforms.includes("instagram")
          ? `${generated.instagramCaption}\n\n${generated.instagramHashtags.join(" ")}\n${generated.instagramCta}`.trim()
          : `${generated.youtubeDescription}\n\n${generated.youtubeHashtags.join(" ")}`.trim(),
      );
    } catch (reason) {
      setError(reason);
    } finally {
      setBusy(false);
    }
  };

  return <div className="schedule-page product-page">
    <header className="page-heading-row"><div><span className="eyebrow">Publishing</span><h1>YouTube publishing beta</h1><p>Save a durable posting plan. Publishing unlocks only when official platform credentials are configured.</p></div></header>
    {error !== null && <CustomerError error={error} fallback="Scheduling could not be completed." />}
    {notice && <div className="social-notice"><CheckCircle2 size={16} /> {notice}</div>}
    <div className="connection-cards">{connections.map((connection) => <article key={connection.platform} data-connected={connection.connected}>{connection.platform === "youtube" ? <Youtube /> : <Instagram />}<div><strong>{connection.label}</strong><span>{connection.detail}</span><small>{connection.connected ? "Encrypted credentials are stored on the server." : connection.configured ? "Official OAuth is ready." : connection.setupHint}</small></div><button disabled={!connection.configured || connectionBusy === connection.platform} onClick={() => void changeConnection(connection)}>{connectionBusy === connection.platform ? "Working…" : connection.connected ? "Disconnect" : connection.configured ? "Connect" : "Admin setup"}</button></article>)}</div>
    <div className="schedule-workspace">
      <section className="schedule-builder">
        <label><span>Finished project</span><select value={projectId} onChange={(event) => setProjectId(event.target.value)}>{projects.map((project) => <option key={project.id} value={project.id}>{project.title}</option>)}</select></label>
        <div><span>Platforms</span><div className="platform-options"><button disabled={!capabilities.some((item) => item.platform === "youtube" && item.canSchedule)} data-selected={platforms.includes("youtube")} onClick={() => toggle("youtube")}><Youtube size={16} /> YouTube</button><span>Instagram publishing coming soon</span></div></div>
        <label><span>Start</span><input type="datetime-local" value={startAt} onChange={(event) => setStartAt(event.target.value)} /></label>
        <label><span>Interval</span><select value={interval} onChange={(event) => setInterval(Number(event.target.value))}><option value="360">Every 6 hours</option><option value="720">Every 12 hours</option><option value="1440">Daily</option><option value="2880">Every 2 days</option></select></label>
        <label><span>Caption template</span><textarea value={caption} onChange={(event) => setCaption(event.target.value)} /></label>
        <button className="secondary-action" disabled={!projectId || busy} onClick={() => void createMetadata()}><Sparkles size={16} /> {busy ? "Generating…" : "Generate editable AI metadata"}</button>
        {metadata && <div className="social-metadata-preview"><strong>{metadata.youtubeTitle}</strong><span>{metadata.hook} · {metadata.category}</span><small>{metadata.postingDescription}</small></div>}
        <button className="primary-action" disabled={!projectId || busy} onClick={() => void save()}><CalendarClock size={16} /> {busy ? "Saving…" : platforms.every((platform) => connections.some((connection) => connection.platform === platform && connection.connected)) ? "Schedule posts" : "Save draft"}</button>
      </section>
      <section className="saved-schedule">
        {!schedule && <div className="projects-empty projects-empty--large"><CalendarClock size={28} /><strong>No schedule preview yet</strong><span>Choose a finished project and save its posting rhythm.</span></div>}
        {schedule && <><header><CheckCircle2 size={20} /><div><strong>{schedule.posts.length} posts planned</strong><span>{schedule.archiveName}</span></div><em>{schedule.publishReady ? "Publishing active" : "Draft only"}</em></header>{schedule.posts.map((post) => <article key={post.id} data-status={post.status}><strong>{post.clipName}</strong><span>{post.platform} · {post.status}</span><label><span>Publish time</span><input type="datetime-local" defaultValue={toLocalInput(post.publishAt)} disabled={post.status === "uploading" || post.status === "published"} onBlur={(event) => event.target.value && void adjustPost(post.id, { publishAt: event.target.value })} /></label><label><span>Caption</span><textarea defaultValue={post.caption} disabled={post.status === "uploading" || post.status === "published"} onBlur={(event) => void adjustPost(post.id, { caption: event.target.value })} /></label>{post.errorMessage && <small>{post.errorMessage}</small>}</article>)}{!schedule.publishReady && <p className="development-note">Draft saved. Connect every selected account to enable automatic publishing.</p>}</>}
      </section>
    </div>
  </div>;
}

function toLocalInput(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(0, 16);
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}
