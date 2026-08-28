import { useCallback, useEffect, useState, type ReactNode } from "react";

import { requestJson } from "../product/api/client";
import { AuthContext, type SessionPayload } from "./authState";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [session, setSession] = useState<SessionPayload | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await requestJson<SessionPayload>("/api/auth/session", { cache: "no-store" });
      setSession(next.authenticated ? next : null);
    } catch {
      setSession(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const login = useCallback(async (email: string, password: string) => {
    const next = await requestJson<SessionPayload>("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    setSession(next.authenticated ? next : null);
    return next;
  }, []);

  const signup = useCallback(async (name: string, email: string, password: string) => {
    const next = await requestJson<SessionPayload>("/api/auth/signup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, email, password }),
    });
    setSession(next.authenticated ? next : null);
    return next;
  }, []);

  const logout = useCallback(async () => {
    await requestJson<null>("/api/auth/logout", { method: "POST" });
    setSession(null);
  }, []);

  return (
    <AuthContext.Provider value={{ loading, session, login, signup, logout, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}
