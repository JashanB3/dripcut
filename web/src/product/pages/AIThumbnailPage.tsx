import { Download, ImagePlus, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";

import { createThumbnailCandidates, fetchProjects } from "../api/client";
import type { ApiArtifact, ApiProject, Platform } from "../models";

export function AIThumbnailPage() {
  const [projects, setProjects] = useState<ApiProject[]>([]);
  const [projectId, setProjectId] = useState("");
  const [prompt, setPrompt] = useState("");
  const [target, setTarget] = useState<Platform>("youtube");
  const [candidates, setCandidates] = useState<ApiArtifact[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    void fetchProjects(100).then((items) => {
      const usable = items.filter((item) => item.sourceAssetId);
      setProjects(usable);
      setProjectId(usable[0]?.id ?? "");
    }).catch(() => setError("Projects could not load."));
  }, []);

  const generate = async () => {
    if (!projectId) return;
    setBusy(true);
    setError("");
    try {
      setCandidates(await createThumbnailCandidates(projectId, prompt, target));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Candidates could not be created.");
    } finally {
      setBusy(false);
    }
  };

  return <div className="thumbnail-page product-page">
    <header className="page-heading-row"><div><span className="eyebrow">Smart thumbnails</span><h1>Find the frame that earns the click.</h1><p>Local candidate extraction today, with a provider boundary ready for generative models later.</p></div></header>
    {error && <div className="source-error-banner">{error}</div>}
    <section className="thumbnail-controls">
      <label><span>Project</span><select value={projectId} onChange={(event) => setProjectId(event.target.value)}>{projects.map((project) => <option key={project.id} value={project.id}>{project.title}</option>)}</select></label>
      <label><span>Creative direction</span><input value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="High energy, clear subject, no text" /></label>
      <label><span>Destination</span><select value={target} onChange={(event) => setTarget(event.target.value as Platform)}><option value="youtube">YouTube</option><option value="instagram">Instagram</option></select></label>
      <button className="primary-action" disabled={!projectId || busy} onClick={() => void generate()}><Sparkles size={16} /> {busy ? "Finding frames…" : "Create candidates"}</button>
    </section>
    {projects.length === 0 && <div className="projects-empty projects-empty--large"><ImagePlus size={30} /><strong>No source projects yet</strong><span>Create a project before extracting thumbnails.</span></div>}
    <div className="thumbnail-grid">{candidates.map((candidate) => <article key={candidate.id}>{candidate.streamUrl && <img src={candidate.streamUrl} alt={`Thumbnail candidate ${candidate.index}`} />}<div><strong>Candidate {candidate.index}</strong><a href={candidate.downloadUrl} download><Download size={14} /> Download</a></div></article>)}</div>
  </div>;
}
