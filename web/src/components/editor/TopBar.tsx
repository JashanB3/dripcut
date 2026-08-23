import { Cloud, Download, Redo2, Undo2 } from "lucide-react";
import { useEffect, useState } from "react";

import { useEditor } from "../../editor/context";
import { Button, IconButton } from "../primitives/Controls";

export function TopBar() {
  const { state, dispatch } = useEditor();
  const [name, setName] = useState(state.present.project.name);

  useEffect(() => setName(state.present.project.name), [state.present.project.name]);

  return (
    <header className="dc-topbar">
      <div className="dc-brand" aria-label="DripCut editor">
        <span className="dc-brand__mark">dc</span>
        <span>DripCut</span>
      </div>
      <span className="dc-topbar__divider" />
      <input
        className="dc-project-name"
        aria-label="Project name"
        value={name}
        onChange={(event) => setName(event.target.value)}
        onBlur={() => dispatch({ type: "rename-project", name })}
        onKeyDown={(event) => event.key === "Enter" && event.currentTarget.blur()}
      />
      <div className="dc-history-controls">
        <IconButton
          label="Undo"
          disabled={state.past.length === 0}
          onClick={() => dispatch({ type: "undo" })}
        >
          <Undo2 size={17} />
        </IconButton>
        <IconButton
          label="Redo"
          disabled={state.future.length === 0}
          onClick={() => dispatch({ type: "redo" })}
        >
          <Redo2 size={17} />
        </IconButton>
      </div>
      <div className="dc-topbar__spacer" />
      <span className="dc-save-status">
        <Cloud size={14} /> {state.present.saveStatus === "saved" ? "Browser session" : "Unsaved session changes"}
      </span>
      <Button variant="primary" disabled title="Export API is intentionally deferred">
        <Download size={16} /> Export
      </Button>
      <button className="dc-avatar" aria-label="Account menu" disabled title="Authentication is intentionally deferred">J</button>
    </header>
  );
}
