import {
  ArrowRight,
  CalendarClock,
  Captions,
  Check,
  Clock3,
  Instagram,
  Link2,
  Menu,
  Play,
  Scissors,
  Sparkles,
  WandSparkles,
  X,
  Youtube,
  Zap,
} from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

import { navigatePath } from "../../auth/authState";

type MarketingPageKind = "home" | "pricing" | "about";

const MRBEAST_VIDEO_URL = "https://www.youtube.com/watch?v=aKq8bkY5eTU";
const MRBEAST_THUMBNAIL = "https://i.ytimg.com/vi/aKq8bkY5eTU/maxresdefault.jpg";
const MRBEAST_CLIP_THUMBNAILS = [
  "https://i.ytimg.com/vi/aKq8bkY5eTU/hq1.jpg",
  "https://i.ytimg.com/vi/aKq8bkY5eTU/hq2.jpg",
  "https://i.ytimg.com/vi/aKq8bkY5eTU/hq3.jpg",
] as const;

const plans = [
  { name: "Early access", price: "$0", detail: "Everything is free while DripCut is in early access", features: ["Video-link importing and uploads", "Standard and AI-assisted clipping", "Captions and multi-format exports", "YouTube + Instagram scheduling"] },
] as const;

const faqs = [
  ["Do I have to use AI?", "No. You can choose exact durations and generate sequential clips without AI, or use AI suggestions when you want help finding moments."],
  ["Can I paste a video link?", "Yes. Paste a public link from YouTube or another supported video website, or upload a video you have permission to use."],
  ["Can I schedule the results?", "Yes. Connect YouTube and an eligible Instagram professional account, choose the clips, and set the publishing interval."],
  ["Do I still control the final clips?", "Always. Preview the selected moments, captions, format, and schedule before publishing or downloading."],
] as const;

export function LandingPage({ signedIn }: { signedIn: boolean }) {
  return <MarketingPage page="home" signedIn={signedIn} />;
}

export function PricingPage({ signedIn }: { signedIn: boolean }) {
  return <MarketingPage page="pricing" signedIn={signedIn} />;
}

export function AboutPage({ signedIn }: { signedIn: boolean }) {
  return <MarketingPage page="about" signedIn={signedIn} />;
}

function MarketingPage({ page, signedIn }: { page: MarketingPageKind; signedIn: boolean }) {
  useMarketingMeta(page);

  return (
    <div className="landing-page">
      <MarketingNav page={page} signedIn={signedIn} />
      {page === "home" && <HomeContent signedIn={signedIn} />}
      {page === "pricing" && <PricingContent signedIn={signedIn} />}
      {page === "about" && <AboutContent signedIn={signedIn} />}
      <MarketingFooter />
    </div>
  );
}

function MarketingNav({ page, signedIn }: { page: MarketingPageKind; signedIn: boolean }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const start = () => navigatePath(signedIn ? "/home" : "/signup");
  const go = (event: React.MouseEvent<HTMLAnchorElement>, path: string) => {
    event.preventDefault();
    setMenuOpen(false);
    navigatePath(path);
  };

  return (
    <header className="landing-nav">
      <a className="landing-brand" href="/" onClick={(event) => go(event, "/")} aria-label="DripCut home">
        <span>dc</span><strong>DripCut</strong>
      </a>
      <button className="landing-menu" onClick={() => setMenuOpen((value) => !value)} aria-label="Toggle navigation" aria-expanded={menuOpen} aria-controls="landing-navigation">
        {menuOpen ? <X /> : <Menu />}
      </button>
      <nav id="landing-navigation" data-open={menuOpen}>
        <a href="/" data-current={page === "home"} onClick={(event) => go(event, "/")}>Product</a>
        <a href="/#how-it-works" onClick={(event) => page === "home" ? setMenuOpen(false) : go(event, "/#how-it-works")}>How it works</a>
        <a href="/pricing" data-current={page === "pricing"} onClick={(event) => go(event, "/pricing")}>Pricing</a>
        <a href="/about" data-current={page === "about"} onClick={(event) => go(event, "/about")}>About</a>
      </nav>
      <div className="landing-auth-actions">
        {!signedIn && <button onClick={() => navigatePath("/login")}>Log in</button>}
        <button className="landing-gradient-button" onClick={start}>{signedIn ? "Open studio" : "Try DripCut free"}<ArrowRight size={16} /></button>
      </div>
    </header>
  );
}

