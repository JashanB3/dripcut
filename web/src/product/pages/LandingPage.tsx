import {
  ArrowRight,
  CalendarClock,
  Captions,
  Check,
  Clapperboard,
  Instagram,
  LayoutTemplate,
  Menu,
  Play,
  Scissors,
  Sparkles,
  WandSparkles,
  X,
  Youtube,
} from "lucide-react";
import { useState } from "react";

import { navigatePath } from "../../auth/authState";

const capabilities = [
  [Scissors, "Auto Clip", "Choose a duration and count. AI is never required."],
  [Sparkles, "Viral Moments", "Find strong hooks and complete ideas with platform-aware AI."],
  [Captions, "Smart Captions", "Readable, centered captions sized for vertical screens."],
  [WandSparkles, "AI Editor", "Describe the outcome. DripCut builds a safe, editable plan."],
  [Clapperboard, "AI Thumbnails", "Rank clear, expressive frames and generate a creative brief."],
  [CalendarClock, "Auto Schedule", "Review the plan, then publish through official platform APIs."],
] as const;

const templates = [
  ["The Clean Hook", "Podcast", "violet"],
  ["Fast Lesson", "Education", "cyan"],
  ["Founder Story", "Business", "coral"],
  ["Play by Play", "Gaming", "lime"],
] as const;

const faqs = [
  ["Do I need AI to make clips?", "No. Standard clipping is the default: choose a duration and number of clips, then render sequential segments."],
  ["Can I upload instead of using YouTube?", "Yes. Direct upload remains available on every clipping workflow."],
  ["Where are finished clips?", "A finished render creates a private, downloadable ZIP. Hosted deployments use signed object-storage links."],
  ["Can DripCut publish automatically?", "Yes, after you connect an eligible YouTube channel or Instagram professional account through official OAuth."],
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
          <a href="#product">Product</a><a href="#workflow">How it works</a><a href="#templates">Templates</a><a href="#pricing">Pricing</a><a href="#faq">FAQ</a>
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
            <p>Turn long videos into ready-to-post Shorts and Reels with smart clipping, captions, thumbnails and automatic scheduling.</p>
            <div className="landing-hero__actions">
              <button className="landing-gradient-button" onClick={start}>Start creating free <ArrowRight size={17} /></button>
              <a href="#product"><Play size={16} fill="currentColor" /> See it in action</a>
            </div>
            <div className="landing-trust"><span><Check size={13} /> Standard clips without AI</span><span><Check size={13} /> Private downloads</span><span><Check size={13} /> Official publishing APIs</span></div>
          </div>
          <HeroAutomation />
        </section>

        <section className="landing-proof" aria-label="Product principles">
          <strong>One simple flow</strong><span>Import</span><i /><span>Clip</span><i /><span>Caption</span><i /><span>Review</span><i /><span>Schedule</span>
        </section>

        <section className="landing-section landing-product" id="product">
          <SectionHeading eyebrow="The complete loop" title="From raw recording to publishing rhythm." body="DripCut keeps the essentials in one focused workspace. Use the standard flow, then add AI only where it genuinely helps." />
          <div className="landing-capability-grid">
            {capabilities.map(([Icon, title, body], index) => <article key={title} style={{ "--delay": `${index * 55}ms` } as React.CSSProperties}><span><Icon size={21} /></span><h3>{title}</h3><p>{body}</p></article>)}
          </div>
        </section>

        <section className="landing-section landing-workflow" id="workflow">
          <SectionHeading eyebrow="How it works" title="Less setup. More finished content." body="Every step stays visible and editable, so automation never turns into a black box." />
          <div className="landing-steps">
            <article><b>01</b><h3>Bring the source</h3><p>Paste a supported YouTube URL or upload a video directly.</p></article>
            <article><b>02</b><h3>Choose the cuts</h3><p>Set duration and count, or optionally review AI viral moments.</p></article>
            <article><b>03</b><h3>Finish the look</h3><p>Pick format, captions, framing and a thumbnail direction.</p></article>
            <article><b>04</b><h3>Download or publish</h3><p>Review the ZIP or schedule clips across connected accounts.</p></article>
          </div>
        </section>

        <section className="landing-section landing-demo">
          <div><span className="landing-section__eyebrow">Product demo</span><h2>The normal timeline always stays in control.</h2><p>Equal clip boundaries remain clear. AI recommendations appear as an optional layer, never a separate rendering engine.</p><button className="landing-gradient-button" onClick={start}>Try the workflow <ArrowRight size={16} /></button></div>
          <div className="landing-timeline-demo" aria-hidden="true"><header><span /><span /><span /><i /></header><div className="landing-demo-player"><Play fill="currentColor" /></div><div className="landing-demo-track"><span>00:00</span><b /><b /><b /><b /><em>Viral 92%</em><span>02:00</span></div></div>
        </section>

        <section className="landing-section" id="templates">
          <SectionHeading eyebrow="Original templates" title="A starting point, not a copied personality." body="Reusable systems for captions, safe zones and pacing, designed for real creator categories." />
          <div className="landing-template-grid">{templates.map(([name, category, accent]) => <article key={name} data-accent={accent}><div><LayoutTemplate /><strong>{name}</strong><span>KEEP<br />WATCHING</span></div><footer><b>{category}</b><small>9:16 · Caption safe</small></footer></article>)}</div>
        </section>

        <section className="landing-section landing-use-cases">
          <div><span className="landing-section__eyebrow">Made for repeatable content</span><h2>One system, different creator rhythms.</h2></div>
          <div><article><Youtube /><h3>Podcasters</h3><p>Turn full conversations into complete, searchable Shorts.</p></article><article><Sparkles /><h3>Educators</h3><p>Extract clear lessons with readable captions and a strong payoff.</p></article><article><Instagram /><h3>Founder-led brands</h3><p>Build a consistent Reel queue from product stories and updates.</p></article></div>
        </section>

        <section className="landing-section landing-pricing" id="pricing">
          <SectionHeading eyebrow="Pricing preview" title="Start useful. Upgrade when your volume grows." body="Limits are enforced by the server and shown clearly before an expensive action." />
          <div className="landing-price-grid"><PriceCard name="Free" price="$0" detail="Experience the real workflow" items={["Standard auto clipping", "Limited AI analyses", "Private ZIP downloads"]} /><PriceCard featured name="Creator" price="Flexible" detail="For a consistent publishing rhythm" items={["More processing minutes", "AI editor and thumbnails", "Social scheduling"]} /><PriceCard name="Pro" price="Flexible" detail="For teams and higher volume" items={["Higher limits", "Workspace collaboration", "Priority processing"]} /></div>
        </section>

        <section className="landing-section landing-faq" id="faq"><SectionHeading eyebrow="FAQ" title="Clear answers before you start." body="No hidden dependency on AI and no mystery around the output." /><div>{faqs.map(([question, answer]) => <details key={question}><summary>{question}<span>+</span></summary><p>{answer}</p></details>)}</div></section>

        <section className="landing-final"><span><Sparkles size={16} /> Your next content week starts here</span><h2>Make the long video once.<br />Let DripCut shape the rest.</h2><button className="landing-gradient-button" onClick={start}>{signedIn ? "Continue creating" : "Start creating free"}<ArrowRight size={17} /></button></section>
      </main>

      <footer className="landing-footer"><button className="landing-brand" onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}><span>dc</span><strong>DripCut</strong></button><p>Creator-first clipping, captions and scheduling.</p><nav><a href="#product">Product</a><a href="#pricing">Pricing</a><a href="#faq">FAQ</a></nav><small>© {new Date().getFullYear()} DripCut</small></footer>
    </div>
  );
}

