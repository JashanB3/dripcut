import {
  AudioLines,
  CalendarClock,
  Clapperboard,
  Download,
  FilePenLine,
  Film,
  ImagePlus,
  Search,
  Sparkles,
  WandSparkles,
  X,
} from "lucide-react";
import { useState } from "react";

import { experimentalTools, isLaunchRoute } from "../launch";
import { workflows } from "../mock/data";
import type { ProductRoute, WorkflowDefinition } from "../models";

const categories = ["For You", "Short Videos", "AI Tools", "Scheduling", "Utilities"] as const;
const workflowIcons: Record<string, typeof Film> = {
  "auto-clip": Sparkles,
  "youtube-shorts": Clapperboard,
  "instagram-reels": Film,
  "ai-editor": WandSparkles,
  "ai-thumbnail": ImagePlus,
  "schedule-content": CalendarClock,
  "bulk-schedule": Download,
  "extract-audio": AudioLines,
  "video-extractor": Download,
  "ai-script": FilePenLine,
};

export function CreateModal({ open, onClose, onNavigate }: {
  open: boolean;
  onClose: () => void;
  onNavigate: (route: ProductRoute) => void;
}) {
  const [category, setCategory] = useState<(typeof categories)[number]>("For You");
  const [query, setQuery] = useState("");
  if (!open) return null;

  const normalized = query.trim().toLowerCase();
  const launchWorkflows = workflows.filter((workflow) => workflow.status === "available" && isLaunchRoute(workflow.route));
  const visible = launchWorkflows.filter((workflow, index) => {
    if (normalized) return `${workflow.title} ${workflow.description}`.toLowerCase().includes(normalized);
    if (category === "For You") return index < 5;
    return workflow.category === category;
  });

  return (
    <div className="create-modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="create-modal" role="dialog" aria-modal="true" aria-labelledby="create-modal-title">
        <button className="modal-close" onClick={onClose} aria-label="Close create menu"><X size={18} /></button>
        <aside className="create-modal__categories">
          <span className="eyebrow">Create</span>
          <h2 id="create-modal-title">Start something</h2>
          <nav aria-label="Creation categories">
            {categories.filter((item) => item === "For You" || launchWorkflows.some((workflow) => workflow.category === item)).map((item) => (
              <button key={item} data-selected={!normalized && category === item} onClick={() => { setCategory(item); setQuery(""); }}>{item}</button>
            ))}
          </nav>
        </aside>
        <div className="create-modal__main">
          <label className="modal-search">
            <Search size={20} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="What would you like to create?" autoFocus />
          </label>
          <div className="modal-section-heading">
            <div><span className="eyebrow">{normalized ? "Search results" : category}</span><h3>Choose a workflow</h3></div>
            <small>{visible.length} options</small>
          </div>
          <div className="workflow-grid">
            {visible.map((workflow) => (
              <WorkflowCard key={workflow.id} workflow={workflow} onNavigate={onNavigate} />
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}

function WorkflowCard({ workflow, onNavigate }: { workflow: WorkflowDefinition; onNavigate: (route: ProductRoute) => void }) {
  const Icon = workflowIcons[workflow.id] ?? Film;
  const available = workflow.status === "available" && workflow.route;
  const openScript = () => {
    if (workflow.scriptPlatform) localStorage.setItem("dripcut.script.platform", workflow.scriptPlatform);
    onNavigate("script");
  };
  return (
    <article className={`workflow-card workflow-card--${workflow.accent}`}>
      <div className="workflow-card__icon"><Icon size={22} /></div>
      <div className="workflow-card__copy">
        <span>{workflow.badge ?? (available ? "Available" : "Development")}</span>
        <h4>{workflow.title}</h4>
        <p>{workflow.description}</p>
      </div>
      <div className="workflow-card__actions">
        <button disabled={!available} onClick={() => available && onNavigate(workflow.route!)}>
          {available ? "Start" : "In development"}
        </button>
        {experimentalTools && workflow.scriptPlatform && <button className="workflow-card__script" onClick={openScript}>AI Script</button>}
      </div>
    </article>
  );
}
