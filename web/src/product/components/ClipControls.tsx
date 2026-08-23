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
const outputFormats: Array<[OutputFormat, string, string]> = [
  ["portrait", "Portrait", "9:16"],
  ["landscape", "Landscape", "16:9"],
  ["square", "Square", "1:1"],
  ["source", "Original", "Source"],
];

export function ClipControls({ state, dispatch, onCreate, starting }: { state: AutoClipState; dispatch: (action: AutoClipAction) => void; onCreate: () => void; starting: boolean }) {
  const max = maximumClipCount(state);
  const segments = selectedSegments(state);
  const accepted = state.acceptedRecommendationIds.length;
  const clipLabel = segments.length === 1 ? "clip" : "clips";

  return (
    <aside className="clip-controls">
      <div className="clip-controls__header">
        <span className="eyebrow">Clip plan</span>
        <h2>Two choices. That’s it.</h2>
        <p>Sequential equal clips are the default.</p>
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
        <div className="control-label"><strong>Number of clips</strong><span>Up to {max} complete clips</span></div>
        <div className="clip-stepper">
          <button aria-label="Remove one clip" disabled={state.count <= 0} onClick={() => dispatch({ type: "set-count", value: state.count - 1 })}><Minus size={18} /></button>
          <strong>{state.count}</strong>
          <button aria-label="Add one clip" disabled={state.count >= max} onClick={() => dispatch({ type: "set-count", value: state.count + 1 })}><Plus size={18} /></button>
          <button className="max-button" disabled={max === 0} onClick={() => dispatch({ type: "use-max" })}>MAX</button>
        </div>
      </div>
      <div className="control-group">
        <div className="control-label"><strong>Destinations</strong><span>Choose one or both</span></div>
        <div className="platform-options">
          <button data-selected={state.platforms.includes("youtube")} onClick={() => dispatch({ type: "toggle-platform", platform: "youtube" })}><Youtube size={17} /> YouTube Shorts</button>
          <button data-selected={state.platforms.includes("instagram")} onClick={() => dispatch({ type: "toggle-platform", platform: "instagram" })}><Instagram size={17} /> Instagram Reels</button>
        </div>
      </div>
      <div className="control-group">
        <div className="control-label"><strong>Output format</strong><span>Applied to every clip</span></div>
        <div className="output-format-options">
          {outputFormats.map(([value, label, ratio]) => (
            <button key={value} data-selected={state.outputFormat === value} onClick={() => dispatch({ type: "set-output-format", value })}>
              <strong>{label}</strong><small>{ratio}</small>
            </button>
          ))}
        </div>
      </div>
      <label className="caption-option">
        <input type="checkbox" checked={state.autoCaptions} onChange={() => dispatch({ type: "toggle-captions" })} />
        <span><strong>Auto captions</strong><small>Transcribe once, then burn phone-safe captions into each clip.</small></span>
      </label>
      <div className="ai-option" data-enabled={state.aiEnabled}>
        <div><span><Sparkles size={17} /></span><p><strong>Find Viral Moments with AI</strong><small>Optional · off by default · demo recommendations</small></p></div>
        <button role="switch" aria-checked={state.aiEnabled} aria-label="Find Viral Moments with AI" onClick={() => dispatch({ type: "toggle-ai" })}><i /></button>
      </div>
      <div className="clip-plan-summary">
        <span>{state.aiEnabled && accepted ? "AI-selected" : "Sequential"}</span>
        <strong>{segments.length} {clipLabel} · {Math.round(segments.reduce((sum, item) => sum + item.duration, 0))} seconds · {state.outputFormat}</strong>
      </div>
      <div className="preview-disclosure"><Sparkles size={15} /><span><strong>Fast render</strong>Compatible videos use stream copy so clips can finish without re-encoding.</span></div>
      {max === 0 && <p className="clip-count-warning">Choose a shorter duration to create a complete clip.</p>}
      <button className="create-clips-preview" disabled={segments.length === 0 || starting} onClick={onCreate}>{starting ? "Starting render…" : `Create ${segments.length} ${clipLabel}`}</button>
    </aside>
  );
}
