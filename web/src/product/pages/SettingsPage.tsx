import { CheckCircle2, ServerCog } from "lucide-react";

export function SettingsPage() {
  return <div className="settings-page product-page narrow-page">
    <header className="page-heading-row"><div><span className="eyebrow">Settings</span><h1>Your studio, ready to create.</h1><p>Choose formats and captions for each video before you render.</p></div></header>
    <section className="settings-cards">
      <article><ServerCog size={22} /><div><strong>Video processing</strong><span>Standard clipping works without AI</span><small>Upload a video or paste a supported YouTube link to begin.</small></div></article>
      <article><CheckCircle2 size={22} /><div><strong>Private project persistence</strong><span>Your projects belong to your workspace</span><small>Open Projects to continue working or download completed clips.</small></div></article>
    </section>
  </div>;
}
