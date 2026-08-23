import {
  Crop,
  Maximize2,
  Pause,
  Play,
  RotateCcw,
  SlidersHorizontal,
  Upload,
  Volume2,
  VolumeX,
} from "lucide-react";
import { type RefObject, useEffect, useRef } from "react";

import { useEditor } from "../../editor/context";
import type { AssetReference } from "../../editor/types";
import { EmptyState, IconButton } from "../primitives/Controls";
import type { RuntimeMedia } from "./types";

const formatTime = (seconds: number) => {
  if (!Number.isFinite(seconds)) return "00:00";
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.floor(seconds % 60);
  return `${minutes.toString().padStart(2, "0")}:${remainder.toString().padStart(2, "0")}`;
};

export function VideoWorkspace({
  media,
  videoRef,
  onChooseMedia,
}: {
  media: RuntimeMedia | null;
  videoRef: RefObject<HTMLVideoElement | null>;
  onChooseMedia: () => void;
}) {
  const { state, dispatch } = useEditor();
  const frame = useRef<number | null>(null);
  const { playback, selection, project } = state.present;

  useEffect(() => {
    if (!playback.playing) {
      if (frame.current) cancelAnimationFrame(frame.current);
      return;
    }
    const update = () => {
      const video = videoRef.current;
      if (video) dispatch({ type: "set-playback", patch: { currentTime: video.currentTime } });
      frame.current = requestAnimationFrame(update);
    };
    frame.current = requestAnimationFrame(update);
    return () => {
      if (frame.current) cancelAnimationFrame(frame.current);
    };
  }, [dispatch, playback.playing, videoRef]);

  const togglePlayback = async () => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) await video.play();
    else video.pause();
  };

  const registerMetadata = () => {
    const video = videoRef.current;
    if (!video || !media) return;
    const asset: AssetReference = {
      id: media.id,
      name: media.name,
      kind: "video",
      mimeType: media.mimeType,
      duration: video.duration,
      width: video.videoWidth,
      height: video.videoHeight,
      source: { type: "local", assetKey: null },
    };
    dispatch({ type: "upsert-asset", asset });
    dispatch({ type: "set-playback", patch: { duration: video.duration, currentTime: 0 } });
    dispatch({ type: "select", selection: { kind: "clip", id: `video-${media.id}` } });
  };

  return (
    <main className="dc-workspace">
      <div className="dc-context-toolbar">
        <span className="dc-context-toolbar__label">
          {selection?.kind === "clip" ? "Video clip" : selection?.kind === "asset" ? "Media asset" : "Canvas"}
        </span>
        <span className="dc-context-toolbar__separator" />
        <button disabled title="Canvas transforms are intentionally deferred"><Crop size={15} /> Crop</button>
        <button disabled title="Canvas transforms are intentionally deferred"><RotateCcw size={15} /> Rotate</button>
        <button disabled title="Video adjustments are intentionally deferred"><SlidersHorizontal size={15} /> Adjust</button>
        <div className="dc-context-toolbar__spacer" />
        <span>{project.canvas.aspectRatio}</span>
        <span>{Math.round(project.canvas.zoom * 100)}%</span>
      </div>

      <section className="dc-canvas-stage" onClick={() => dispatch({ type: "select", selection: { kind: "canvas", id: "canvas" } })}>
        <div
          className="dc-canvas-frame"
          data-aspect={project.canvas.aspectRatio}
          data-selected={selection?.kind === "canvas"}
        >
          {media ? (
            <video
              ref={videoRef}
              src={media.url}
              preload="metadata"
              playsInline
              onLoadedMetadata={registerMetadata}
              onPlay={() => dispatch({ type: "set-playback", patch: { playing: true } })}
              onPause={() => dispatch({ type: "set-playback", patch: { playing: false } })}
              onEnded={() => dispatch({ type: "set-playback", patch: { playing: false } })}
              onVolumeChange={(event) => dispatch({ type: "set-playback", patch: { volume: event.currentTarget.volume } })}
              onClick={(event) => {
                event.stopPropagation();
                void togglePlayback();
              }}
            />
          ) : (
            <EmptyState
              icon={<Upload size={22} />}
              title="Add your first video"
              body="Your preview and timeline will appear here."
              action={<button className="dc-text-action" onClick={(event) => { event.stopPropagation(); onChooseMedia(); }}>Choose video</button>}
            />
          )}
        </div>
      </section>

      <div className="dc-transport">
        <IconButton label={playback.playing ? "Pause" : "Play"} disabled={!media} onClick={() => void togglePlayback()}>
          {playback.playing ? <Pause size={18} fill="currentColor" /> : <Play size={18} fill="currentColor" />}
        </IconButton>
        <span className="dc-transport__time">
          <strong>{formatTime(playback.currentTime)}</strong>
          <span>/</span>
          <span>{formatTime(playback.duration)}</span>
        </span>
        <div className="dc-transport__spacer" />
        <IconButton
          label={playback.volume === 0 ? "Unmute" : "Mute"}
          disabled={!media}
          onClick={() => {
            const video = videoRef.current;
            if (!video) return;
            video.volume = video.volume === 0 ? 0.8 : 0;
          }}
        >
          {playback.volume === 0 ? <VolumeX size={17} /> : <Volume2 size={17} />}
        </IconButton>
        <input
          className="dc-volume"
          aria-label="Volume"
          type="range"
          min="0"
          max="1"
          step="0.05"
          value={playback.volume}
          disabled={!media}
          onChange={(event) => {
            const video = videoRef.current;
            if (video) video.volume = Number(event.target.value);
          }}
        />
        <IconButton label="Fullscreen preview" disabled={!media} onClick={() => void videoRef.current?.requestFullscreen()}>
          <Maximize2 size={17} />
        </IconButton>
      </div>
    </main>
  );
}