function HomeContent({ signedIn }: { signedIn: boolean }) {
  const [videoUrl, setVideoUrl] = useState("");
  const start = () => navigatePath(signedIn ? "/home" : "/signup");
  const submitLink = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = videoUrl.trim();
    if (trimmed) window.localStorage.setItem("dripcut.pendingVideoUrl", trimmed);
    start();
  };

  return (
    <main>
      <section className="landing-hero landing-hero--lazy">
        <div className="landing-hero__copy">
          <span className="landing-pill"><Sparkles size={14} /> Less editing. More posting.</span>
          <h1>Paste the link.<br /><span>Skip the busywork.</span></h1>
          <p>DripCut turns one long video into clipped, captioned, scheduled posts. You review the moments. The repetitive part disappears.</p>
          <form className="landing-link-cta" onSubmit={submitLink}>
            <Link2 size={20} aria-hidden="true" />
            <label className="dc-visually-hidden" htmlFor="landing-video-url">Public video link</label>
            <input id="landing-video-url" type="url" value={videoUrl} onChange={(event) => setVideoUrl(event.target.value)} placeholder="Paste any supported video link" />
            <button type="submit">Make my clips <ArrowRight size={17} /></button>
          </form>
          <div className="landing-trust"><span><Check size={13} /> Start free</span><span><Check size={13} /> AI is optional</span><span><Check size={13} /> You approve before publishing</span></div>
        </div>
        <HeroProductPreview />
      </section>

      <section className="landing-outcome-strip" aria-label="DripCut workflow summary">
        <strong>One link</strong><span>Clips found</span><i /><span>Captions added</span><i /><span>Posts queued</span><b>While you do literally anything else.</b>
      </section>

      <section className="landing-section landing-ease" id="product">
        <div className="landing-ease__heading">
          <span className="landing-section__eyebrow">Your editing shortcut</span>
          <h2>The best workflow is the one you barely notice.</h2>
          <p>Start with a link. Come back to clips that are ready for your approval—not another timeline that needs hours of attention.</p>
        </div>
        <div className="landing-ease__steps">
          <article><span><Link2 /></span><b>01</b><h3>Drop the link</h3><p>Paste a supported public video or upload your own file.</p></article>
          <article><span><WandSparkles /></span><b>02</b><h3>Let DripCut work</h3><p>Generate clean cuts, choose optional AI moments, and add captions.</p></article>
          <article><span><Check /></span><b>03</b><h3>Approve and leave</h3><p>Preview once, then download or put every approved clip on the calendar.</p></article>
        </div>
      </section>

      <RealWorkflowDemo />

      <section className="landing-section landing-anyone">
        <div className="landing-anyone__art" aria-hidden="true">
          <article><img src={MRBEAST_CLIP_THUMBNAILS[0]} alt="" /><span>9:16</span><strong>THE MOMENT<br />EVERYONE REPLAYS</strong></article>
          <article><img src={MRBEAST_CLIP_THUMBNAILS[1]} alt="" /><span>1:1</span><strong>CAPTIONED<br />AND READY</strong></article>
          <article><img src={MRBEAST_CLIP_THUMBNAILS[2]} alt="" /><span>16:9</span><strong>KEEP THE<br />FULL FRAME</strong></article>
        </div>
        <div>
          <span className="landing-section__eyebrow">No content-type boxes</span>
          <h2>If your video has a moment worth sharing, DripCut can shape it.</h2>
          <p>No “podcasters only” positioning. No narrow creator labels. Start with any video you are allowed to use and choose portrait, square, or landscape output.</p>
          <button className="landing-gradient-button" onClick={start}>Try your own video <ArrowRight size={16} /></button>
        </div>
      </section>

      <section className="landing-section landing-schedule-story">
        <div>
          <span className="landing-section__eyebrow">The last repetitive task, gone</span>
          <h2>Schedule the batch. Close the tab.</h2>
          <p>Select the approved clips, choose YouTube, Instagram, or both, then set the gap between posts. DripCut builds the queue.</p>
          <ul><li><Check /> Post to both platforms in the same slot</li><li><Check /> Space clips by minutes, hours, or days</li><li><Check /> See every scheduled post before confirming</li></ul>
        </div>
        <SchedulePreview />
      </section>

      <section className="landing-section landing-faq" id="faq">
        <SectionHeading eyebrow="Questions, answered" title="You keep control. DripCut takes the chores." body="The workflow is lightweight, but the final decision always stays with you." />
        <div>{faqs.map(([question, answer]) => <details key={question}><summary>{question}<span>+</span></summary><p>{answer}</p></details>)}</div>
      </section>

      <section className="landing-final">
        <span><Zap size={16} /> Your time is better spent elsewhere</span>
        <h2>Paste the video.<br />Take the rest of the hour back.</h2>
        <button className="landing-gradient-button" onClick={start}>{signedIn ? "Open your studio" : "Make my first clips"}<ArrowRight size={17} /></button>
      </section>
    </main>
  );
}

