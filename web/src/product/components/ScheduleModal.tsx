import { CalendarDays, Check, Clock3, Instagram, Sparkles, X, Youtube } from "lucide-react";
import { useState } from "react";

import { entitlementPreview } from "../config/entitlements";
import type { ClipSegment, Platform, ScheduleDraft } from "../models";

const frequencyDays = { "6h": 0.25, "12h": 0.5, "1d": 1, "2d": 2, custom: 1 } as const;

export function ScheduleModal({ open, segments, onClose }: { open: boolean; segments: ClipSegment[]; onClose: () => void }) {
  const [draft, setDraft] = useState<ScheduleDraft>({
    platforms: ["youtube", "instagram"],
    startDate: new Date().toISOString().slice(0, 10),
    frequency: "1d",
    bestTime: false,
  });
  if (!open) return null;

  const togglePlatform = (platform: Platform) => {
    const included = draft.platforms.includes(platform);
    const platforms = included ? draft.platforms.filter((item) => item !== platform) : [...draft.platforms, platform];
    if (platforms.length) setDraft({ ...draft, platforms });
  };

  const schedule = segments.slice(0, 5).map((segment, index) => {
    const date = new Date(`${draft.startDate}T10:00:00`);
    date.setHours(date.getHours() + index * frequencyDays[draft.frequency] * 24);
    return { segment, date };
  });

  return (
    <div className="schedule-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="schedule-modal" role="dialog" aria-modal="true" aria-labelledby="schedule-title">
        <button className="modal-close" onClick={onClose} aria-label="Close schedule preview"><X size={18} /></button>
        <header><span className="eyebrow">Scheduling preview</span><h2 id="schedule-title">Build a posting rhythm.</h2><p>This panel is functional as a draft preview, but no platform account or scheduling API is connected.</p></header>
        <div className="schedule-modal__body">
          <div className="schedule-form">
            <div className="schedule-field"><strong>Platforms</strong><div className="platform-options">
              <button data-selected={draft.platforms.includes("youtube")} onClick={() => togglePlatform("youtube")}><Youtube size={17} /> YouTube</button>
              <button data-selected={draft.platforms.includes("instagram")} onClick={() => togglePlatform("instagram")}><Instagram size={17} /> Instagram</button>
            </div></div>
            <label className="schedule-field"><strong>Start date</strong><span><CalendarDays size={16} /><input type="date" value={draft.startDate} onChange={(event) => setDraft({ ...draft, startDate: event.target.value })} /></span></label>
            <label className="schedule-field"><strong>Posting frequency</strong><span><Clock3 size={16} /><select value={draft.frequency} onChange={(event) => setDraft({ ...draft, frequency: event.target.value as ScheduleDraft["frequency"] })}>
              <option value="6h">Every 6 hours</option><option value="12h">Every 12 hours</option><option value="1d">Every day</option><option value="2d">Every 2 days</option><option value="custom">Custom · preview only</option>
            </select></span></label>
            <label className="best-time-option"><input type="checkbox" checked={draft.bestTime} onChange={(event) => setDraft({ ...draft, bestTime: event.target.checked })} /><span><Sparkles size={16} /><p><strong>Best time automatically</strong><small>Requires platform insights API</small></p></span></label>
          </div>
          <div className="schedule-preview">
            <div className="schedule-preview__heading"><strong>{segments.length} {segments.length === 1 ? "clip" : "clips"} ready to plan</strong><span>First {schedule.length} shown</span></div>
            {schedule.map(({ segment, date }) => (
              <div key={segment.id}><span><Check size={14} /></span><p><strong>Clip {segment.index}</strong><small>{date.toLocaleDateString(undefined, { month: "short", day: "numeric" })} · {date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}</small></p><em>{draft.platforms.length === 2 ? "YouTube + Instagram" : draft.platforms[0]}</em></div>
            ))}
          </div>
        </div>
        <footer><span>Free scheduling limit preview: {entitlementPreview.freeScheduledVideosPerMonth} videos/month</span><button disabled title="OAuth and scheduling APIs are not connected">Schedule All · Not connected</button></footer>
      </section>
    </div>
  );
}
