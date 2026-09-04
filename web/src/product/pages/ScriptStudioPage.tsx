import {
  BookOpenText,
  Check,
  Clock3,
  FilePenLine,
  Instagram,
  MessageCircleMore,
  RefreshCw,
  Save,
  Sparkles,
  WandSparkles,
  Youtube,
  Zap,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  createManualScript,
  fetchContentItem,
  generateScript,
  runScriptAction,
  updateContentItem,
} from "../api/client";
import { CustomerError } from "../components/CustomerError";
import type { ContentItem, Platform, ScriptAction, ScriptBrief, ScriptWorkspace } from "../models";
import {
  countScriptWords,
  estimateScriptDuration,
  initialScriptBrief,
  LAST_SCRIPT_KEY,
  SCRIPT_PLATFORM_KEY,
  scriptSnapshot,
} from "../state/scriptStudio";

type Operation = ScriptAction | "generate" | "save";

const actions: Array<{ id: ScriptAction; label: string; detail: string; icon: typeof Sparkles }> = [
  { id: "rewrite_hook", label: "Rewrite hook", detail: "Open with a stronger first line", icon: Zap },
  { id: "generate_hooks", label: "Alternate hooks", detail: "Create fresh openings to choose from", icon: Sparkles },
  { id: "shorten", label: "Shorten", detail: "Keep the payoff, lose the filler", icon: Clock3 },
  { id: "expand", label: "Expand", detail: "Add useful detail and examples", icon: BookOpenText },
  { id: "conversational", label: "Make conversational", detail: "Sound natural when spoken", icon: MessageCircleMore },
  { id: "educational", label: "Make educational", detail: "Clarify the lesson and structure", icon: BookOpenText },
  { id: "engaging", label: "Make more engaging", detail: "Improve momentum without clickbait", icon: WandSparkles },
  { id: "rewrite_cta", label: "Rewrite CTA", detail: "End with a natural next step", icon: RefreshCw },
];

