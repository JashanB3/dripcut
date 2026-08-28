import { Check, Pause, Play, Sparkles, X } from "lucide-react";
import { type RefObject, useRef } from "react";

import { useVideoThumbnails } from "../hooks/useVideoThumbnails";
import type { RuntimeSource } from "../models";
import { selectedSegments, type AutoClipAction, type AutoClipState } from "../state/autoClipReducer";

const formatTime = (seconds: number) => {
  const safe = Math.max(0, Math.floor(seconds));
  return `${Math.floor(safe / 60)}:${String(safe % 60).padStart(2, "0")}`;
};

export function SourceTimeline({ state, dispatch, runtime, videoRef }: {
  state: AutoClipState;
  dispatch: (action: AutoClipAction) => void;
  runtime: RuntimeSource;
  videoRef: RefObject<HTMLVideoElement | null>;
}) {
  const timeline = useRef<HTMLDivElement>(null);
  const duration = state.source?.duration ?? 1;
  const thumbnails = useVideoThumbnails(runtime.url, duration);
  const segments = selectedSegments(state);
  const activeRecommendations = state.recommendations.filter((item) => !state.ignoredRecommendationIds.includes(item.id));

  const togglePlayback = async () => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) await video.play(); else video.pause();
  };

  const seek = (clientX: number) => {
    const bounds = timeline.current?.getBoundingClientRect();
    if (!bounds || !videoRef.current) return;
    const value = Math.max(0, Math.min(duration, ((clientX - bounds.left) / bounds.width) * duration));
    videoRef.current.currentTime = value;
    dispatch({ type: "set-current-time", value });
  };

  return (
    <section className="source-workspace">
      <div className="source-player">
        <video
          ref={videoRef}
          src={runtime.url}
          playsInline
          preload="metadata"
          onClick={() => void togglePlayback()}
          onPlay={() => dispatch({ type: "set-playing", value: true })}
          onPause={() => dispatch({ type: "set-playing", value: false })}
          onTimeUpdate={(event) => dispatch({ type: "set-current-time", value: event.currentTarget.currentTime })}
        />
        <button className="source-player__play" onClick={() => void togglePlayback()} aria-label={state.playing ? "Pause video" : "Play video"}>
          {state.playing ? <Pause size={19} fill="currentColor" /> : <Play size={19} fill="currentColor" />}
        </button>
        <div className="source-player__meta"><strong>{state.source?.name}</strong><span>{formatTime(state.currentTime)} / {formatTime(duration)}</span></div>
      </div>
      <div className="source-timeline-section">
        <div className="timeline-heading"><div><span className="eyebrow">Full source timeline</span><h2>See exactly what becomes a clip.</h2></div><span>{formatTime(duration)} source</span></div>
        <div className="source-timeline" ref={timeline} onPointerDown={(event) => seek(event.clientX)}>
          <div className="thumbnail-strip">
            {Array.from({ length: 12 }, (_, index) => <span key={index} style={thumbnails[index] ? { backgroundImage: `url(${thumbnails[index]})` } : undefined} />)}
          </div>
          <div className="timeline-time-labels">{Array.from({ length: 7 }, (_, index) => <span key={index} style={{ left: `${(index / 6) * 100}%` }}>{formatTime((duration / 6) * index)}</span>)}</div>
          <div className="segment-lane" aria-label="Selected clip regions">
            {segments.map((segment) => (
              <button
                key={segment.id}
                className={`segment-region segment-region--${segment.strategy}`}
                style={{ left: `${(segment.start / duration) * 100}%`, width: `${(segment.duration / duration) * 100}%` }}
                onPointerDown={(event) => event.stopPropagation()}
                onClick={() => {
                  if (videoRef.current) videoRef.current.currentTime = segment.start;
                  dispatch({ type: "set-current-time", value: segment.start });
                }}
              ><span>Clip {segment.index}</span></button>
            ))}
          </div>
          {state.aiEnabled && (
            <div className="ai-recommendation-lane" aria-label="AI recommendation overlays">
              {activeRecommendations.map((item) => (
                <span
                  key={item.id}
                  data-accepted={state.acceptedRecommendationIds.includes(item.id)}
                  style={{ left: `${(item.start / duration) * 100}%`, width: `${((item.end - item.start) / duration) * 100}%` }}
                ><Sparkles size={11} /> {item.score}%</span>
              ))}
            </div>
          )}
          <span className="source-playhead" style={{ left: `${(state.currentTime / duration) * 100}%` }}><i /></span>
        </div>
        {state.aiEnabled && (
          <div className="ai-recommendations">
            <div className="ai-recommendations__heading"><span><Sparkles size={16} /> AI viral recommendations</span><small>Scored from the source transcript for your destination</small></div>
            <div className="recommendation-row">
              {state.recommendations.map((item) => {
                const accepted = state.acceptedRecommendationIds.includes(item.id);
                const ignored = state.ignoredRecommendationIds.includes(item.id);
                return (
                  <article key={item.id} data-state={accepted ? "accepted" : ignored ? "ignored" : "idle"}>
                    <div><strong>{formatTime(item.start)} – {formatTime(item.end)}</strong><span>{item.score}% potential</span></div>
                    <p>{item.label}<small>{item.reason}</small></p>
                    <div>
                      <button disabled={accepted} onClick={() => dispatch({ type: "accept-recommendation", id: item.id })}><Check size={13} /> {accepted ? "Using" : "Use clip"}</button>
                      <button disabled={ignored} onClick={() => dispatch({ type: "ignore-recommendation", id: item.id })}><X size={13} /> Ignore</button>
                    </div>
                  </article>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
