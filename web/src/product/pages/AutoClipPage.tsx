import { ArrowLeft, Check, LoaderCircle, Sparkles } from "lucide-react";
import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import { createClipJob, findViralMoments, getClipJob, getProject, importYouTube, uploadSource } from "../api/client";
import { ClipControls } from "../components/ClipControls";
import { ClipResults } from "../components/ClipResults";
import { CustomerError } from "../components/CustomerError";
import { RenderProgress } from "../components/RenderProgress";
import { SourcePicker } from "../components/SourcePicker";
import { SourceTimeline } from "../components/SourceTimeline";
import type { ApiJob, ProductRoute, RuntimeSource, SourceAsset } from "../models";
import { autoClipReducer, initialAutoClipState, selectedDuration, selectedSegments } from "../state/autoClipReducer";
import { findClipTemplate } from "../templates/catalog";

const stepIndex = { source: 0, configure: 1, "render-preview": 2, results: 2 } as const;

export function AutoClipPage({ onNavigate }: { onNavigate: (route: ProductRoute) => void }) {
  const [state, dispatch] = useReducer(autoClipReducer, initialAutoClipState);
  const [runtime, setRuntime] = useState<RuntimeSource | null>(null);
  const [sourceError, setSourceError] = useState<unknown>(null);
  const [sourceBusy, setSourceBusy] = useState<"upload" | "youtube" | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [sourceStage, setSourceStage] = useState("");
  const [failedSourceKind, setFailedSourceKind] = useState<"upload" | "youtube" | null>(null);
  const [job, setJob] = useState<ApiJob | null>(null);
  const [starting, setStarting] = useState(false);
  const [aiBusy, setAiBusy] = useState(false);
  const [restoringProject, setRestoringProject] = useState(
    () => Boolean(window.localStorage.getItem("dripcut.activeProjectId")),
  );
  const videoRef = useRef<HTMLVideoElement>(null);

  const acceptSource = (source: SourceAsset, file?: File) => {
    setRuntime({ id: source.id, url: source.mediaUrl, file });
    dispatch({ type: "source-loaded", source });
  };

  const loadFile = async (file: File) => {
    setSourceError(null);
    setFailedSourceKind(null);
    setSourceBusy("upload");
    setUploadProgress(0);
    setSourceStage("Uploading video");
    try {
      acceptSource(await uploadSource(file, setUploadProgress), file);
    } catch (error) {
      setSourceError(error);
      setFailedSourceKind("upload");
    } finally {
      setSourceBusy(null);
      setSourceStage("");
    }
  };

  const loadYouTube = async (url: string, rightsConfirmed: boolean) => {
    setSourceError(null);
    setFailedSourceKind(null);
    setSourceBusy("youtube");
    setUploadProgress(0);
    setSourceStage("Fetching video information");
    try {
      acceptSource(await importYouTube(url, rightsConfirmed, (percent, stage) => {
        setUploadProgress(percent);
        setSourceStage(stage);
      }));
    } catch (error) {
      setSourceError(error);
      setFailedSourceKind("youtube");
    } finally {
      setSourceBusy(null);
      setSourceStage("");
    }
  };

  useEffect(() => {
    const template = findClipTemplate(window.localStorage.getItem("dripcut.selectedTemplate"));
    if (template) {
      dispatch({ type: "apply-template", template });
      window.localStorage.removeItem("dripcut.selectedTemplate");
    }
    const projectId = window.localStorage.getItem("dripcut.activeProjectId");
    if (!projectId) return;
    let active = true;
    void (async () => {
      try {
        const project = await getProject(projectId);
        if (!active) return;
        if (!project.source) throw new Error("This saved project no longer has an available source video.");

        setRuntime({ id: project.source.id, url: project.source.mediaUrl });
        dispatch({ type: "source-loaded", source: project.source });

        if (project.latestJobId) {
          const restoredJob = await getClipJob(project.latestJobId);
          if (!active) return;
          setJob(restoredJob);
          const hasFinishedClips = restoredJob.artifacts.some((artifact) => artifact.kind === "clip");
          if (restoredJob.status === "succeeded" && hasFinishedClips) {
            dispatch({ type: "show-results" });
          } else if (restoredJob.status !== "succeeded") {
            dispatch({ type: "preview-render" });
          }
        }
      } catch (error) {
        if (active) setSourceError(error);
      } finally {
        window.localStorage.removeItem("dripcut.activeProjectId");
        if (active) setRestoringProject(false);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  const reset = () => {
    setRuntime(null);
    setJob(null);
    dispatch({ type: "reset" });
  };

  const currentStep = stepIndex[state.phase];
  const segments = selectedSegments(state);

  const toggleAI = async () => {
    if (!state.source) return;
    if (state.aiEnabled) {
      dispatch({ type: "set-ai-enabled", value: false });
      return;
    }
    dispatch({ type: "set-ai-enabled", value: true });
    setAiBusy(true);
    setSourceError(null);
    try {
      const platform = state.platforms.includes("instagram") ? "instagram" : "youtube";
      const recommendations = await findViralMoments(
        state.source.id,
        platform,
        selectedDuration(state),
        Math.max(1, Math.min(20, state.count || 8)),
      );
      dispatch({ type: "set-recommendations", recommendations });
      if (recommendations.length === 0) {
        setSourceError("AI did not find a complete standalone moment. Sequential clipping is still ready.");
      }
    } catch (error) {
      dispatch({ type: "set-ai-enabled", value: false });
      setSourceError(error);
    } finally {
      setAiBusy(false);
    }
  };

  const startRender = async () => {
    if (!state.source || segments.length === 0) return;
    setStarting(true);
    setSourceError(null);
    try {
      const created = await createClipJob(state.source.id, segments, {
        outputFormat: state.outputFormat,
        autoCaptions: state.autoCaptions,
        platforms: state.platforms,
        captionStyle: state.captionStyle,
      });
      setJob(created);
      dispatch({ type: "preview-render" });
    } catch (error) {
      setSourceError(error);
    } finally {
      setStarting(false);
    }
  };

  const updateJob = useCallback((latest: ApiJob) => setJob(latest), []);
  const finishJob = useCallback((latest: ApiJob) => {
    setJob(latest);
    dispatch({ type: "show-results" });
  }, []);

  return (
    <div className="auto-clip-page product-page">
      <header className="auto-clip-topline">
        <div><span className="eyebrow"><Sparkles size={13} /> Auto Clip</span><h1>One source. A whole content plan.</h1>{state.templateId && <small className="active-template-note">Template preset applied</small>}</div>
        <div className="workflow-steps">
          {["Source", "Clips", "Finish"].map((step, index) => <span key={step} data-active={currentStep === index} data-complete={currentStep > index}><i>{currentStep > index ? <Check size={12} /> : index + 1}</i>{step}</span>)}
        </div>
      </header>
      {sourceError !== null && <CustomerError error={sourceError} fallback="This clipping action could not be completed." />}
      {state.phase === "source" && restoringProject && (
        <section className="source-step project-restore-state" role="status">
          <LoaderCircle className="spin" size={30} />
          <strong>Restoring your saved project…</strong>
          <span>Loading the source and latest completed clips.</span>
        </section>
      )}
      {state.phase === "source" && !restoringProject && <SourcePicker onFile={(file) => void loadFile(file)} onYouTube={(url, rightsConfirmed) => void loadYouTube(url, rightsConfirmed)} busy={sourceBusy} progress={uploadProgress} stage={sourceStage} youtubeFailed={failedSourceKind === "youtube" && sourceError !== null} />}
      {state.phase === "configure" && runtime && (
        <>
          <button className="workflow-back" onClick={reset}><ArrowLeft size={16} /> Change source</button>
          <div className="configure-layout">
            <SourceTimeline state={state} dispatch={dispatch} runtime={runtime} videoRef={videoRef} />
            <ClipControls state={state} dispatch={dispatch} onCreate={() => void startRender()} onToggleAI={() => void toggleAI()} starting={starting} aiBusy={aiBusy} />
          </div>
        </>
      )}
      {state.phase === "render-preview" && job && <RenderProgress job={job} onUpdate={updateJob} onComplete={finishJob} onBack={() => dispatch({ type: "back-to-configure" })} />}
      {state.phase === "results" && job && <ClipResults job={job} onBack={() => dispatch({ type: "back-to-configure" })} onSchedule={(artifactId, clipName) => { window.localStorage.setItem("dripcut.activeProjectId", job.projectId); window.localStorage.setItem("dripcut.scheduleArtifactId", artifactId); window.localStorage.setItem("dripcut.scheduleClipName", clipName); onNavigate("schedule"); }} />}
    </div>
  );
}
