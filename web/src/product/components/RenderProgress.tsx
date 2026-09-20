import { AlertCircle, Check, Download, LoaderCircle, Sparkles } from "lucide-react";
import { useEffect } from "react";

import { getClipJob } from "../api/client";
import type { ApiJob } from "../models";

export function RenderProgress({ job, onUpdate, onComplete, onBack }: {
  job: ApiJob;
  onUpdate: (job: ApiJob) => void;
  onComplete: (job: ApiJob) => void;
  onBack: () => void;
}) {
  useEffect(() => {
    if (job.status === "succeeded" || job.status === "failed" || job.status === "cancelled") return;
    let active = true;
    let timer: number | undefined;
    const poll = async () => {
      const startedAt = Date.now();
      let terminal = false;
      try {
        const latest = await getClipJob(job.id);
        if (!active) return;
        onUpdate(latest);
        if (latest.status === "succeeded") onComplete(latest);
        terminal = latest.status === "succeeded" || latest.status === "failed" || latest.status === "cancelled";
      } catch {
        // A brief API restart should not discard the render already running.
      } finally {
        // Keep status-to-screen lag under two seconds without overlapping calls.
        const delay = Math.max(0, 1_000 - (Date.now() - startedAt));
        if (active && !terminal) timer = window.setTimeout(() => void poll(), delay);
      }
    };
    void poll();
    return () => {
      active = false;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [job.id, job.status, onComplete, onUpdate]);

  const clips = job.artifacts.filter((artifact) => artifact.kind === "clip");
  const failed = job.status === "failed" || job.status === "cancelled";

  return (
    <section className="render-preview-page">
      <div className="render-preview__visual">
        <span className="render-orbit render-orbit--one" />
        <span className="render-orbit render-orbit--two" />
        <div className="render-preview__mark">{failed ? <AlertCircle size={28} /> : job.status === "succeeded" ? <Check size={28} /> : <Sparkles size={28} />}</div>
      </div>
      <div className="render-preview__content">
        <span className="preview-badge">Real render job · {job.id}</span>
        <h1>{failed ? "This render stopped early." : job.status === "succeeded" ? "Your downloads are ready." : "Creating your clips now."}</h1>
        <p>{failed ? job.error : job.stage || "Waiting for a worker"}</p>
        {failed && job.hint && <p className="render-error-hint">{job.hint}</p>}
        <div className="render-progress-bar"><span style={{ width: `${job.percent}%` }} /></div>
        <div className="render-live-status">
          <span>{job.status === "running" ? <LoaderCircle className="spin" size={17} /> : <Check size={17} />}{job.percent}%</span>
          <span>{job.elapsed.toFixed(1)}s elapsed</span>
          <span>{clips.length} clips available</span>
        </div>
        {clips.length > 0 && failed && (
          <div className="partial-downloads">
            <strong>Completed clips were preserved</strong>
            {clips.map((clip) => <a key={clip.id} href={clip.downloadUrl} download><Download size={14} /> {clip.name}</a>)}
          </div>
        )}
        <button className="secondary-action" onClick={onBack}>Back to clip plan</button>
      </div>
    </section>
  );
}
