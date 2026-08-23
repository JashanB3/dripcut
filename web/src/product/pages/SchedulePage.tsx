import { CalendarClock, CheckCircle2, Instagram, Youtube } from "lucide-react";
import { useEffect, useState } from "react";

import { fetchProjects, fetchSocialConnections, saveSchedule } from "../api/client";
import type { ApiProject, Platform, SavedSchedule, SocialConnection } from "../models";

export function SchedulePage() {
  const [projects, setProjects] = useState<ApiProject[]>([]);
  const [projectId, setProjectId] = useState("");
  const [connections, setConnections] = useState<SocialConnection[]>([]);
  const [platforms, setPlatforms] = useState<Platform[]>(["youtube", "instagram"]);
  const [interval, setInterval] = useState(1440);
  const [startAt, setStartAt] = useState("");
  const [caption, setCaption] = useState("{clip} #shorts #reels");
  const [schedule, setSchedule] = useState<SavedSchedule | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void Promise.all([fetchProjects(100), fetchSocialConnections()]).then(([items, statuses]) => {
      const ready = items.filter((item) => item.downloadArtifactId && item.status === "completed");
      setProjects(ready);
      setProjectId(ready[0]?.id ?? "");
      setConnections(statuses);
    }).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Scheduling data could not load."));
  }, []);

  const toggle = (platform: Platform) => {
    const next = platforms.includes(platform) ? platforms.filter((item) => item !== platform) : [...platforms, platform];
    if (next.length) setPlatforms(next);
  };

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      setSchedule(await saveSchedule({ projectId, platforms, intervalMinutes: interval, startAt: startAt || "now", caption }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The schedule could not be saved.");
    } finally {
      setBusy(false);
    }
  };

  return <div className="schedule-page product-page">
    <header className="page-heading-row"><div><span className="eyebrow">Publishing</span><h1>Schedule your finished clips.</h1><p>Save a durable posting plan. Publishing unlocks only when official platform credentials are configured.</p></div></header>
    {error && <div className="source-error-banner">{error}</div>}
    <div className="connection-cards">{connections.map((connection) => <article key={connection.platform} data-connected={connection.connected}>{connection.platform === "youtube" ? <Youtube /> : <Instagram />}<div><strong>{connection.label}</strong><span>{connection.detail}</span><small>{connection.configured ? "Credentials configured; OAuth verification still required." : connection.setupHint}</small></div><em>{connection.connected ? "Connected" : connection.configured ? "Setup incomplete" : "Not connected"}</em></article>)}</div>
    <div className="schedule-workspace">
      <section className="schedule-builder">
        <label><span>Finished project</span><select value={projectId} onChange={(event) => setProjectId(event.target.value)}>{projects.map((project) => <option key={project.id} value={project.id}>{project.title}</option>)}</select></label>
        <div><span>Platforms</span><div className="platform-options"><button data-selected={platforms.includes("youtube")} onClick={() => toggle("youtube")}><Youtube size={16} /> YouTube</button><button data-selected={platforms.includes("instagram")} onClick={() => toggle("instagram")}><Instagram size={16} /> Instagram</button></div></div>
        <label><span>Start</span><input type="datetime-local" value={startAt} onChange={(event) => setStartAt(event.target.value)} /></label>
        <label><span>Interval</span><select value={interval} onChange={(event) => setInterval(Number(event.target.value))}><option value="360">Every 6 hours</option><option value="720">Every 12 hours</option><option value="1440">Daily</option><option value="2880">Every 2 days</option></select></label>
        <label><span>Caption template</span><textarea value={caption} onChange={(event) => setCaption(event.target.value)} /></label>
        <button className="primary-action" disabled={!projectId || busy} onClick={() => void save()}><CalendarClock size={16} /> {busy ? "Saving…" : "Save schedule"}</button>
      </section>
      <section className="saved-schedule">
        {!schedule && <div className="projects-empty projects-empty--large"><CalendarClock size={28} /><strong>No schedule preview yet</strong><span>Choose a finished project and save its posting rhythm.</span></div>}
        {schedule && <><header><CheckCircle2 size={20} /><div><strong>{schedule.posts.length} posts planned</strong><span>{schedule.archiveName}</span></div><em>{schedule.publishReady ? "Ready to publish" : "Draft only"}</em></header>{schedule.posts.map((post, index) => <article key={`${post.platform}-${post.clipName}-${index}`}><strong>{post.clipName}</strong><span>{post.platform} · {post.publishAt}</span><small>{post.caption}</small></article>)}{!schedule.publishReady && <p className="development-note">Draft saved. Automatic publishing remains disabled until every selected account passes the credential check.</p>}</>}
      </section>
    </div>
  </div>;
}
