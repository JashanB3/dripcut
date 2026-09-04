import { Clapperboard, Download, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { apiUrl, fetchProjects } from "../api/client";
import { CustomerError } from "../components/CustomerError";
import type { ApiProject, ProductRoute } from "../models";

export function ProjectsPage({ onNavigate }: { onNavigate: (route: ProductRoute) => void }) {
  const [projects, setProjects] = useState<ApiProject[]>([]);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const refresh = useCallback(() => {
    setBusy(true);
    setError(null);
    void fetchProjects(100)
      .then(setProjects)
      .catch(setError)
      .finally(() => setBusy(false));
  }, []);

  useEffect(refresh, [refresh]);

  const openProject = (project: ApiProject) => {
    window.localStorage.setItem("dripcut.activeProjectId", project.id);
    onNavigate(project.workflowRoute);
  };

  return (
    <div className="projects-page product-page">
      <header className="page-heading-row">
        <div><span className="eyebrow">Library</span><h1>Your projects</h1><p>Every imported source and finished render, saved automatically.</p></div>
        <button className="secondary-action" onClick={refresh} disabled={busy}><RefreshCw size={16} /> Refresh</button>
      </header>
      {error !== null && <CustomerError error={error} fallback="Projects could not load." onRetry={refresh} />}
      {!busy && projects.length === 0 && <div className="projects-empty projects-empty--large"><Clapperboard size={30} /><strong>No projects yet</strong><span>Your first source will appear here and remain available after a restart.</span><button onClick={() => onNavigate("auto-clip")}>Create clips</button></div>}
      <div className="projects-grid">
        {projects.map((project) => (
          <article key={project.id} className="library-project-card">
            <button className="library-project-card__preview" onClick={() => openProject(project)} style={project.thumbnailUrl ? { backgroundImage: `url(${project.thumbnailUrl})` } : undefined}>
              {!project.thumbnailUrl && <Clapperboard size={32} />}
              <span>{project.status}</span>
            </button>
            <div><strong>{project.title}</strong><span>{project.clipCount} clips · {project.outputFormat} · {project.captionsEnabled ? "captions" : "clean"}</span><small>Updated {new Date(project.updatedAt * 1000).toLocaleString()}</small></div>
            <footer><button onClick={() => openProject(project)}>Open</button>{project.downloadArtifactId && <a href={apiUrl(`/api/artifacts/${project.downloadArtifactId}/download`)} download><Download size={14} /> Download</a>}</footer>
          </article>
        ))}
      </div>
    </div>
  );
}
