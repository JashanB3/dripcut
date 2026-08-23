import { FileVideo2, Upload } from "lucide-react";
import { useRef, useState } from "react";

import { useEditor } from "../../editor/context";
import { EmptyState, SearchField } from "../primitives/Controls";
import type { RuntimeMedia } from "./types";

const toolCopy = {
  templates: ["Templates", "Template editing arrives after the core project API."],
  text: ["Text", "Text layers will be enabled when canvas transforms are implemented."],
  captions: ["Captions", "Caption editing will connect to DripCut's existing subtitle engine."],
  audio: ["Audio", "Audio library and mixing are planned after multi-track persistence."],
  elements: ["Elements", "Shape and sticker layers are intentionally deferred."],
  brand: ["Brand", "Brand kits are outside this editor-foundation phase."],
  ai: ["AI tools", "AI tools will reuse the current Python AI services through the API."],
} as const;

export function ToolPanel({ media, onImport }: {
  media: RuntimeMedia | null;
  onImport: (file: File) => void;
}) {
  const { state, dispatch } = useEditor();
  const input = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const activeTool = state.present.selectedTool;
  const mediaMatches = media?.name.toLowerCase().includes(query.trim().toLowerCase());

  if (activeTool !== "media") {
    const [title, body] = toolCopy[activeTool];
    return (
      <aside className="dc-tool-panel">
        <div className="dc-panel-heading"><h2>{title}</h2></div>
        <EmptyState icon={<span>+</span>} title="Not enabled yet" body={body} />
      </aside>
    );
  }

  return (
    <aside className="dc-tool-panel">
      <div className="dc-panel-heading">
        <h2>Media</h2>
        <button className="dc-panel-heading__action" onClick={() => input.current?.click()}>
          <Upload size={15} /> Upload
        </button>
      </div>
      <SearchField
        placeholder="Search project media"
        aria-label="Search project media"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      <input
        ref={input}
        className="dc-visually-hidden"
        type="file"
        accept="video/*"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) onImport(file);
          event.currentTarget.value = "";
        }}
      />
      {media && mediaMatches ? (
        <button
          className="dc-asset-card"
          data-selected={state.present.selection?.kind === "asset"}
          onClick={() => dispatch({ type: "select", selection: { kind: "asset", id: media.id } })}
        >
          <span className="dc-asset-card__preview"><FileVideo2 size={26} /></span>
          <span className="dc-asset-card__name">{media.name}</span>
          <span className="dc-asset-card__meta">Local video</span>
        </button>
      ) : media ? (
        <EmptyState
          icon={<FileVideo2 size={22} />}
          title="No media found"
          body={`Nothing matches “${query}”.`}
          action={<button className="dc-text-action" onClick={() => setQuery("")}>Clear search</button>}
        />
      ) : (
        <EmptyState
          icon={<FileVideo2 size={22} />}
          title="Bring in a video"
          body="Use a local MP4, MOV or WebM file to start editing."
          action={<button className="dc-text-action" onClick={() => input.current?.click()}>Choose video</button>}
        />
      )}
    </aside>
  );
}
