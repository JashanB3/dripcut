import { Film, SlidersHorizontal } from "lucide-react";

import { useEditor } from "../../editor/context";

export function PropertyPanel() {
  const { state, dispatch } = useEditor();
  const { project, selection } = state.present;
  const selectedClip = project.timeline.tracks
    .flatMap((track) => track.clips)
    .find((clip) => clip.id === selection?.id);

  return (
    <aside className="dc-property-panel">
      <div className="dc-panel-heading">
        <h2>{selectedClip ? "Video properties" : "Canvas"}</h2>
        {selectedClip ? <Film size={17} /> : <SlidersHorizontal size={17} />}
      </div>
      {selectedClip ? (
        <div className="dc-properties">
          <label>Clip name<input value={selectedClip.label} readOnly /></label>
          <div className="dc-property-grid">
            <label>Start<input value={`${selectedClip.start.toFixed(2)}s`} readOnly /></label>
            <label>Duration<input value={`${(selectedClip.end - selectedClip.start).toFixed(2)}s`} readOnly /></label>
          </div>
          <div className="dc-property-section">
            <h3>Transform</h3>
            <div className="dc-property-grid">
              <label>Position X<input value="0" readOnly /></label>
              <label>Position Y<input value="0" readOnly /></label>
              <label>Scale<input value="100%" readOnly /></label>
              <label>Rotation<input value="0°" readOnly /></label>
            </div>
          </div>
        </div>
      ) : (
        <div className="dc-properties">
          <label>
            Format
            <select
              value={project.canvas.aspectRatio}
              onChange={(event) => dispatch({
                type: "set-canvas-aspect",
                aspectRatio: event.target.value as typeof project.canvas.aspectRatio,
              })}
            >
              <option value="16:9">Landscape · 16:9</option>
              <option value="9:16">Portrait · 9:16</option>
              <option value="1:1">Square · 1:1</option>
            </select>
          </label>
          <div className="dc-property-grid">
            <label>Width<input value={project.canvas.width} readOnly /></label>
            <label>Height<input value={project.canvas.height} readOnly /></label>
          </div>
          <label>Background<span className="dc-color-field"><span style={{ background: project.canvas.background }} />{project.canvas.background}</span></label>
        </div>
      )}
    </aside>
  );
}
