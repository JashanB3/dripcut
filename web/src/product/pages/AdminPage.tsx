import { AlertTriangle, Bot, Clock3, Database, Film, FolderKanban, RefreshCw, Send, Users } from "lucide-react";
import { useEffect, useState } from "react";

import { ApiError, fetchAdminOverview } from "../api/client";
import type { AdminOverview } from "../models";

const metricCards = [
  ["total_users", "Total users", Users],
  ["active_users_30d", "Active users", Clock3],
  ["projects_created", "Projects", FolderKanban],
  ["videos_processed", "Videos processed", Film],
  ["render_jobs", "Render jobs", Database],
  ["failed_jobs", "Failed jobs", AlertTriangle],
  ["ai_requests", "AI requests", Bot],
  ["published_posts", "Published posts", Send],
] as const;

export function AdminPage() {
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    setBusy(true);
    setError("");
    void fetchAdminOverview()
      .then(setOverview)
      .catch((reason: ApiError) => setError(reason.message || "Admin analytics are unavailable."))
      .finally(() => setBusy(false));
  }, [refreshKey]);

  return (
    <div className="admin-page product-page">
      <header className="page-title-row">
        <div><span className="eyebrow">Internal operations</span><h1>DripCut Admin</h1><p>Privacy-safe product health across users, processing, AI and publishing.</p></div>
        <button className="secondary-action" disabled={busy} onClick={() => setRefreshKey((value) => value + 1)}><RefreshCw size={16} /> {busy ? "Refreshing…" : "Refresh"}</button>
      </header>
      {error && <div className="inline-error"><AlertTriangle size={17} /> {error}</div>}
      {busy && !overview && <div className="admin-loading"><span className="spinner" /> Loading operations…</div>}
      {overview && <>
        <section className="admin-metric-grid">
          {metricCards.map(([key, label, Icon]) => <article key={key}><span><Icon size={18} /></span><strong>{formatMetric(overview.metrics[key] ?? 0)}</strong><small>{label}</small></article>)}
        </section>
        <section className="admin-detail-grid">
          <article className="admin-table-card"><div className="section-heading"><div><span className="eyebrow">Accounts</span><h2>Recent users</h2></div></div><div className="admin-table"><div className="admin-table__head"><span>Creator</span><span>Role</span><span>Last active</span></div>{overview.users.length ? overview.users.map((user) => <div key={user.id}><span><strong>{user.name || "Unnamed creator"}</strong><small>{user.email}</small></span><span>{user.role}</span><span>{formatDate(user.lastActiveAt)}</span></div>) : <p>No users yet.</p>}</div></article>
          <article className="admin-table-card"><div className="section-heading"><div><span className="eyebrow">Workers</span><h2>Recent jobs</h2></div></div><div className="admin-table"><div className="admin-table__head"><span>Job</span><span>Status</span><span>Time</span></div>{overview.jobs.length ? overview.jobs.map((job) => <div key={job.id}><span><strong>{job.title}</strong><small>{job.stage || job.id.slice(0, 8)}</small></span><span data-status={job.status}>{job.status}</span><span>{job.elapsedSeconds.toFixed(1)}s</span></div>) : <p>No jobs yet.</p>}</div></article>
        </section>
        <section className="admin-detail-grid">
          <article className="admin-table-card"><div className="section-heading"><div><span className="eyebrow">Allowances</span><h2>Provider usage</h2></div></div><div className="admin-usage-list">{overview.usage.length ? overview.usage.map((item) => <div key={`${item.metric}-${item.unit}`}><span>{item.metric.replaceAll("_", " ")}</span><strong>{formatMetric(item.quantity)} {item.unit}</strong></div>) : <p>No usage events yet.</p>}</div></article>
          <article className="admin-table-card"><div className="section-heading"><div><span className="eyebrow">Failures</span><h2>Errors to inspect</h2></div></div><div className="admin-error-list">{overview.errors.length ? overview.errors.map((job) => <div key={job.id}><AlertTriangle size={16} /><span><strong>{job.errorCode || "RENDER_FAILED"}</strong><small>{job.errorMessage || job.stage}</small></span></div>) : <p>No recent failures.</p>}</div></article>
        </section>
        <p className="admin-generated">Generated {formatDate(overview.generatedAt)}. Credentials, cookies, prompts and private media are never included.</p>
      </>}
    </div>
  );
}

function formatMetric(value: number) {
  return Intl.NumberFormat(undefined, { maximumFractionDigits: 1, notation: value >= 10_000 ? "compact" : "standard" }).format(value);
}

function formatDate(value: string) {
  if (!value) return "Never";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "Unknown" : date.toLocaleString();
}
