import { createContext, useContext } from "react";

import { requestJson } from "../product/api/client";

export interface SessionUser {
  id: string;
  email: string;
  name: string;
  workspace_id?: string;
  role?: string;
  is_dripcut_admin?: boolean;
}

export interface SessionPayload {
  authenticated: boolean;
  provider: string;
  user?: SessionUser;
  requires_email_confirmation?: boolean;
  message?: string;
}

export interface AuthContextValue {
  loading: boolean;
  session: SessionPayload | null;
  login: (email: string, password: string) => Promise<SessionPayload>;
  signup: (name: string, email: string, password: string) => Promise<SessionPayload>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}

export async function googleAuthorize(): Promise<void> {
  const payload = await requestJson<{ authorize_url: string }>("/api/auth/google");
  window.location.assign(payload.authorize_url);
}

export async function exchangeOAuthTokens(accessToken: string, refreshToken: string): Promise<void> {
  await requestJson<SessionPayload>("/api/auth/oauth/exchange", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ access_token: accessToken, refresh_token: refreshToken }),
  });
}

export function navigatePath(path: string, replace = false) {
  window.history[replace ? "replaceState" : "pushState"]({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}