export function ScriptStudioPage() {
  const storedPlatform = localStorage.getItem(SCRIPT_PLATFORM_KEY);
  const [brief, setBrief] = useState<ScriptBrief>(() => initialScriptBrief(storedPlatform === "instagram" ? "instagram" : "youtube"));
  const [item, setItem] = useState<ContentItem | null>(null);
  const [title, setTitle] = useState("Untitled script");
  const [hook, setHook] = useState("");
  const [script, setScript] = useState("");
  const [alternateHooks, setAlternateHooks] = useState<string[]>([]);
  const [busy, setBusy] = useState<Operation | null>(null);
  const [retryOperation, setRetryOperation] = useState<Operation | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [saveStatus, setSaveStatus] = useState("New draft");
  const savedSnapshot = useRef("");

  const hydrateItem = useCallback((content: ContentItem, hooks: string[] = []) => {
    setItem(content);
    setTitle(content.title);
    setHook(content.hook ?? "");
    setScript(content.script ?? "");
    setAlternateHooks(hooks.length ? hooks : readHooks(content));
    setBrief((current) => ({
      ...current,
      topic: current.topic || content.title,
      platform: readPlatform(content) ?? current.platform,
      language: content.language ?? current.language,
      targetDurationSeconds: Math.round(content.durationSeconds ?? current.targetDurationSeconds),
    }));
    savedSnapshot.current = scriptSnapshot(content.title, content.hook ?? "", content.script ?? "");
    localStorage.setItem(LAST_SCRIPT_KEY, content.id);
    setSaveStatus("Saved");
  }, []);

  useEffect(() => {
    const contentId = localStorage.getItem(LAST_SCRIPT_KEY);
    if (!contentId) return;
    void fetchContentItem(contentId).then((content) => {
      hydrateItem(content);
    }).catch((reason: unknown) => {
      if (reason instanceof ApiError && reason.status === 404) {
        localStorage.removeItem(LAST_SCRIPT_KEY);
        return;
      }
      setError(reason);
    });
  }, [hydrateItem]);

  useEffect(() => {
    localStorage.setItem(SCRIPT_PLATFORM_KEY, brief.platform);
  }, [brief.platform]);

  useEffect(() => {
    if (!item) return;
    if (scriptSnapshot(title, hook, script) !== savedSnapshot.current) setSaveStatus("Unsaved changes");
  }, [hook, item, script, title]);

  const applyWorkspace = (workspace: ScriptWorkspace) => {
    hydrateItem(workspace.item, workspace.alternateHooks);
  };

  const updateBrief = <Key extends keyof ScriptBrief>(key: Key, value: ScriptBrief[Key]) => {
    setBrief((current) => ({ ...current, [key]: value }));
  };

  const createWithAI = async () => {
    if (!brief.topic.trim()) {
      setError(new ApiError("Add a topic before generating your script."));
      return;
    }
    setBusy("generate");
    setRetryOperation("generate");
    setError(null);
    try {
      applyWorkspace(await generateScript(brief, item?.projectId));
      setRetryOperation(null);
    } catch (reason) {
      setError(reason);
    } finally {
      setBusy(null);
    }
  };

  const persist = async (): Promise<ContentItem | null> => {
    if (!script.trim()) {
      setError(new ApiError("Write, paste, or generate a script before saving."));
      return null;
    }
    setBusy("save");
    setRetryOperation("save");
    setSaveStatus("Saving…");
    setError(null);
    try {
      if (item) {
        const saved = await updateContentItem(item.id, {
          title: title.trim() || "Untitled script",
          hook: hook.trim() || undefined,
          script,
          durationSeconds: estimateScriptDuration(script) || brief.targetDurationSeconds,
          language: brief.language,
          status: "review",
        });
        hydrateItem(saved, alternateHooks);
        setRetryOperation(null);
        return saved;
      }
      const workspace = await createManualScript({
        title: title.trim() || brief.topic.trim() || "Untitled script",
        script,
        platform: brief.platform,
        language: brief.language,
        targetDurationSeconds: brief.targetDurationSeconds,
      });
      applyWorkspace(workspace);
      setRetryOperation(null);
      return workspace.item;
    } catch (reason) {
      setError(reason);
      setSaveStatus("Save failed");
      return null;
    } finally {
      setBusy(null);
    }
  };

  const runAction = async (action: ScriptAction) => {
    const saved = await persist();
    if (!saved) return;
    setBusy(action);
    setRetryOperation(action);
    setError(null);
    try {
      applyWorkspace(await runScriptAction(saved.id, action, {
        ...brief,
        topic: brief.topic.trim() || title,
        platform: action === "adapt_instagram" ? "instagram" : action === "adapt_youtube" ? "youtube" : brief.platform,
      }));
      setRetryOperation(null);
    } catch (reason) {
      setError(reason);
    } finally {
      setBusy(null);
    }
  };

  const retry = () => {
    if (retryOperation === "generate") void createWithAI();
    else if (retryOperation === "save") void persist();
    else if (retryOperation) void runAction(retryOperation);
  };

  const chooseHook = (value: string) => {
    setHook(value);
    const paragraphs = script.split(/\n\s*\n/);
    setScript([value, ...paragraphs.slice(hook ? 1 : 0)].join("\n\n"));
  };

  const wordCount = countScriptWords(script);
  const liveDuration = estimateScriptDuration(script);

  return (
    <div className="script-studio-page product-page">
      <header className="page-heading-row script-studio-heading">
        <div>
          <span className="eyebrow">AI Script Studio</span>
          <h1>Shape the idea before you hit record.</h1>
          <p>Write from scratch or generate a structured, editable script for Shorts and Reels.</p>
        </div>
        <div className="script-save-state" data-state={saveStatus === "Saved" ? "saved" : "draft"}>
          {saveStatus === "Saved" && <Check size={15} />}{saveStatus}
        </div>
      </header>

      {error !== null && <CustomerError error={error} fallback="The script action could not be completed." onRetry={retryOperation ? retry : undefined} />}

      <div className="script-studio-layout">
        <aside className="script-controls script-panel">
          <div className="script-panel__heading"><span>01</span><div><strong>Creative brief</strong><small>Give AI the right context</small></div></div>
          <label><span>Topic</span><textarea value={brief.topic} onChange={(event) => updateBrief("topic", event.target.value)} placeholder="What should this video be about?" rows={3} /></label>
          <div className="script-platform-toggle" aria-label="Platform">
            <button data-selected={brief.platform === "youtube"} onClick={() => updateBrief("platform", "youtube")}><Youtube size={17} /> YouTube Shorts</button>
            <button data-selected={brief.platform === "instagram"} onClick={() => updateBrief("platform", "instagram")}><Instagram size={17} /> Instagram Reels</button>
          </div>
          <label><span>Audience</span><input value={brief.audience} onChange={(event) => updateBrief("audience", event.target.value)} /></label>
          <label><span>Tone</span><select value={brief.tone} onChange={(event) => updateBrief("tone", event.target.value)}><option>Conversational</option><option>Educational</option><option>Energetic</option><option>Bold</option><option>Storytelling</option><option>Professional</option></select></label>
          <div className="script-two-fields">
            <label><span>Language</span><select value={brief.language} onChange={(event) => updateBrief("language", event.target.value)}><option value="en">English</option><option value="hi">Hindi</option><option value="es">Spanish</option><option value="fr">French</option></select></label>
            <label><span>Target</span><select value={brief.targetDurationSeconds} onChange={(event) => updateBrief("targetDurationSeconds", Number(event.target.value))}><option value={15}>15 sec</option><option value={30}>30 sec</option><option value={45}>45 sec</option><option value={60}>60 sec</option><option value={90}>90 sec</option></select></label>
          </div>
          <label><span>Content goal</span><input value={brief.contentGoal} onChange={(event) => updateBrief("contentGoal", event.target.value)} /></label>
          <label><span>Call to action</span><input value={brief.cta} onChange={(event) => updateBrief("cta", event.target.value)} placeholder="What should viewers do next?" /></label>
          <label><span>Reference text <em>optional</em></span><textarea value={brief.referenceText} onChange={(event) => updateBrief("referenceText", event.target.value)} placeholder="Paste facts, notes, or source copy" rows={4} /></label>
          <button className="primary-action script-generate" disabled={busy !== null} onClick={() => void createWithAI()}><Sparkles size={17} /> {busy === "generate" ? "Writing your script…" : "Generate script"}</button>
        </aside>

        <section className="script-editor script-panel">
          <div className="script-editor__toolbar">
            <div><FilePenLine size={18} /><strong>Editable script</strong></div>
            <span>{wordCount} words · {liveDuration || brief.targetDurationSeconds}s read</span>
          </div>
          <input className="script-title-input" aria-label="Script title" value={title} onChange={(event) => setTitle(event.target.value)} />
          <label className="script-hook-field"><span>Hook</span><textarea aria-label="Script hook" value={hook} onChange={(event) => setHook(event.target.value)} placeholder="Your opening line appears here" rows={2} /></label>
          <textarea className="script-body-editor" aria-label="Script body" value={script} onChange={(event) => setScript(event.target.value)} placeholder="Write here, paste your own script, or use Generate script to begin." />
          {alternateHooks.length > 0 && <div className="alternate-hooks"><strong>Choose an alternate hook</strong>{alternateHooks.map((value) => <button key={value} onClick={() => chooseHook(value)}>{value}</button>)}</div>}
          <div className="script-editor__footer">
            <span>{item ? `Draft ${item.id.slice(0, 8)}` : "Not saved yet"}</span>
            <button className="secondary-action" disabled={busy !== null || !script.trim()} onClick={() => void persist()}><Save size={15} /> {busy === "save" ? "Saving…" : "Save draft"}</button>
          </div>
        </section>

        <aside className="script-actions script-panel">
          <div className="script-panel__heading"><span>02</span><div><strong>AI actions</strong><small>Refine without losing control</small></div></div>
          <div className="script-action-list">
            {actions.map(({ id, label, detail, icon: Icon }) => <button key={id} disabled={busy !== null || !script.trim()} onClick={() => void runAction(id)}><Icon size={17} /><span><strong>{busy === id ? "Working…" : label}</strong><small>{detail}</small></span></button>)}
          </div>
          <div className="script-adapt-actions">
            <span>Adapt the full script</span>
            <button disabled={busy !== null || !script.trim()} onClick={() => void runAction("adapt_youtube")}><Youtube size={17} /> YouTube Shorts</button>
            <button disabled={busy !== null || !script.trim()} onClick={() => void runAction("adapt_instagram")}><Instagram size={17} /> Instagram Reels</button>
          </div>
          <div className="script-ai-note"><Sparkles size={16} /><span><strong>You stay in control.</strong> Every AI result remains editable and is only saved to your workspace.</span></div>
        </aside>
      </div>
    </div>
  );
}

function readPlatform(item: ContentItem): Platform | null {
  const value = item.metadata.intended_platform;
  return value === "youtube" || value === "instagram" ? value : null;
}

function readHooks(item: ContentItem): string[] {
  const value = item.metadata.alternate_hooks;
  return Array.isArray(value) ? value.filter((entry): entry is string => typeof entry === "string") : [];
}
