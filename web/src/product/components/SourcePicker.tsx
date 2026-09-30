import { AlertTriangle, FileVideo2, Link2, LoaderCircle, RotateCcw, Upload } from "lucide-react";
import { useRef, useState } from "react";

export function SourcePicker({ onFile, onYouTube, busy, progress, stage, youtubeFailed }: {
  onFile: (file: File) => void;
  onYouTube: (url: string, rightsConfirmed: boolean) => void;
  busy: "upload" | "youtube" | null;
  progress: number;
  stage: string;
  youtubeFailed: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [url, setUrl] = useState(() => window.localStorage.getItem("dripcut.pendingVideoUrl") ?? "");
  const [urlState, setUrlState] = useState<"idle" | "invalid">("idle");
  const [rightsConfirmed, setRightsConfirmed] = useState(false);

  const submitUrl = () => {
    try {
      const parsed = new URL(url.trim());
      const validLink = ["http:", "https:"].includes(parsed.protocol) && Boolean(parsed.hostname);
       if (validLink && rightsConfirmed) {
         window.localStorage.removeItem("dripcut.pendingVideoUrl");
         onYouTube(url.trim(), true);
       }
      else setUrlState("invalid");
    } catch {
      setUrlState("invalid");
    }
  };

  return (
    <section className="source-step">
      <div className="source-step__intro">
        <span className="eyebrow">Step 1 · Source</span>
        <h1>Start with one long video.</h1>
        <p>Upload it here or paste a public link from a supported video website. Nothing is analyzed unless you ask for AI recommendations later.</p>
      </div>
      <div className="source-options">
        <button className="upload-source-card" disabled={busy !== null} onClick={() => input.current?.click()}>
          <span>{busy === "upload" ? <LoaderCircle className="spin" size={25} /> : <Upload size={25} />}</span>
          <strong>{busy === "upload" ? `Uploading ${progress}%` : "Upload video"}</strong>
          <p>{busy === "upload" ? "Saving and checking your source" : "MP4, MOV or WebM from your device"}</p>
          <em>{busy === "upload" ? "Please keep this page open" : "Choose a file"}</em>
        </button>
        <div className="source-divider"><span>or</span></div>
        <div className="youtube-source-card">
          <span className="youtube-source-card__icon"><Link2 size={25} /></span>
          <strong>Paste a video link</strong>
          <p>{busy === "youtube" ? `${stage || "Connecting to the video source"} · ${progress}%` : "YouTube and hundreds of supported public video sites."}</p>
          <label data-state={urlState}>
            <Link2 size={17} />
            <input
              value={url}
              onChange={(event) => { setUrl(event.target.value); setUrlState("idle"); }}
              disabled={busy !== null}
              onKeyDown={(event) => event.key === "Enter" && submitUrl()}
              placeholder="https://video-site.com/watch/..."
               aria-label="YouTube video URL or supported public link"
            />
          </label>
          {urlState === "invalid" && <small className="source-error">Enter a valid public video URL and confirm your permission.</small>}
          <label className="rights-confirmation">
            <input
              type="checkbox"
              checked={rightsConfirmed}
              disabled={busy !== null}
              onChange={(event) => {
                setRightsConfirmed(event.target.checked);
                setUrlState("idle");
              }}
            />
            <span>I own this video or have permission to edit and republish it.</span>
          </label>
          <button className="check-link-button" disabled={!url.trim() || !rightsConfirmed || busy !== null} onClick={submitUrl}>
            {busy === "youtube" ? <><LoaderCircle className="spin" size={16} /> Importing video…</> : "Import video"}
          </button>
        </div>
      </div>
      {youtubeFailed && (
        <div className="youtube-recovery" role="status">
          <AlertTriangle size={20} />
          <span>
            <strong>Keep going with this project</strong>
            <small>Retry the public link, or upload a copy you are allowed to use. Your selected template and clip settings stay in place.</small>
          </span>
          <button disabled={busy !== null || !url.trim() || !rightsConfirmed} onClick={submitUrl}>
             <RotateCcw size={15} /> Retry link
          </button>
          <button className="youtube-recovery__upload" disabled={busy !== null} onClick={() => input.current?.click()}>
            <Upload size={15} /> Upload video instead
          </button>
        </div>
      )}
      <input
        ref={input}
        className="dc-visually-hidden"
        type="file"
        accept="video/mp4,video/quicktime,video/webm,video/*"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) onFile(file);
          event.currentTarget.value = "";
        }}
      />
      <div className="source-trust"><FileVideo2 size={17} /><span>Your source is prepared once, then reused for every clip in this project.</span></div>
    </section>
  );
}
