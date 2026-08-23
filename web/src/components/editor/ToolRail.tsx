import {
  AudioLines,
  Captions,
  Component,
  ImagePlus,
  Palette,
  Sparkles,
  Type,
  WandSparkles,
} from "lucide-react";

import { useEditor } from "../../editor/context";
import type { ToolId } from "../../editor/types";

const tools: Array<{ id: ToolId; label: string; icon: typeof ImagePlus }> = [
  { id: "media", label: "Media", icon: ImagePlus },
  { id: "templates", label: "Templates", icon: Component },
  { id: "text", label: "Text", icon: Type },
  { id: "captions", label: "Captions", icon: Captions },
  { id: "audio", label: "Audio", icon: AudioLines },
  { id: "elements", label: "Elements", icon: Sparkles },
  { id: "brand", label: "Brand", icon: Palette },
  { id: "ai", label: "AI tools", icon: WandSparkles },
];

export function ToolRail() {
  const { state, dispatch } = useEditor();
  return (
    <nav className="dc-tool-rail" aria-label="Editor tools">
      {tools.map(({ id, label, icon: Icon }) => (
        <button
          key={id}
          className="dc-tool-rail__item"
          data-selected={state.present.selectedTool === id}
          onClick={() => dispatch({ type: "select-tool", tool: id })}
        >
          <Icon size={20} strokeWidth={1.8} />
          <span>{label}</span>
        </button>
      ))}
    </nav>
  );
}
