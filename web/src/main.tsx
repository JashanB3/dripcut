import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { AuthProvider } from "./auth/AuthProvider";
import { AppErrorBoundary } from "./product/components/AppErrorBoundary";
import "./styles/tokens.css";
import "./styles/global.css";
import "./styles/editor.css";
import "./styles/landing.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppErrorBoundary><AuthProvider><App /></AuthProvider></AppErrorBoundary>
  </StrictMode>,
);
