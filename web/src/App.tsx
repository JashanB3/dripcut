import { useEffect, useState } from "react";

import { CreateModal } from "./product/components/CreateModal";
import { ProductShell, type UtilityPanel } from "./product/components/ProductShell";
import type { ProductRoute } from "./product/models";
import { AIEditorPage } from "./product/pages/AIEditorPage";
import { AIThumbnailPage } from "./product/pages/AIThumbnailPage";
import { AutoClipPage } from "./product/pages/AutoClipPage";
import { HomePage } from "./product/pages/HomePage";
import { ProjectsPage } from "./product/pages/ProjectsPage";
import { SchedulePage } from "./product/pages/SchedulePage";
import { SettingsPage } from "./product/pages/SettingsPage";
import { TemplatesPage } from "./product/pages/TemplatesPage";
import { useHashRoute } from "./product/hooks/useHashRoute";

export function App() {
  const { route, navigate } = useHashRoute();
  const [createOpen, setCreateOpen] = useState(false);
  const [utilityPanel, setUtilityPanel] = useState<UtilityPanel>(null);

  useEffect(() => {
    setCreateOpen(false);
    setUtilityPanel(null);
  }, [route]);

  const goTo = (next: ProductRoute) => {
    setCreateOpen(false);
    setUtilityPanel(null);
    navigate(next);
  };

  return (
    <ProductShell
      route={route}
      onNavigate={goTo}
      onCreate={() => setCreateOpen(true)}
      utilityPanel={utilityPanel}
      onUtilityPanel={setUtilityPanel}
    >
      {route === "home" && <HomePage onCreate={() => setCreateOpen(true)} onNavigate={goTo} />}
      {route === "projects" && <ProjectsPage onNavigate={goTo} />}
      {route === "templates" && <TemplatesPage />}
      {route === "ai-editor" && <AIEditorPage />}
      {route === "ai-thumbnail" && <AIThumbnailPage />}
      {route === "schedule" && <SchedulePage />}
      {route === "settings" && <SettingsPage />}
      {route === "auto-clip" && <AutoClipPage onNavigate={goTo} />}
      <CreateModal open={createOpen} onClose={() => setCreateOpen(false)} onNavigate={goTo} />
    </ProductShell>
  );
}
