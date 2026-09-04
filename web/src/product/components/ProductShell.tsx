import {
  CircleHelp,
  CalendarClock,
  Home,
  FolderKanban,
  LayoutTemplate,
  FilePenLine,
  Plus,
  Search,
  ShieldCheck,
  Settings,
  Sparkles,
  UserRound,
  WalletCards,
  X,
} from "lucide-react";
import type { ReactNode } from "react";

import type { ProductRoute } from "../models";

export type UtilityPanel = "settings" | "account" | null;
type ShellUser = { name: string; email: string; is_dripcut_admin?: boolean };

const mainNavigation: Array<{ route: ProductRoute; label: string; icon: typeof Home }> = [
  { route: "home", label: "Home", icon: Home },
  { route: "projects", label: "Projects", icon: FolderKanban },
  { route: "templates", label: "Templates", icon: LayoutTemplate },
  { route: "script", label: "Script Studio", icon: FilePenLine },
  { route: "ai-editor", label: "AI Editor", icon: Sparkles },
  { route: "schedule", label: "Schedule", icon: CalendarClock },
  { route: "usage", label: "Usage", icon: WalletCards },
];

export function ProductShell({
  route,
  onNavigate,
  onCreate,
  utilityPanel,
  onUtilityPanel,
  user,
  onLogout,
  children,
}: {
  route: ProductRoute;
  onNavigate: (route: ProductRoute) => void;
  onCreate: () => void;
  utilityPanel: UtilityPanel;
  onUtilityPanel: (panel: UtilityPanel) => void;
  user: ShellUser;
  onLogout: () => void;
  children: ReactNode;
}) {
  const initial = (user.name || user.email || "D").slice(0, 1).toUpperCase();
  const navigation = user.is_dripcut_admin
    ? [...mainNavigation, { route: "admin" as ProductRoute, label: "Admin", icon: ShieldCheck }]
    : mainNavigation;
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
          {navigation.map(({ route: itemRoute, label, icon: Icon }) => (
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
          <button data-selected={route === "settings"} onClick={() => onNavigate("settings")}>
            <Settings size={19} /><span>Settings</span>
          </button>
          <button data-selected={utilityPanel === "account"} onClick={() => onUtilityPanel("account")}>
            <span className="nav-avatar">{initial}</span><span>Account</span>
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
          <span className="local-pill">{user.name}</span>
          <button className="topbar-avatar" onClick={() => onUtilityPanel("account")} aria-label="Open account menu">{initial}</button>
        </header>
        <main className="route-outlet">{children}</main>
      </section>
      {utilityPanel && (
        <UtilityDrawer
          panel={utilityPanel}
          user={user}
          onLogout={onLogout}
          onOpenConnections={() => { onUtilityPanel(null); onNavigate("schedule"); }}
          onClose={() => onUtilityPanel(null)}
        />
      )}
    </div>
  );
}

function UtilityDrawer({
  panel,
  user,
  onLogout,
  onOpenConnections,
  onClose,
}: {
  panel: Exclude<UtilityPanel, null>;
  user: ShellUser;
  onLogout: () => void;
  onOpenConnections: () => void;
  onClose: () => void;
}) {
  const content = {
    settings: {
      eyebrow: "Settings",
      title: "Simple by default",
      body: "Project persistence and account preferences will appear here after the API boundary is connected.",
    },
    account: {
      eyebrow: "Account",
      title: user.name,
      body: user.email,
    },
  }[panel];

  return (
    <div className="utility-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <aside className="utility-drawer" aria-label={`${content.title} panel`}>
        <button className="modal-close" onClick={onClose} aria-label="Close panel"><X size={18} /></button>
        <span className="eyebrow">{content.eyebrow}</span>
        <h2>{content.title}</h2>
        <p>{content.body}</p>
        {panel === "account" && (
          <div className="connection-list">
            <div><CalendarClock size={18} /><span><strong>Publishing accounts</strong><small>View live YouTube and Instagram connection status.</small></span><button onClick={onOpenConnections}>Manage</button></div>
            <button className="secondary-action account-logout" onClick={onLogout}>Log out</button>
          </div>
        )}
        {panel === "settings" && (
          <div className="settings-preview">
            <label><span>Default format</span><select disabled><option>Portrait · 9:16</option></select></label>
            <label><span>Default captions</span><input type="checkbox" disabled /></label>
          </div>
        )}
        <div className="development-note"><UserRound size={16} /> Signed in to your private workspace</div>
      </aside>
    </div>
  );
}
