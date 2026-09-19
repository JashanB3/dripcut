import { Youtube } from "lucide-react";

import {
  selectedDuration,
  selectedSegments,
  type AutoClipAction,
  type AutoClipState,
} from "../state/autoClipReducer";
import type { ClipDuration } from "../models";

const durationOptions: ClipDuration[] = [15, 30, 45, 60, "custom"];
export function ClipControls({ state, dispatch, onCreate, starting }: { state: AutoClipState; dispatch: (action: AutoClipAction) => void; onCreate: () => void; onToggleAI: () => void; starting: boolean; aiBusy: boolean }) {
  const segments = selectedSegments(state);
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
        <div className="control-label"><strong>Destination</strong><span>YouTube MVP</span></div>
        <div className="platform-options">
          <button data-selected><Youtube size={17} /> YouTube Shorts</button>
        </div>
      </div>
      <div className="clip-plan-summary">
        <span>Sequential</span>
        <strong>{segments.length} {clipLabel} · {Math.round(segments.reduce((sum, item) => sum + item.duration, 0))} seconds · portrait</strong>
      </div>
      {segments.length === 0 && <p className="clip-count-warning">Choose a shorter duration to create a clip.</p>}
      <button className="create-clips-preview" disabled={segments.length === 0 || starting} onClick={onCreate}>{starting ? "Starting render…" : `Create ${segments.length} ${clipLabel}`}</button>
    </aside>
  );
}
