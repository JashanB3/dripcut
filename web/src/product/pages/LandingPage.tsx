import {
  ArrowRight,
  Captions,
  Check,
  Instagram,
  LayoutTemplate,
  Menu,
  Play,
  Scissors,
  Sparkles,
  X,
  Youtube,
} from "lucide-react";
import { useState } from "react";

import { navigatePath } from "../../auth/authState";

const capabilities = [
  [Scissors, "Auto Clip", "Choose a duration and count. AI is never required."],
  [Sparkles, "Viral Moments", "Find strong hooks and complete ideas with platform-aware AI."],
  [Captions, "Smart Captions", "Readable, centered captions sized for vertical screens."],
  [Scissors, "Three formats", "Create portrait, landscape, or square clips from one source."],
] as const;

const templates = [
  ["The Clean Hook", "Podcast", "violet"],
  ["Fast Lesson", "Education", "cyan"],
  ["Founder Story", "Business", "coral"],
  ["Play by Play", "Gaming", "lime"],
] as const;

const plans = [
  { name: "Free", price: "$0", detail: "Explore the workflow", features: ["50 render credits / month", "10 clips per project", "1 connected channel", "7-day clip retention"] },
  { name: "Starter", price: "$9", detail: "For consistent creators", features: ["300 render credits / month", "YouTube + Instagram scheduling", "30-day clip retention", "Buy extra credits anytime"] },
  { name: "Creator", price: "$19", detail: "For a weekly content engine", features: ["1,000 render credits / month", "AI viral-moment analysis", "Multi-platform scheduling", "Priority render queue"] },
  { name: "Pro", price: "$49", detail: "For high-volume publishing", features: ["3,000 render credits / month", "Multiple connected channels", "Priority support", "Advanced workflow access"] },
] as const;

const faqs = [
  ["Do I need AI to make clips?", "No. Standard clipping is the default: choose a duration and number of clips, then render sequential segments."],
  ["Can I upload instead of using YouTube?", "Yes. Direct upload remains available on every clipping workflow."],
  ["Where are finished clips?", "A finished render creates a private, downloadable ZIP. Hosted deployments use signed object-storage links."],
  ["Can DripCut publish automatically?", "Connect YouTube or an Instagram professional account, choose your clips, and schedule posts from one calendar. Platform availability depends on your connected account and provider approval."],
];

