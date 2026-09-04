import { Check, FileVideo2, MessageSquareText, Sparkles, Upload } from "lucide-react";
import { useCallback, useRef, useState } from "react";

import { createAIEditPlan, createClipJob, uploadSource } from "../api/client";
import { ClipResults } from "../components/ClipResults";
import { CustomerError } from "../components/CustomerError";
import { RenderProgress } from "../components/RenderProgress";
import type { AIEditPlan, ApiJob, SourceAsset } from "../models";

export function AIEditorPage() {
  const input = useRef<HTMLInputElement>(null);
  const [source, setSource] = useState<SourceAsset | null>(null);
  const [prompt, setPrompt] = useState("");
  const [plan, setPlan] = useState<AIEditPlan | null>(null);
  const [job, setJob] = useState<ApiJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const load = async (file: File) => {
    setBusy(true);
    setError(null);
    try {
      setSource(await uploadSource(file));
      setPlan(null);
      setJob(null);
    } catch (reason) {
      setError(reason);
    } finally {
      setBusy(false);
    }
  };

  const createPlan = async () => {
    if (!source || !prompt.trim()) return;
    setBusy(true);
    setError(null);
    try {
      setPlan(await createAIEditPlan(source.id, prompt));
    } catch (reason) {
      setError(reason);
    } finally {
      setBusy(false);
    }
  };

  const applyPlan = async () => {
    if (!plan) return;
    setBusy(true);
    setError(null);
    try {
      setJob(await createClipJob(plan.sourceId, plan.segments, {
        outputFormat: plan.outputFormat,
        autoCaptions: plan.autoCaptions,
        platforms: [plan.platform],
      }));
    } catch (reason) {
      setError(reason);
    } finally {
      setBusy(false);
    }
  };

  const updateJob = useCallback((latest: ApiJob) => setJob(latest), []);

  if (job?.status === "succeeded") {
    return <div className="product-page"><ClipResults job={job} onBack={() => setJob(null)} /></div>;
  }
  if (job) {
    return <div className="product-page"><RenderProgress job={job} onUpdate={updateJob} onComplete={updateJob} onBack={() => setJob(null)} /></div>;
  }

  return (
    <div className="ai-editor-page product-page narrow-page">
      <header className="page-intro">
        <span className="eyebrow">AI Editor · reviewable planner</span>
        <h1>Describe the edit. Review every action.</h1>
        <p>DripCut translates a constrained prompt into a real render plan. Nothing runs until you approve it.</p>
      </header>
      {error !== null && <CustomerError error={error} fallback="The AI edit could not be completed." />}
      <div className="ai-editor-layout">
        <section className="ai-chat-preview">
          <div className="ai-chat-preview__header"><Sparkles size={18} /><strong>AI Editor</strong><span>Review first</span></div>
          <div className="ai-chat-preview__empty">
            <MessageSquareText size={32} />
            <h2>{source ? "Describe your finished clip" : "Start with a short video"}</h2>
            <p>Every AI action is constrained and shown before rendering.</p>
            {!source && <div className="prompt-examples"><span>“Make this a 20-second portrait clip.”</span><span>“Add captions for Instagram.”</span><span>“Keep it landscape with subtitles.”</span></div>}
            {plan && <div className="ai-action-plan"><strong>{plan.summary}</strong>{plan.actions.map((action) => <span key={action.kind}><Check size={14} /> {action.label}: {String(action.value)}</span>)}</div>}
          </div>
          <div className="ai-prompt-disabled"><input value={prompt} disabled={!source || busy} onChange={(event) => setPrompt(event.target.value)} placeholder="Example: Make a 20-second portrait clip with captions" onKeyDown={(event) => event.key === "Enter" && void createPlan()} /><button disabled={!source || !prompt.trim() || busy} onClick={() => void createPlan()}><Sparkles size={15} /> {busy ? "Planning…" : "Plan edit"}</button></div>
          {plan && <button className="primary-action ai-apply-plan" disabled={busy} onClick={() => void applyPlan()}>Apply approved edit</button>}
        </section>
        <aside className="ai-source-preview">
          {source ? <video controls playsInline preload="metadata" src={source.mediaUrl} poster={source.thumbnailUrl} /> : <FileVideo2 size={30} />}
          <h2>{source?.name ?? "Add a video"}</h2>
          <p>{source ? `${Math.round(source.duration)} seconds · ready to plan` : "Upload a video to create a safe edit plan."}</p>
          <button disabled={busy} onClick={() => input.current?.click()}><Upload size={16} /> {source ? "Change source" : "Upload video"}</button>
          <input ref={input} className="dc-visually-hidden" type="file" accept="video/*" onChange={(event) => { const file = event.target.files?.[0]; if (file) void load(file); event.currentTarget.value = ""; }} />
        </aside>
      </div>
    </div>
  );
}
