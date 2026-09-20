import { CalendarClock, CheckSquare2, Download, Square } from "lucide-react";
import { useState } from "react";

import { youtubePublishingBeta } from "../launch";
import type { ApiJob } from "../models";

const formatBytes = (bytes: number) => {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};

export function ClipResults({ job, onBack, onSchedule }: { job: ApiJob; onBack: () => void; onSchedule?: () => void }) {
  const clips = job.artifacts.filter((artifact) => artifact.kind === "clip");
  const [selected, setSelected] = useState(() => clips.map((clip) => clip.id));
  const allSelected = selected.length === clips.length;

  const downloadSelected = () => {
    clips.filter((clip) => selected.includes(clip.id)).forEach((clip, index) => {
      window.setTimeout(() => {
        const anchor = document.createElement("a");
        anchor.href = clip.downloadUrl;
        anchor.download = clip.name;
        anchor.click();
      }, index * 250);
    });
  };

  return (
    <section className="clip-results-page">
      <header className="results-header">
        <div><span className="preview-badge">{job.elapsed > 0 ? `Render complete · ${job.elapsed.toFixed(1)} seconds` : "Saved render"}</span><h1>Your clips are ready.</h1><p>Preview, download, or schedule each finished clip.</p></div>
        <div className="results-header__actions"><button className="secondary-action" onClick={onBack}>Edit clip plan</button>{youtubePublishingBeta && onSchedule && <button className="secondary-action" onClick={onSchedule}><CalendarClock size={16} /> Schedule</button>}{job.zipArtifact && <a className="primary-action" href={job.zipArtifact.downloadUrl} download><Download size={17} /> Download ZIP</a>}</div>
      </header>
      <div className="results-selection-bar">
        <button onClick={() => setSelected(allSelected ? [] : clips.map((item) => item.id))}>{allSelected ? <CheckSquare2 size={17} /> : <Square size={17} />} Select all</button>
        <span>{selected.length} selected</span>
        <div />
        <button disabled={selected.length === 0} onClick={downloadSelected}><Download size={15} /> Download selected</button>
        {job.zipArtifact && <a href={job.zipArtifact.downloadUrl} download>Download ZIP · {formatBytes(job.zipArtifact.sizeBytes)}</a>}
      </div>
      <div className="clip-result-grid">
        {clips.map((clip) => {
          const checked = selected.includes(clip.id);
          return (
            <article key={clip.id} className="clip-result-card" data-selected={checked}>
              <button className="result-select" aria-label={`${checked ? "Deselect" : "Select"} ${clip.name}`} onClick={() => setSelected(checked ? selected.filter((id) => id !== clip.id) : [...selected, clip.id])}>{checked ? <CheckSquare2 size={17} /> : <Square size={17} />}</button>
              <div className="clip-result-card__media">{clip.streamUrl && <video controls playsInline preload="metadata" src={clip.streamUrl} />}</div>
              <div className="clip-result-card__copy"><div><span>Clip {clip.index ?? ""}</span><small>{clip.duration ? `${Math.round(clip.duration)} sec · ` : ""}{formatBytes(clip.sizeBytes)}</small></div><p><CheckSquare2 size={14} /><span><strong>Ready to post</strong><small>{clip.outputFormat} · {clip.captionsEnabled ? "captions on" : "captions off"} · {clip.name}</small></span></p></div>
              <div className="clip-result-card__actions"><a href={clip.downloadUrl} download><Download size={14} /> Download</a></div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
