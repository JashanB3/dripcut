import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from "react";
import { Search } from "lucide-react";

type ButtonVariant = "primary" | "secondary" | "ghost";

export function Button({
  variant = "secondary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return <button className={`dc-button dc-button--${variant} ${className}`} {...props} />;
}

export function IconButton({
  label,
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button className={`dc-icon-button ${className}`} aria-label={label} title={label} {...props} />
  );
}

export function SearchField(props: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="dc-search-field">
      <Search size={16} aria-hidden="true" />
      <input type="search" {...props} />
    </label>
  );
}

export function EmptyState({ icon, title, body, action }: {
  icon: ReactNode;
  title: string;
  body: string;
  action?: ReactNode;
}) {
  return (
    <div className="dc-empty-state">
      <span className="dc-empty-state__icon">{icon}</span>
      <strong>{title}</strong>
      <p>{body}</p>
      {action}
    </div>
  );
}
