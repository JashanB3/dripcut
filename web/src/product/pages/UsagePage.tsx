import {
  Bot,
  CalendarClock,
  Clapperboard,
  Cloud,
  Download,
  Image,
  RefreshCw,
  Sparkles,
  Subtitles,
} from "lucide-react";
import { useEffect, useState } from "react";

import { ApiError, fetchUsage } from "../api/client";
import type { UsageMetric, UsageSummary } from "../models";

const metricIcons: Record<string, typeof Clapperboard> = {
  video_processing_minutes: Clapperboard,
  ai_viral_analyses: Sparkles,
  transcription_minutes: Subtitles,
  thumbnail_generations: Image,
  ai_editor_actions: Bot,
  scheduled_posts: CalendarClock,
  youtube_imports: Download,
  storage_bytes: Cloud,
};

function formatAmount(value: number, metric: UsageMetric): string {
  if (metric.unit === "bytes") {
    const gigabytes = value / 1024 ** 3;
    return `${gigabytes < 0.1 ? gigabytes.toFixed(2) : gigabytes.toFixed(1)} GB`;
  }
  if (metric.unit === "minutes") return `${value.toFixed(value < 10 ? 1 : 0)} min`;
  return Math.round(value).toLocaleString();
}

export function UsagePage() {
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      setSummary(await fetchUsage());
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Usage could not be loaded.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const resetLabel = summary
    ? new Date(summary.resetAt).toLocaleDateString(undefined, { month: "long", day: "numeric" })
    : "";
  const needsMoreRoom = Boolean(summary?.metrics.some((metric) => metric.percent >= 75));

  return (
    <div className="usage-page product-page narrow-page">
      <header className="page-heading-row">
        <div>
          <span className="eyebrow">Plan and usage</span>
          <h1>Create freely. Know your limits.</h1>
          <p>Live workspace totals update as imports, renders, AI actions, and schedules complete.</p>
        </div>
        <button className="secondary-action" onClick={() => void load()} disabled={loading}>
          <RefreshCw size={16} className={loading ? "spin" : ""} /> Refresh
        </button>
      </header>

      {error && <div className="usage-error" role="alert">{error}</div>}
      {loading && !summary && <div className="usage-loading"><span className="auth-loader" />Loading live usage...</div>}

      {summary && (
        <>
          <section className="usage-plan-banner">
            <div>
              <span className="eyebrow">Current plan</span>
              <h2>{summary.planLabel}</h2>
              <p>Monthly allowances reset on {resetLabel}. Running jobs appear as reserved until they finish.</p>
            </div>
            <span className="usage-plan-chip">{summary.planLabel} workspace</span>
          </section>

          <section className="usage-grid" aria-label="Workspace usage">
            {summary.metrics.map((metric) => {
              const Icon = metricIcons[metric.key] ?? Sparkles;
              const total = metric.used + metric.reserved;
              return (
                <article key={metric.key} data-alert={metric.percent >= 90}>
                  <header>
                    <span><Icon size={18} /></span>
                    <div><strong>{metric.label}</strong><small>{metric.unit}</small></div>
                    <em>{metric.unlimited ? "Unlimited" : `${Math.round(metric.percent)}%`}</em>
                  </header>
                  <div className="usage-meter" aria-label={`${metric.label} ${metric.percent}% used`}>
                    <span style={{ width: `${metric.percent}%` }} />
                  </div>
                  <footer>
                    <strong>{formatAmount(total, metric)}</strong>
                    <span>{metric.limit === null ? "No limit" : `of ${formatAmount(metric.limit, metric)}`}</span>
                  </footer>
                  {metric.reserved > 0 && <small>{formatAmount(metric.reserved, metric)} currently reserved</small>}
                </article>
              );
            })}
          </section>

          {needsMoreRoom && summary.plan === "free" && (
            <aside className="usage-upgrade-card">
              <div><strong>Your next big edit is welcome here.</strong><span>Ask about Creator limits before your monthly allowance runs out.</span></div>
              <a className="primary-action" href="mailto:hello@dripcut.app?subject=DripCut%20Creator%20plan">Explore Creator</a>
            </aside>
          )}
        </>
      )}
    </div>
  );
}
