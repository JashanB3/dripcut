import { Check, Clock3, LayoutTemplate } from "lucide-react";
import { useState } from "react";

import type { ProductRoute } from "../models";
import { clipTemplates, type TemplateCategory } from "../templates/catalog";

const categories = ["All", "Podcast", "Talking Head", "Education", "Business", "Gaming", "Motivation", "Story", "Product", "News", "Minimal"] as const;

export function TemplatesPage({ onNavigate }: { onNavigate: (route: ProductRoute) => void }) {
  const [category, setCategory] = useState<(typeof categories)[number]>("All");
  const [selected, setSelected] = useState<string | null>(null);
  const visible = category === "All" ? clipTemplates : clipTemplates.filter((template) => template.category === category as TemplateCategory);

  const applyTemplate = (id: string) => {
    setSelected(id);
    window.localStorage.setItem("dripcut.selectedTemplate", id);
    window.setTimeout(() => onNavigate("auto-clip"), 180);
  };

  return (
    <div className="templates-page product-page narrow-page">
      <header className="page-intro">
        <span className="eyebrow">Original preset library</span>
        <h1>Short-form templates, without the copy-paste look.</h1>
        <p>Choose a format, caption rhythm, safe-zone plan, and transition style. Then add your source.</p>
      </header>
      <div className="template-categories">
        {categories.map((item) => <button key={item} data-selected={item === category} onClick={() => setCategory(item)}>{item}</button>)}
      </div>
      <div className="template-grid">
        {visible.map((template) => (
          <article className="template-card" key={template.id}>
            <div className={`template-card__preview template-card__preview--${template.accent}`}>
              <span className="template-shape template-shape--one" />
              <span className="template-shape template-shape--two" />
              <strong>{template.headline[0]}<br />{template.headline[1]}</strong>
              <LayoutTemplate size={20} />
            </div>
            <div className="template-card__detail">
              <strong>{template.name}</strong>
              <span>{template.category}<small><Clock3 size={12} /> {template.duration} sec</small></span>
              <p>{template.tagline}</p>
              <button data-selected={selected === template.id} onClick={() => applyTemplate(template.id)}>{selected === template.id ? <Check size={14} /> : <LayoutTemplate size={14} />} {selected === template.id ? "Applied" : "Use template"}</button>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}
