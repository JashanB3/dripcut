import { FileVideo2, Link2, LoaderCircle, Upload, Youtube } from "lucide-react";
import { useRef, useState } from "react";

export function SourcePicker({ onFile, onYouTube, busy, progress, stage }: {
  onFile: (file: File) => void;
  onYouTube: (url: string, rightsConfirmed: boolean) => void;
  busy: "upload" | "youtube" | null;
  progress: number;
  stage: string;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [url, setUrl] = useState("");
  const [urlState, setUrlState] = useState<"idle" | "invalid">("idle");
  const [rightsConfirmed, setRightsConfirmed] = useState(false);

  const submitUrl = () => {
    try {
      const parsed = new URL(url.trim());
      const validHost = ["youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"].includes(parsed.hostname);
      if (validHost && rightsConfirmed) onYouTube(url.trim(), true);
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
        <p>Upload it here or check a supported YouTube URL. Nothing is analyzed unless you ask for AI recommendations later.</p>
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
          <span className="youtube-source-card__icon"><Youtube size={25} /></span>
          <strong>Paste YouTube link</strong>
          <p>{busy === "youtube" ? `${stage || "Connecting to YouTube"} · ${progress}%` : "Check a public YouTube URL before importing."}</p>
          <label data-state={urlState}>
            <Link2 size={17} />
            <input
              value={url}
              onChange={(event) => { setUrl(event.target.value); setUrlState("idle"); }}
              disabled={busy !== null}
              onKeyDown={(event) => event.key === "Enter" && submitUrl()}
              placeholder="https://youtube.com/watch?v=..."
              aria-label="YouTube video URL"
            />
          </label>
          {urlState === "invalid" && <small className="source-error">Enter a valid YouTube URL and confirm your permission.</small>}
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
