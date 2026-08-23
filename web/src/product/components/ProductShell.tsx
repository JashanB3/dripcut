import {
  CircleHelp,
  CalendarClock,
  Clapperboard,
  Home,
  FolderKanban,
  LayoutTemplate,
  Plus,
  Search,
  Settings,
  Sparkles,
  UserRound,
  WalletCards,
  X,
} from "lucide-react";
import type { ReactNode } from "react";

import { entitlementPreview } from "../config/entitlements";
import type { ProductRoute } from "../models";

export type UtilityPanel = "usage" | "settings" | "account" | null;

const mainNavigation: Array<{ route: ProductRoute; label: string; icon: typeof Home }> = [
  { route: "home", label: "Home", icon: Home },
  { route: "projects", label: "Projects", icon: FolderKanban },
  { route: "templates", label: "Templates", icon: LayoutTemplate },
  { route: "ai-editor", label: "AI Editor", icon: Sparkles },
  { route: "schedule", label: "Schedule", icon: CalendarClock },
];

export function ProductShell({
  route,
  onNavigate,
  onCreate,
  utilityPanel,
  onUtilityPanel,
  children,
}: {
  route: ProductRoute;
  onNavigate: (route: ProductRoute) => void;
  onCreate: () => void;
  utilityPanel: UtilityPanel;
  onUtilityPanel: (panel: UtilityPanel) => void;
  children: ReactNode;
}) {
  return (
    <div className="product-shell">
      <aside className="product-nav">
        <button className="product-logo" aria-label="Go to DripCut home" onClick={() => onNavigate("home")}>
          <span>dc</span>
          <strong>DripCut</strong>
        </button>
        <button className="create-nav-button" onClick={onCreate}>
          <Plus size={21} strokeWidth={2.6} />
          <span>Create</span>
        </button>
        <nav className="product-nav__main" aria-label="Primary navigation">
          {mainNavigation.map(({ route: itemRoute, label, icon: Icon }) => (
            <button
              key={itemRoute}
              data-selected={route === itemRoute}
              onClick={() => onNavigate(itemRoute)}
            >
              <Icon size={20} />
              <span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="product-nav__bottom">
          <button data-selected={utilityPanel === "usage"} onClick={() => onUtilityPanel("usage")}>
            <WalletCards size={19} /><span>Usage</span>
          </button>
          <button data-selected={route === "settings"} onClick={() => onNavigate("settings")}>
            <Settings size={19} /><span>Settings</span>
          </button>
          <button data-selected={utilityPanel === "account"} onClick={() => onUtilityPanel("account")}>
            <span className="nav-avatar">J</span><span>Account</span>
          </button>
        </div>
      </aside>
      <section className="product-main">
        <header className="product-topbar">
          <div className="product-search">
            <Search size={17} />
            <span>Search projects and tools</span>
            <kbd>⌘K</kbd>
          </div>
          <div className="product-topbar__spacer" />
          <button className="topbar-help" title="Help center is not connected yet" disabled>
            <CircleHelp size={19} />
          </button>
          <span className="local-pill">Local preview</span>
          <button className="topbar-avatar" onClick={() => onUtilityPanel("account")} aria-label="Open account menu">J</button>
        </header>
        <main className="route-outlet">{children}</main>
      </section>
      {utilityPanel && (
        <UtilityDrawer panel={utilityPanel} onClose={() => onUtilityPanel(null)} />
      )}
    </div>
  );
}

function UtilityDrawer({ panel, onClose }: { panel: Exclude<UtilityPanel, null>; onClose: () => void }) {
  const usedMinutes = entitlementPreview.weeklySourceMinutesUsed;
  const weeklyMinutes = entitlementPreview.weeklySourceMinutes;
  const usedSeconds = Math.round(usedMinutes * 60);
  const usedLabel = `${Math.floor(usedSeconds / 60)}:${String(usedSeconds % 60).padStart(2, "0")}`;
  const limitLabel = `${weeklyMinutes}:00`;
  const usagePercent = Math.min(100, (usedMinutes / weeklyMinutes) * 100);
  const content = {
    usage: {
      eyebrow: "Usage preview",
      title: "Your creator plan",
      body: "Entitlements are not connected yet. This preview shows the intended weekly limit presentation.",
    },
    settings: {
      eyebrow: "Settings",
      title: "Simple by default",
      body: "Project persistence and account preferences will appear here after the API boundary is connected.",
    },
    account: {
      eyebrow: "Account",
      title: "Creator profile",
      body: "Authentication and social OAuth are intentionally unavailable in this frontend foundation.",
    },
  }[panel];

  return (
    <div className="utility-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <aside className="utility-drawer" aria-label={`${content.title} panel`}>
        <button className="modal-close" onClick={onClose} aria-label="Close panel"><X size={18} /></button>
        <span className="eyebrow">{content.eyebrow}</span>
        <h2>{content.title}</h2>
        <p>{content.body}</p>
        {panel === "usage" && (
          <div className="usage-preview">
            <div><span>Example weekly usage</span><strong>{usedLabel} / {limitLabel} min</strong></div>
            <span><i style={{ width: `${usagePercent}%` }} /></span>
            <small>Limits will come from a configurable entitlement service.</small>
          </div>
        )}
        {panel === "account" && (
          <div className="connection-list">
            <div><Clapperboard size={18} /><span><strong>YouTube</strong><small>Not connected</small></span><button disabled>Connect</button></div>
            <div><Sparkles size={18} /><span><strong>Instagram</strong><small>Not connected</small></span><button disabled>Connect</button></div>
          </div>
        )}
        {panel === "settings" && (
          <div className="settings-preview">
            <label><span>Default format</span><select disabled><option>Portrait · 9:16</option></select></label>
            <label><span>Default captions</span><input type="checkbox" disabled /></label>
          </div>
        )}
        <div className="development-note"><UserRound size={16} /> Development state · no account data is stored</div>
      </aside>
    </div>
  );
}
