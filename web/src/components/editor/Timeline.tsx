import { Captions, Film, Lock, Music2, Type, ZoomIn, ZoomOut } from "lucide-react";
import type { PointerEvent as ReactPointerEvent, RefObject } from "react";
import { useRef } from "react";

import { useEditor } from "../../editor/context";
import type { TimelineTrack } from "../../editor/types";
import { IconButton } from "../primitives/Controls";

const trackIcons = { video: Film, audio: Music2, text: Type, caption: Captions };

export function Timeline({ videoRef }: { videoRef: RefObject<HTMLVideoElement | null> }) {
  const { state, dispatch } = useEditor();
  const body = useRef<HTMLDivElement>(null);
  const { project, playback, selection } = state.present;
  const duration = Math.max(playback.duration || project.timeline.duration, 0.1);
  const zoom = project.timeline.zoom;

  const seekFromPointer = (event: ReactPointerEvent<HTMLElement>) => {
    const target = body.current;
    if (!target) return;
    const bounds = target.getBoundingClientRect();
    const contentWidth = target.scrollWidth - 108;
    const x = event.clientX - bounds.left + target.scrollLeft - 108;
    const time = Math.max(0, Math.min(duration, (x / contentWidth) * duration));
    if (videoRef.current) videoRef.current.currentTime = time;
    dispatch({ type: "set-playback", patch: { currentTime: time } });
  };

  const changeZoom = (next: number) => {
    dispatch({ type: "set-timeline-zoom", zoom: Math.max(0.75, Math.min(4, next)) });
  };

  return (
    <section className="dc-timeline" aria-label="Timeline">
      <div className="dc-timeline__toolbar">
        <strong>Timeline</strong>
        <span>{project.timeline.tracks.length} tracks</span>
        <div className="dc-timeline__spacer" />
        <IconButton label="Zoom out" onClick={() => changeZoom(zoom - 0.25)}><ZoomOut size={16} /></IconButton>
        <input
          aria-label="Timeline zoom"
          type="range"
          min="0.75"
          max="4"
          step="0.25"
          value={zoom}
          onChange={(event) => changeZoom(Number(event.target.value))}
        />
        <IconButton label="Zoom in" onClick={() => changeZoom(zoom + 0.25)}><ZoomIn size={16} /></IconButton>
        <span className="dc-zoom-label">{Math.round(zoom * 100)}%</span>
      </div>
      <div className="dc-timeline__body" ref={body} onPointerDown={seekFromPointer}>
        <div className="dc-timeline__content" style={{ width: `${Math.max(100, zoom * 100)}%` }}>
          <div className="dc-ruler-label" />
          <div className="dc-ruler">
            {Array.from({ length: 9 }, (_, index) => {
              const value = (duration / 8) * index;
              return <span key={index} style={{ left: `${(index / 8) * 100}%` }}>{value.toFixed(value < 10 ? 1 : 0)}s</span>;
            })}
          </div>
          {project.timeline.tracks.map((track) => (
            <TimelineTrackRow
              key={track.id}
              track={track}
              duration={duration}
              selectedId={selection?.id ?? null}
              onSelect={(id) => dispatch({ type: "select", selection: { kind: "clip", id } })}
            />
          ))}
          <div
            className="dc-playhead"
            style={{ left: `calc(108px + (100% - 108px) * ${playback.currentTime / duration})` }}
          >
            <span />
          </div>
        </div>
      </div>
    </section>
  );
}

function TimelineTrackRow({ track, duration, selectedId, onSelect }: {
  track: TimelineTrack;
  duration: number;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const Icon = trackIcons[track.kind];
  return (
    <div className="dc-track">
      <div className="dc-track__label"><Icon size={14} /><span>{track.name}</span>{track.locked && <Lock size={12} />}</div>
      <div className="dc-track__lane">
        {track.clips.length === 0 ? <span className="dc-track__empty">No {track.kind} layers</span> : track.clips.map((clip) => (
          <button
            key={clip.id}
            className={`dc-timeline-clip dc-timeline-clip--${clip.color}`}
            data-selected={selectedId === clip.id}
            style={{ left: `${(clip.start / duration) * 100}%`, width: `${((clip.end - clip.start) / duration) * 100}%` }}
            onPointerDown={(event) => event.stopPropagation()}
            onClick={() => onSelect(clip.id)}
          >
            {clip.label}
          </button>
        ))}
      </div>
    </div>
  );
}
