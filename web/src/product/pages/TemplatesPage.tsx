import { Clock3, LayoutTemplate, LockKeyhole } from "lucide-react";

import { templatePreviews } from "../mock/data";

const categories = ["Trending", "Reels", "Shorts", "Business", "Podcast", "Motivation", "Memes", "Product", "Fashion", "Gaming", "Education"];

export function TemplatesPage() {
  return (
    <div className="templates-page product-page narrow-page">
      <header className="page-intro">
        <span className="eyebrow">Preview library</span>
        <h1>Short-form templates, without the copy-paste look.</h1>
        <p>Original DripCut template architecture is ready. Applying templates is deferred until the render API supports them.</p>
      </header>
      <div className="template-categories">
        {categories.map((category, index) => <button key={category} data-selected={index === 0}>{category}</button>)}
      </div>
      <div className="template-grid">
        {templatePreviews.map(([name, category, duration, accent], index) => (
          <article className="template-card" key={name}>
            <div className={`template-card__preview template-card__preview--${accent}`}>
              <span className="template-shape template-shape--one" />
              <span className="template-shape template-shape--two" />
              <strong>{index % 2 ? "MAKE IT" : "KEEP IT"}<br />{index % 2 ? "COUNT" : "MOVING"}</strong>
              <LayoutTemplate size={20} />
            </div>
            <div className="template-card__detail">
              <strong>{name}</strong>
              <span>{category}<small><Clock3 size={12} /> {duration}</small></span>
              <button disabled title="Template rendering is not connected"><LockKeyhole size={14} /> Use template</button>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}