function HeroProductPreview() {
  return (
    <div className="hero-product-preview" aria-label="DripCut product preview showing a real video becoming short clips">
      <div className="hero-preview__bar"><i /><i /><i /><span>dripcut / new project</span><em>Auto saved</em></div>
      <div className="hero-preview__source">
        <img src={MRBEAST_THUMBNAIL} alt="Thumbnail for I Survived The 5 Deadliest Places On Earth by MrBeast" />
        <span><Play fill="currentColor" /></span>
        <small>Source video · 18:47</small>
      </div>
      <div className="hero-preview__timeline"><b /><b /><b /><b /><span>3 moments found</span></div>
      <div className="hero-preview__clips">
        <ClipImage image={MRBEAST_CLIP_THUMBNAILS[0]} label="The first danger" score="94" />
        <ClipImage image={MRBEAST_CLIP_THUMBNAILS[1]} label="One wrong step" score="91" />
        <ClipImage image={MRBEAST_CLIP_THUMBNAILS[2]} label="The escape" score="89" />
      </div>
      <div className="hero-preview__done"><Check /> Three clips ready to review <strong>2m 14s saved</strong></div>
    </div>
  );
}

function ClipImage({ image, label, score }: { image: string; label: string; score: string }) {
  return <article><img src={image} alt="" /><em>{score}</em><strong>{label}</strong><small><Captions /> Captions ready</small></article>;
}

function RealWorkflowDemo() {
  const [step, setStep] = useState(0);
  const steps = ["Paste", "Cut", "Schedule"] as const;

  return (
    <section className="landing-workflow-showcase" id="how-it-works">
      <header>
        <div><span className="landing-section__eyebrow">See the real workflow</span><h2>A long video goes in. The boring steps happen here.</h2></div>
        <div className="workflow-tabs" role="tablist" aria-label="Workflow preview steps">
          {steps.map((label, index) => <button key={label} role="tab" aria-selected={step === index} onClick={() => setStep(index)}><span>{index + 1}</span>{label}</button>)}
        </div>
      </header>
      <div className="workflow-stage">
        {step === 0 && <div className="workflow-paste">
          <div className="workflow-url"><Youtube /><span>{MRBEAST_VIDEO_URL}</span><b>Import video</b></div>
          <div className="workflow-source-card"><img src={MRBEAST_THUMBNAIL} alt="I Survived The 5 Deadliest Places On Earth video thumbnail" /><div><small>PUBLIC YOUTUBE VIDEO</small><h3>I Survived The 5 Deadliest Places On Earth</h3><p>Source found. Choose standard clips or ask for suggested moments.</p><span><Clock3 /> 18:47</span></div></div>
        </div>}
        {step === 1 && <div className="workflow-cut">
          <div className="workflow-player"><img src={MRBEAST_CLIP_THUMBNAILS[1]} alt="Video preview inside a cutting timeline" /><span><Play fill="currentColor" /></span></div>
          <div className="workflow-cut__side"><small>CLIP 2 OF 8</small><h3>One wrong step changes everything</h3><p>00:04:18 — 00:04:48</p><div className="workflow-caption">“This might be the most dangerous place we have ever filmed.”</div><button><Check /> Keep this clip</button></div>
          <div className="workflow-timeline"><span>04:00</span><i /><b /><b /><b /><em>Selected · 30 sec</em><span>05:00</span></div>
        </div>}
        {step === 2 && <SchedulePreview expanded />}
      </div>
      <p className="workflow-attribution">Illustrative product demo using the public thumbnail for <a href={MRBEAST_VIDEO_URL} target="_blank" rel="noreferrer">“I Survived The 5 Deadliest Places On Earth” by MrBeast</a>. Video rights remain with the creator. Only repurpose content you own or are permitted to use.</p>
    </section>
  );
}

