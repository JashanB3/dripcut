import { AlertCircle, RefreshCw } from "lucide-react";

import { ApiError } from "../api/client";

export function CustomerError({
  error,
  fallback = "This action could not be completed.",
  onRetry,
}: {
  error: unknown;
  fallback?: string;
  onRetry?: () => void;
}) {
  const failure = normalizeCustomerError(error, fallback);
  return (
    <div className="source-error-banner customer-error" role="alert">
      <AlertCircle size={18} aria-hidden="true" />
      <span><strong>{failure.message}</strong>{failure.hint && <small>{failure.hint}</small>}</span>
      {onRetry && <button type="button" onClick={onRetry}><RefreshCw size={14} /> Try again</button>}
    </div>
  );
}

function normalizeCustomerError(error: unknown, fallback: string) {
  if (error instanceof ApiError) {
    return { message: error.message || fallback, hint: error.hint, retryable: error.retryable };
  }
  if (error instanceof Error) return { message: error.message || fallback, hint: undefined, retryable: false };
  if (typeof error === "string" && error.trim()) return { message: error.trim(), hint: undefined, retryable: false };
  return { message: fallback, hint: undefined, retryable: false };
}
