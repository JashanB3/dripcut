import { Instagram, Minus, Plus, Sparkles, Youtube } from "lucide-react";

import {
  maximumClipCount,
  selectedDuration,
  selectedSegments,
  type AutoClipAction,
  type AutoClipState,
} from "../state/autoClipReducer";
import type { ClipDuration, OutputFormat } from "../models";

const durationOptions: ClipDuration[] = [15, 30, 45, 60, "custom"];
const outputOptions: Array<{ value: OutputFormat; label: string; detail: string }> = [
  { value: "portrait", label: "Portrait", detail: "9:16" },
  { value: "square", label: "Square", detail: "1:1" },
  { value: "landscape", label: "Landscape", detail: "16:9" },
];
export function ClipControls({ state, dispatch, onCreate, onToggleAI, starting, aiBusy }: { state: AutoClipState; dispatch: (action: AutoClipAction) => void; onCreate: () => void; onToggleAI: () => void; starting: boolean; aiBusy: boolean }) {
  const segments = selectedSegments(state);
  const max = maximumClipCount(state);
  const clipLabel = segments.length === 1 ? "clip" : "clips";

  return (
    <aside className="clip-controls">
      <div className="clip-controls__header">
        <span className="eyebrow">Clip plan</span>
        <h2>Two choices. That’s it.</h2>
        <p>Sequential equal clips are the default.</p>
      </div>
      <div className="control-group">
        <div className="control-label"><strong>Number of clips</strong><span>Up to {max} clips</span></div>
        <div className="clip-stepper">
          <button aria-label="Remove one clip" disabled={state.count <= 1} onClick={() => dispatch({ type: "set-count", value: state.count - 1 })}><Minus size={18} /></button>
          <strong>{state.count}</strong>
          <button aria-label="Add one clip" disabled={state.count >= max} onClick={() => dispatch({ type: "set-count", value: state.count + 1 })}><Plus size={18} /></button>
          <button className="max-button" disabled={max === 0 || state.count === max} onClick={() => dispatch({ type: "use-max" })}>MAX</button>
        </div>
      </div>
      <div className="control-group">
        <div className="control-label"><strong>Output format</strong><span>Choose a frame</span></div>
        <div className="output-format-options">
          {outputOptions.map((option) => <button key={option.value} type="button" data-selected={state.outputFormat === option.value} onClick={() => dispatch({ type: "set-output-format", value: option.value })}>
            <strong>{option.label}</strong><small>{option.detail}</small>
          </button>)}
        </div>
      </div>
      <div className="control-group">
        <div className="control-label"><strong>Clip duration</strong><span>{selectedDuration(state)} seconds</span></div>
        <div className="duration-options">
          {durationOptions.map((option) => (
            <button
              key={option}
              data-selected={state.durationChoice === option}
              onClick={() => dispatch({ type: "set-duration", value: option })}
            >
              {option === "custom" ? "Custom" : `${option}s`}
            </button>
          ))}
        </div>
        {state.durationChoice === "custom" && (
          <label className="custom-duration"><span>Custom seconds</span><input type="number" min="5" max="300" value={state.customDuration} onChange={(event) => dispatch({ type: "set-custom-duration", value: Number(event.target.value) })} /></label>
        )}
      </div>
      <div className="control-group">
        <div className="control-label"><strong>Destination</strong><span>Choose one or both</span></div>
        <div className="platform-options">
          <button type="button" data-selected={state.platforms.includes("youtube")} onClick={() => dispatch({ type: "toggle-platform", platform: "youtube" })}><Youtube size={17} /> YouTube Shorts</button>
          <button type="button" data-selected={state.platforms.includes("instagram")} onClick={() => dispatch({ type: "toggle-platform", platform: "instagram" })}><Instagram size={17} /> Instagram Reels</button>
        </div>
      </div>
      <div className="control-group ai-mode-control">
        <div className="control-label"><strong>AI highlight mode</strong><span>{state.aiEnabled ? "Transcript-scored" : "Off"}</span></div>
        <button type="button" className="ai-toggle" aria-pressed={state.aiEnabled} data-selected={state.aiEnabled} disabled={aiBusy} onClick={onToggleAI}><Sparkles size={16} /> {aiBusy ? "Finding strong moments…" : state.aiEnabled ? "Refresh viral recommendations" : "Find my best moments"}</button>
        <small>AI scores hooks, completeness, retention, and shareability for the selected destination.</small>
      </div>
      <label className="caption-option">
        <input type="checkbox" aria-label="Auto captions" checked={state.autoCaptions} onChange={() => dispatch({ type: "toggle-captions" })} />
        <span><strong>Auto captions</strong><small>Burn readable captions into every exported clip.</small></span>
      </label>
      <div className="clip-plan-summary">
        <span>Sequential</span>
        <strong>{segments.length} of {max} {clipLabel} · {Math.round(segments.reduce((sum, item) => sum + item.duration, 0))} seconds · portrait</strong>
      </div>
      {segments.length === 0 && <p className="clip-count-warning">Choose a shorter duration to create a clip.</p>}
      <button className="create-clips-preview" disabled={segments.length === 0 || starting} onClick={onCreate}>{starting ? "Starting render…" : `Create ${segments.length} ${clipLabel}`}</button>
    </aside>
  );
}
