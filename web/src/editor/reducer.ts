import type { AssetReference, EditorAction, EditorProject, EditorState } from "./types";

const MAX_HISTORY = 50;

function commit(state: EditorState, project: EditorProject): EditorState {
  return {
    past: [...state.past, state.present.project].slice(-MAX_HISTORY),
    present: {
      ...state.present,
      project: { ...project, updatedAt: new Date().toISOString() },
      dirty: true,
      saveStatus: "dirty",
    },
    future: [],
  };
}

function projectWithAsset(project: EditorProject, asset: AssetReference): EditorProject {
  const existing = project.assets.some((item) => item.id === asset.id);
  const duration = Math.max(asset.duration, 0.1);
  const upsertClip = (kind: "video" | "audio") => ({
    id: `${kind}-${asset.id}`,
    assetId: asset.id,
    label: asset.name,
    start: 0,
    end: duration,
    sourceStart: 0,
    sourceEnd: duration,
    color: kind === "video" ? ("violet" as const) : ("cyan" as const),
    transform: kind === "video"
      ? { x: 0, y: 0, scale: 1, rotation: 0, opacity: 1 }
      : undefined,
  });

  return {
    ...project,
    assets: existing
      ? project.assets.map((item) => (item.id === asset.id ? asset : item))
      : [...project.assets, asset],
    timeline: {
      ...project.timeline,
      duration: Math.max(duration, project.timeline.duration),
      tracks: project.timeline.tracks.map((track) => {
        if (track.kind !== "video" && track.kind !== "audio") return track;
        const clip = upsertClip(track.kind);
        return {
          ...track,
          clips: existing
            ? track.clips.map((item) => (item.assetId === asset.id ? clip : item))
            : [...track.clips, clip],
        };
      }),
    },
  };
}

export function editorReducer(state: EditorState, action: EditorAction): EditorState {
  switch (action.type) {
    case "select-tool":
      return { ...state, present: { ...state.present, selectedTool: action.tool } };
    case "select":
      return { ...state, present: { ...state.present, selection: action.selection } };
    case "set-playback":
      return {
        ...state,
        present: {
          ...state.present,
          playback: { ...state.present.playback, ...action.patch },
        },
      };
    case "rename-project":
      return commit(state, { ...state.present.project, name: action.name || "Untitled project" });
    case "upsert-asset":
      return commit(state, projectWithAsset(state.present.project, action.asset));
    case "set-timeline-zoom":
      return commit(state, {
        ...state.present.project,
        timeline: { ...state.present.project.timeline, zoom: action.zoom },
      });
    case "set-canvas-aspect": {
      const dimensions = {
        "16:9": [1920, 1080],
        "9:16": [1080, 1920],
        "1:1": [1080, 1080],
      }[action.aspectRatio];
      return commit(state, {
        ...state.present.project,
        canvas: {
          ...state.present.project.canvas,
          aspectRatio: action.aspectRatio,
          width: dimensions[0],
          height: dimensions[1],
        },
      });
    }
    case "undo": {
      const previous = state.past.at(-1);
      if (!previous) return state;
      return {
        past: state.past.slice(0, -1),
        present: { ...state.present, project: previous, dirty: true, saveStatus: "dirty" },
        future: [state.present.project, ...state.future],
      };
    }
    case "redo": {
      const next = state.future[0];
      if (!next) return state;
      return {
        past: [...state.past, state.present.project].slice(-MAX_HISTORY),
        present: { ...state.present, project: next, dirty: true, saveStatus: "dirty" },
        future: state.future.slice(1),
      };
    }
    case "mark-saved":
      return {
        ...state,
        present: { ...state.present, dirty: false, saveStatus: "saved" },
      };
  }
}