function SchedulePreview({ expanded = false }: { expanded?: boolean }) {
  return <div className="schedule-preview" data-expanded={expanded}>
    <header><div><CalendarClock /><span><b>Publishing queue</b><small>Both channels · every 30 minutes</small></span></div><button>Review schedule</button></header>
    <div className="schedule-preview__days"><span>MON<small>21</small></span><span data-active="true">TUE<small>22</small></span><span>WED<small>23</small></span><span>THU<small>24</small></span><span>FRI<small>25</small></span></div>
    <div className="schedule-preview__queue">
      <article><time>10:00</time><img src={MRBEAST_CLIP_THUMBNAILS[0]} alt="" /><span><b>The first danger</b><small><Youtube /> YouTube <Instagram /> Instagram</small></span><em>Ready</em></article>
      <article><time>10:30</time><img src={MRBEAST_CLIP_THUMBNAILS[1]} alt="" /><span><b>One wrong step</b><small><Youtube /> YouTube <Instagram /> Instagram</small></span><em>Ready</em></article>
      <article><time>11:00</time><img src={MRBEAST_CLIP_THUMBNAILS[2]} alt="" /><span><b>The escape</b><small><Youtube /> YouTube <Instagram /> Instagram</small></span><em>Ready</em></article>
    </div>
  </div>;
}

function PricingContent({ signedIn }: { signedIn: boolean }) {
  const start = () => navigatePath(signedIn ? "/home" : "/signup");
  return <main className="marketing-inner-page">
    <section className="marketing-page-hero"><span className="landing-pill"><Sparkles size={14} /> Free during early access</span><h1>Create and schedule clips.<br /><span>Pay nothing for now.</span></h1><p>Use the complete DripCut workflow while we finish the launch experience. No card, no paid plan, no surprise checkout.</p></section>
    <section className="landing-price-grid landing-price-grid--free">{plans.map((plan) => <article key={plan.name} data-featured="true">
      <span>Free for now</span><h2>{plan.name}</h2><strong>{plan.price}<small>/month</small></strong><p>{plan.detail}</p>
      <ul>{plan.features.map((feature) => <li key={feature}><Check size={15} />{feature}</li>)}</ul>
      <button className="landing-gradient-button" onClick={start}>{signedIn ? "Open your studio" : "Start free"}</button>
    </article>)}</section>
    <section className="pricing-explainer"><div><span>No card</span><strong>Create an account and start immediately</strong></div><div><span>All core tools</span><strong>Clip, caption, download, and schedule</strong></div><div><span>Before pricing changes</span><strong>We will show the plan clearly in advance</strong></div></section>
    <section className="landing-final landing-final--inner"><span><Zap size={16} /> Start small</span><h2>Try the workflow before choosing a plan.</h2><button className="landing-gradient-button" onClick={start}>Start free <ArrowRight size={17} /></button></section>
  </main>;
}

