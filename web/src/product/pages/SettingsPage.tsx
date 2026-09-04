import { CheckCircle2, ServerCog } from "lucide-react";

export function SettingsPage() {
  return <div className="settings-page product-page narrow-page">
    <header className="page-heading-row"><div><span className="eyebrow">Settings</span><h1>Simple defaults, clear infrastructure.</h1><p>DripCut uses the same API contracts on a Mac or an AWS worker.</p></div></header>
    <section className="settings-cards">
      <article><ServerCog size={22} /><div><strong>Processing API</strong><span>Same-origin `/api` service</span><small>Run the Python API beside Vite locally, or behind your production reverse proxy.</small></div></article>
      <article><CheckCircle2 size={22} /><div><strong>Private project persistence</strong><span>Configured by the processing service</span><small>Development can use local manifests. Production can use tenant metadata plus private S3/R2 storage without changing this UI.</small></div></article>
    </section>
  </div>;
}