export function LandingPage({ signedIn }: { signedIn: boolean }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const start = () => navigatePath(signedIn ? "/home" : "/signup");

  return (
    <div className="landing-page">
      <header className="landing-nav">
        <button className="landing-brand" onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}>
          <span>dc</span><strong>DripCut</strong>
        </button>
        <button className="landing-menu" onClick={() => setMenuOpen((value) => !value)} aria-label="Toggle navigation">
          {menuOpen ? <X /> : <Menu />}
        </button>
        <nav data-open={menuOpen}>
          <a href="#product">Product</a><a href="#workflow">How it works</a><a href="#pricing">Pricing</a><a href="#faq">FAQ</a>
        </nav>
        <div className="landing-auth-actions">
          {!signedIn && <button onClick={() => navigatePath("/login")}>Log in</button>}
          <button className="landing-gradient-button" onClick={start}>{signedIn ? "Open studio" : "Start creating free"}<ArrowRight size={16} /></button>
        </div>
      </header>

      <main>
        <section className="landing-hero">
          <div className="landing-hero__copy">
            <span className="landing-pill"><Sparkles size={14} /> Built for a consistent creator workflow</span>
            <h1><span>One video in.</span><br />A week of content out.</h1>
            <p>Turn long videos into ready-to-post Shorts and Reels with smart clipping, captions and optional AI viral moments.</p>
            <div className="landing-hero__actions">
              <button className="landing-gradient-button" onClick={start}>Start creating free <ArrowRight size={17} /></button>
              <a href="#product"><Play size={16} fill="currentColor" /> See it in action</a>
            </div>
            <div className="landing-trust"><span><Check size={13} /> Standard clips without AI</span><span><Check size={13} /> Private downloads</span><span><Check size={13} /> Portrait, landscape and square</span></div>
          </div>
          <HeroAutomation />
        </section>

        <section className="landing-proof" aria-label="Product principles">
          <strong>One simple flow</strong><span>Import</span><i /><span>Clip</span><i /><span>Caption</span><i /><span>Schedule</span><i /><span>Publish</span>
        </section>

        <section className="landing-section landing-product" id="product">
          <SectionHeading eyebrow="The complete loop" title="From raw recording to finished clips." body="DripCut keeps the essentials in one focused workspace. Choose your cuts, add captions, and download clips ready to share." />
          <div className="landing-capability-grid">
            {capabilities.map(([Icon, title, body], index) => <article key={title} style={{ "--delay": `${index * 55}ms` } as React.CSSProperties}><span><Icon size={21} /></span><h3>{title}</h3><p>{body}</p></article>)}
          </div>
        </section>

        <section className="landing-section landing-workflow" id="workflow">
          <SectionHeading eyebrow="How it works" title="Less setup. More finished content." body="Start with a video and finish with clips you can preview and download." />
          <div className="landing-steps">
            <article><b>01</b><h3>Bring the source</h3><p>Paste a supported YouTube URL or upload a video directly.</p></article>
            <article><b>02</b><h3>Choose the cuts</h3><p>Set duration and count, or optionally review AI viral moments.</p></article>
            <article><b>03</b><h3>Finish the look</h3><p>Choose a format, framing and readable captions.</p></article>
            <article><b>04</b><h3>Schedule everywhere</h3><p>Connect YouTube and Instagram, then publish both platforms in the same slot.</p></article>
          </div>
        </section>

        <section className="landing-section landing-demo">
          <div><span className="landing-section__eyebrow">Product demo</span><h2>The normal timeline always stays in control.</h2><p>Choose exactly where your clips begin and end. Optionally ask AI to suggest moments worth sharing.</p><button className="landing-gradient-button" onClick={start}>Try the workflow <ArrowRight size={16} /></button></div>
          <div className="landing-timeline-demo" aria-hidden="true"><header><span /><span /><span /><i /></header><div className="landing-demo-player"><Play fill="currentColor" /></div><div className="landing-demo-track"><span>00:00</span><b /><b /><b /><b /><em>Viral 92%</em><span>02:00</span></div></div>
        </section>

        <section className="landing-section" id="templates">
          <SectionHeading eyebrow="Original templates" title="A starting point, not a copied personality." body="Reusable systems for captions, safe zones and pacing, designed for real creator categories." />
          <div className="landing-template-grid">{templates.map(([name, category, accent]) => <article key={name} data-accent={accent}><div><LayoutTemplate /><strong>{name}</strong><span>KEEP<br />WATCHING</span></div><footer><b>{category}</b><small>9:16 · Caption safe</small></footer></article>)}</div>
        </section>

        <section className="landing-section landing-pricing" id="pricing">
          <SectionHeading eyebrow="Simple credit pricing" title="Pay for the clips you make." body="Every plan renews monthly. One render credit covers up to 30 seconds of finished video; scheduling does not use credits." />
          <div className="landing-price-grid">{plans.map((plan) => <article key={plan.name} data-featured={plan.name === "Creator"}>
            <span>{plan.name === "Creator" ? "Most popular" : plan.detail}</span><h3>{plan.name}</h3><strong>{plan.price}<small>/month</small></strong><p>{plan.detail}</p>
            <ul>{plan.features.map((feature) => <li key={feature}><Check size={15} />{feature}</li>)}</ul>
            <button className={plan.name === "Creator" ? "landing-gradient-button" : "landing-outline-button"} onClick={start}>{plan.name === "Free" ? "Start free" : "Choose plan"}</button>
          </article>)}</div>
          <p className="landing-pricing-note">Need more? Add credits whenever you need them. You will always see the credit estimate before a render starts.</p>
        </section>

        <section className="landing-section landing-use-cases">
          <div><span className="landing-section__eyebrow">Made for repeatable content</span><h2>One system, different creator rhythms.</h2></div>
          <div><article><Youtube /><h3>Podcasters</h3><p>Turn full conversations into complete, searchable Shorts.</p></article><article><Sparkles /><h3>Educators</h3><p>Extract clear lessons with readable captions and a strong payoff.</p></article><article><Instagram /><h3>Founder-led brands</h3><p>Build a consistent Reel queue from product stories and updates.</p></article></div>
        </section>

        <section className="landing-section landing-faq" id="faq"><SectionHeading eyebrow="FAQ" title="Clear answers before you start." body="No hidden dependency on AI and no mystery around the output." /><div>{faqs.map(([question, answer]) => <details key={question}><summary>{question}<span>+</span></summary><p>{answer}</p></details>)}</div></section>

        <section className="landing-final"><span><Sparkles size={16} /> Your next content week starts here</span><h2>Make the long video once.<br />Let DripCut shape the rest.</h2><button className="landing-gradient-button" onClick={start}>{signedIn ? "Continue creating" : "Start creating free"}<ArrowRight size={17} /></button></section>
      </main>

      <footer className="landing-footer"><button className="landing-brand" onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}><span>dc</span><strong>DripCut</strong></button><p>Turn long videos into clips worth sharing.</p><nav><a href="#product">Product</a><a href="#pricing">Pricing</a><a href="#faq">FAQ</a></nav><small>© {new Date().getFullYear()} DripCut</small></footer>
    </div>
  );
}

function HeroAutomation() {
  return <div className="hero-automation" aria-label="Animation showing a YouTube video becoming three downloadable vertical clips"><div className="hero-url"><Youtube size={17} /><span>youtube.com/watch?v=your-story</span><b>Import</b></div><div className="hero-video"><div className="hero-video__scene"><i /><i /><i /><strong>YOUR BIG IDEA</strong></div><div className="hero-scan"><span /><em /><em /><em /></div></div><div className="hero-clips"><article><span>THE HOOK</span><Captions /></article><article><span>THE STORY</span><Captions /></article><article><span>THE PAYOFF</span><Captions /></article></div><div className="hero-calendar"><Check size={16} /><span>Preview</span><b /><span>Download</span><b /><span>Share</span></div></div>;
}

function SectionHeading({ eyebrow, title, body }: { eyebrow: string; title: string; body: string }) {
  return <header className="landing-section-heading"><span className="landing-section__eyebrow">{eyebrow}</span><h2>{title}</h2><p>{body}</p></header>;
}