function AboutContent({ signedIn }: { signedIn: boolean }) {
  const start = () => navigatePath(signedIn ? "/home" : "/signup");
  return <main className="marketing-inner-page">
    <section className="marketing-page-hero marketing-page-hero--about"><span className="landing-pill"><Scissors size={14} /> About DripCut</span><h1>Video work should feel<br /><span>lighter than this.</span></h1><p>DripCut exists to remove the repetitive steps between a finished long video and the short posts waiting inside it.</p></section>
    <section className="about-manifesto"><div><span>Our point of view</span><h2>Your creativity is the source.<br />Software should handle the chores.</h2></div><p>Finding timestamps, repeating crops, rebuilding captions, naming exports, and setting twenty publishing times are necessary tasks—not the reason anyone starts making videos. DripCut keeps the creative decision with you and automates as much of the repetition as possible.</p></section>
    <section className="about-values"><article><Link2 /><h3>Start from what already exists</h3><p>Bring a link or upload. No complicated project setup before you can see a result.</p></article><article><Check /><h3>Keep the human approval</h3><p>Automation should propose and prepare. You decide what is worth publishing.</p></article><article><Zap /><h3>Finish the whole loop</h3><p>A useful clip is not finished until it can be downloaded or placed on the publishing calendar.</p></article></section>
    <section className="landing-final landing-final--inner"><span><Sparkles size={16} /> Less busywork starts here</span><h2>Bring the video. Keep your afternoon.</h2><button className="landing-gradient-button" onClick={start}>Try DripCut free <ArrowRight size={17} /></button></section>
  </main>;
}

function MarketingFooter() {
  const go = (event: React.MouseEvent<HTMLAnchorElement>, path: string) => { event.preventDefault(); navigatePath(path); };
  return <footer className="landing-footer"><a className="landing-brand" href="/" onClick={(event) => go(event, "/")}><span>dc</span><strong>DripCut</strong></a><p>Paste the link. Skip the busywork.</p><nav><a href="/" onClick={(event) => go(event, "/")}>Product</a><a href="/pricing" onClick={(event) => go(event, "/pricing")}>Pricing</a><a href="/about" onClick={(event) => go(event, "/about")}>About</a></nav><small>© {new Date().getFullYear()} DripCut</small></footer>;
}

function SectionHeading({ eyebrow, title, body }: { eyebrow: string; title: string; body: string }) {
  return <header className="landing-section-heading"><span className="landing-section__eyebrow">{eyebrow}</span><h2>{title}</h2><p>{body}</p></header>;
}

function useMarketingMeta(page: MarketingPageKind) {
  useEffect(() => {
    const metadata = {
      home: {
        title: "DripCut — Paste a Video Link. Get Clips Ready to Post.",
        description: "Turn a long video into clipped, captioned, scheduled posts with less repetitive editing.",
        path: "/",
      },
      pricing: {
        title: "DripCut Pricing — Clip and Schedule Videos",
        description: "Compare DripCut credit plans for clipping, captions, and multi-platform scheduling.",
        path: "/pricing",
      },
      about: {
        title: "About DripCut — Less Video Busywork",
        description: "Learn why DripCut is building a faster path from long videos to scheduled short-form content.",
        path: "/about",
      },
    }[page];
    const canonicalUrl = `https://dripcut.onrender.com${metadata.path}`;
    document.title = metadata.title;
    document.querySelector<HTMLMetaElement>('meta[name="description"]')?.setAttribute("content", metadata.description);
    document.querySelector<HTMLLinkElement>('link[rel="canonical"]')?.setAttribute("href", canonicalUrl);
    document.querySelector<HTMLMetaElement>('meta[property="og:url"]')?.setAttribute("content", canonicalUrl);
    document.querySelector<HTMLMetaElement>('meta[property="og:title"]')?.setAttribute("content", metadata.title);
    document.querySelector<HTMLMetaElement>('meta[property="og:description"]')?.setAttribute("content", metadata.description);
    document.querySelector<HTMLMetaElement>('meta[name="twitter:title"]')?.setAttribute("content", metadata.title);
    document.querySelector<HTMLMetaElement>('meta[name="twitter:description"]')?.setAttribute("content", metadata.description);
  }, [page]);
}
