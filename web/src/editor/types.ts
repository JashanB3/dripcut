export type ToolId =
  | "media"
  | "templates"
  | "text"
  | "captions"
  | "audio"
  | "elements"
  | "brand"
  | "ai";

export type TrackKind = "video" | "audio" | "text" | "caption";
export type Selection =
  | { kind: "canvas"; id: "canvas" }
  | { kind: "asset"; id: string }
  | { kind: "clip"; id: string }
  | null;

export interface AssetReference {
  id: string;
  name: string;
  kind: "video" | "audio" | "image";
  mimeType: string;
  duration: number;
  width: number;
  height: number;
  source: {
    type: "local" | "uploaded" | "remote";
    assetKey: string | null;
  };
}

export interface TimelineClip {
  id: string;
  assetId: string | null;
  label: string;
  start: number;
  end: number;
  sourceStart: number;
  sourceEnd: number;
  color: "violet" | "cyan" | "amber" | "rose";
  transform?: {
    x: number;
    y: number;
    scale: number;
    rotation: number;
    opacity: number;
  };
}

export interface TimelineTrack {
  id: string;
  kind: TrackKind;
  name: string;
  muted: boolean;
  locked: boolean;
  clips: TimelineClip[];
}

export interface EditorProject {
  version: 1;
  id: string;
  name: string;
  createdAt: string;
  updatedAt: string;
  assets: AssetReference[];
  canvas: {
    aspectRatio: "16:9" | "9:16" | "1:1";
    width: number;
    height: number;
    background: string;
    zoom: number;
  };
  timeline: {
    duration: number;
    zoom: number;
    tracks: TimelineTrack[];
  };
  renderSettings: {
    format: "mp4" | "mov";
    width: number;
    height: number;
    fps: number;
    quality: "draft" | "balanced" | "high";
    captions: boolean;
  };
}

export interface EditorPresent {
  project: EditorProject;
  selectedTool: ToolId;
  selection: Selection;
  playback: {
    currentTime: number;
    duration: number;
    playing: boolean;
    volume: number;
  };
  dirty: boolean;
  saveStatus: "saved" | "dirty" | "saving";
}

export interface EditorState {
  past: EditorProject[];
  present: EditorPresent;
  future: EditorProject[];
}

export type EditorAction =
  | { type: "select-tool"; tool: ToolId }
  | { type: "select"; selection: Selection }
  | { type: "rename-project"; name: string }
  | { type: "upsert-asset"; asset: AssetReference }
  | { type: "set-playback"; patch: Partial<EditorPresent["playback"]> }
  | { type: "set-timeline-zoom"; zoom: number }
  | { type: "set-canvas-aspect"; aspectRatio: EditorProject["canvas"]["aspectRatio"] }
  | { type: "undo" }
  | { type: "redo" }
  | { type: "mark-saved" };

const now = new Date().toISOString();

export const createInitialProject = (): EditorProject => ({
  version: 1,
  id: crypto.randomUUID(),
  name: "Untitled project",
  createdAt: now,
  updatedAt: now,
  assets: [],
  canvas: {
    aspectRatio: "16:9",
    width: 1920,
    height: 1080,
    background: "#090a0e",
    zoom: 1,
  },
  timeline: {
    duration: 30,
    zoom: 1,
    tracks: [
      { id: "track-video", kind: "video", name: "Video", muted: false, locked: false, clips: [] },
      { id: "track-audio", kind: "audio", name: "Audio", muted: false, locked: false, clips: [] },
      { id: "track-text", kind: "text", name: "Text", muted: false, locked: false, clips: [] },
      { id: "track-caption", kind: "caption", name: "Captions", muted: false, locked: false, clips: [] },
    ],
  },
  renderSettings: {
    format: "mp4",
    width: 1920,
    height: 1080,
    fps: 30,
    quality: "balanced",
    captions: false,
  },
});

export const createInitialState = (): EditorState => ({
  past: [],
  present: {
    project: createInitialProject(),
    selectedTool: "media",
    selection: { kind: "canvas", id: "canvas" },
    playback: { currentTime: 0, duration: 0, playing: false, volume: 0.8 },
    dirty: false,
    saveStatus: "saved",
  },
  future: [],
});
