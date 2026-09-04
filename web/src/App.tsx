import { useEffect, useState } from "react";

import { AuthPage } from "./auth/AuthPage";
import { navigatePath, useAuth } from "./auth/authState";
import { CreateModal } from "./product/components/CreateModal";
import { LandingPage } from "./product/pages/LandingPage";
import { ProductShell, type UtilityPanel } from "./product/components/ProductShell";
import type { ProductRoute } from "./product/models";
import { AIEditorPage } from "./product/pages/AIEditorPage";
import { AIThumbnailPage } from "./product/pages/AIThumbnailPage";
import { AdminPage } from "./product/pages/AdminPage";
import { AutoClipPage } from "./product/pages/AutoClipPage";
import { HomePage } from "./product/pages/HomePage";
import { ProjectsPage } from "./product/pages/ProjectsPage";
import { SchedulePage } from "./product/pages/SchedulePage";
import { ScriptStudioPage } from "./product/pages/ScriptStudioPage";
import { SettingsPage } from "./product/pages/SettingsPage";
import { TemplatesPage } from "./product/pages/TemplatesPage";
import { UsagePage } from "./product/pages/UsagePage";
import { useHashRoute } from "./product/hooks/useHashRoute";

export function App() {
  const auth = useAuth();
  const { route, navigate } = useHashRoute();
  const [pathname, setPathname] = useState(window.location.pathname);
  const [createOpen, setCreateOpen] = useState(false);
  const [utilityPanel, setUtilityPanel] = useState<UtilityPanel>(null);

  useEffect(() => {
    setCreateOpen(false);
    setUtilityPanel(null);
  }, [route]);

  useEffect(() => {
    const onNavigation = () => setPathname(window.location.pathname);
    window.addEventListener("popstate", onNavigation);
    return () => window.removeEventListener("popstate", onNavigation);
  }, []);

  useEffect(() => {
    if (auth.loading) return;
    const isAuthPath = ["/login", "/signup", "/forgot-password", "/reset-password", "/auth/callback", "/logout"].includes(pathname);
    if (!auth.session && pathname !== "/" && !isAuthPath) navigatePath("/login", true);
    if (auth.session && ["/login", "/signup"].includes(pathname)) navigatePath("/home", true);
  }, [auth.loading, auth.session, pathname]);

  useEffect(() => {
    if (!auth.loading && route === "admin" && !auth.session?.user?.is_dripcut_admin) {
      navigatePath("/home", true);
    }
  }, [auth.loading, auth.session, route]);

  const goTo = (next: ProductRoute) => {
    setCreateOpen(false);
    setUtilityPanel(null);
    navigate(next);
  };

  if (auth.loading) return <div className="app-loading"><span className="auth-loader" />Loading your workspace...</div>;

  const authKind = {
    "/login": "login",
    "/signup": "signup",
    "/forgot-password": "forgot-password",
    "/reset-password": "reset-password",
    "/auth/callback": "callback",
    "/logout": "logout",
  }[pathname] as "login" | "signup" | "forgot-password" | "reset-password" | "callback" | "logout" | undefined;
  if (authKind) return <AuthPage kind={authKind} />;
  if (pathname === "/") return <LandingPage signedIn={Boolean(auth.session)} />;
  if (!auth.session?.user) return <div className="app-loading"><span className="auth-loader" />Opening login...</div>;

  return (
    <ProductShell
      route={route}
      onNavigate={goTo}
      onCreate={() => setCreateOpen(true)}
      utilityPanel={utilityPanel}
      onUtilityPanel={setUtilityPanel}
      user={auth.session.user}
      onLogout={() => navigatePath("/logout")}
    >
      {route === "home" && <HomePage onCreate={() => setCreateOpen(true)} onNavigate={goTo} />}
      {route === "projects" && <ProjectsPage onNavigate={goTo} />}
      {route === "templates" && <TemplatesPage onNavigate={goTo} />}
      {route === "ai-editor" && <AIEditorPage />}
      {route === "ai-thumbnail" && <AIThumbnailPage />}
      {route === "script" && <ScriptStudioPage />}
      {route === "schedule" && <SchedulePage />}
      {route === "usage" && <UsagePage />}
      {route === "admin" && auth.session.user.is_dripcut_admin && <AdminPage />}
      {route === "settings" && <SettingsPage />}
      {route === "auto-clip" && <AutoClipPage onNavigate={goTo} />}
      <CreateModal open={createOpen} onClose={() => setCreateOpen(false)} onNavigate={goTo} />
    </ProductShell>
  );
}