function HeroAutomation() {
  return <div className="hero-automation" aria-label="Animation showing a YouTube video becoming three scheduled vertical clips"><div className="hero-url"><Youtube size={17} /><span>youtube.com/watch?v=your-story</span><b>Import</b></div><div className="hero-video"><div className="hero-video__scene"><i /><i /><i /><strong>YOUR BIG IDEA</strong></div><div className="hero-scan"><span /><em /><em /><em /></div></div><div className="hero-clips"><article><span>THE HOOK</span><Captions /></article><article><span>THE STORY</span><Captions /></article><article><span>THE PAYOFF</span><Captions /></article></div><div className="hero-calendar"><CalendarClock size={16} /><span>Mon</span><b /><span>Wed</span><b /><span>Fri</span><i><Youtube size={13} /><Instagram size={13} /></i></div></div>;
}

function SectionHeading({ eyebrow, title, body }: { eyebrow: string; title: string; body: string }) {
  return <header className="landing-section-heading"><span className="landing-section__eyebrow">{eyebrow}</span><h2>{title}</h2><p>{body}</p></header>;
}

function PriceCard({ name, price, detail, items, featured = false }: { name: string; price: string; detail: string; items: string[]; featured?: boolean }) {
  return <article data-featured={featured}><span>{featured ? "Most creator-friendly" : name}</span><h3>{name}</h3><strong>{price}</strong><p>{detail}</p><ul>{items.map((item) => <li key={item}><Check size={14} /> {item}</li>)}</ul><button className={featured ? "landing-gradient-button" : "landing-outline-button"} onClick={() => navigatePath("/signup")}>Get started</button></article>;
}
