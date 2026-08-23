import { type ReactNode, useReducer } from "react";

import { editorReducer } from "./reducer";
import { EditorContext } from "./context";
import { createInitialState } from "./types";

export function EditorProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(editorReducer, undefined, createInitialState);
  return <EditorContext value={{ state, dispatch }}>{children}</EditorContext>;
}
