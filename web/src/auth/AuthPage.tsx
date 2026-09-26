import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowRight, Check, Eye, EyeOff, Link2, Scissors, Sparkles } from "lucide-react";

import { ApiError, requestJson } from "../product/api/client";
import { CustomerError } from "../product/components/CustomerError";
import { exchangeOAuthTokens, googleAuthorize, navigatePath, useAuth } from "./authState";

type AuthPageKind = "login" | "signup" | "forgot-password" | "reset-password" | "callback" | "logout";

const copy = {
  login: ["Welcome back", "Log in to pick up your latest clips and ZIPs."],
  signup: ["Create your account", "Start clipping in under a minute."],
  "forgot-password": ["Reset your password", "We will send a secure recovery link."],
  "reset-password": ["Choose a new password", "Use at least eight characters."],
  callback: ["Confirming your account", "Finishing your secure DripCut sign-in."],
  logout: ["Signing you out", "Closing this DripCut session."],
} satisfies Record<AuthPageKind, [string, string]>;

export function AuthPage({ kind }: { kind: AuthPageKind }) {
  const auth = useAuth();
  const { logout, refresh } = auth;
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState<unknown>(null);
  const callbackStarted = useRef(false);

  useEffect(() => {
    if (kind === "logout") {
      void logout().finally(() => navigatePath("/login", true));
    }
    if (kind === "callback") {
      if (callbackStarted.current) return;
      callbackStarted.current = true;
      const values = new URLSearchParams(window.location.hash.replace(/^#/, "") || window.location.search);
      window.history.replaceState(null, "", window.location.pathname);
      if (values.has("error")) {
        setError(values.get("error_code") === "otp_expired"
          ? "This confirmation link has expired or was already used. Try logging in if you already confirmed your email. Otherwise, sign up again to request a fresh link."
          : "We could not confirm this sign-in. Please return to login and try again.");
        return;
      }
      const accessToken = values.get("access_token");
      const refreshToken = values.get("refresh_token");
      if (!accessToken || !refreshToken) {
        setError("This sign-in link is incomplete. Please return to login and try again.");
        return;
      }
      void exchangeOAuthTokens(accessToken, refreshToken)
        .then(refresh)
        .then(() => navigatePath("/home", true))
        .catch(setError);
    }
  }, [kind, logout, refresh]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setMessage("");
    try {
      if (kind === "login") {
        await auth.login(email, password);
        navigatePath("/home", true);
      } else if (kind === "signup") {
        const result = await auth.signup(name, email, password);
        if (result.requires_email_confirmation) setMessage(result.message ?? "Check your email to continue.");
        else navigatePath("/home", true);
      } else if (kind === "forgot-password") {
        const result = await requestJson<{ message: string }>("/api/auth/forgot-password", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email }),
        });
        setMessage(result.message);
      } else if (kind === "reset-password") {
        const values = new URLSearchParams(window.location.hash.replace(/^#/, ""));
        await requestJson("/api/auth/reset-password", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            password,
            access_token: values.get("access_token"),
            refresh_token: values.get("refresh_token"),
          }),
        });
        await auth.refresh();
        setMessage("Password updated. You can continue to DripCut.");
      }
    } catch (reason) {
      const failure = reason as ApiError;
      setError(failure);
    } finally {
      setBusy(false);
    }
  };

  const [title, subtitle] = copy[kind];
  const isPassive = kind === "callback" || kind === "logout";
  return (
    <div className="auth-screen">
      <header className="auth-header">
        <button className="auth-brand" onClick={() => navigatePath("/")}><span>dc</span><strong>DripCut</strong></button>
        <nav><button onClick={() => navigatePath("/login")}>Log in</button><button className="auth-signup" onClick={() => navigatePath("/signup")}>Sign up free</button></nav>
      </header>
      <section className="auth-story">
        <span className="auth-kicker"><Sparkles size={14} /> Less editing. More posting.</span>
        <h1>Paste the link.<br /><em>Skip the busywork.</em></h1>
        <p>Turn a long video into polished clips, review the moments, then schedule the whole batch to YouTube and Instagram.</p>
        <div className="auth-workflow" aria-label="DripCut workflow preview">
          <article><span><Link2 size={18} /></span><div><small>01 · SOURCE</small><strong>Paste any supported video link</strong></div><Check size={18} /></article>
          <article><span><Scissors size={18} /></span><div><small>02 · CLIPS</small><strong>Pick exact cuts or viral moments</strong></div><Check size={18} /></article>
          <article><span><ArrowRight size={18} /></span><div><small>03 · PUBLISH</small><strong>Queue YouTube and Instagram</strong></div></article>
        </div>
        <div className="auth-proof"><span><Check size={14} /> Start free</span><span><Check size={14} /> AI is optional</span><span><Check size={14} /> You stay in control</span></div>
      </section>
      <section className="auth-card" aria-live="polite">
        <span className="auth-card__eyebrow">{kind === "signup" ? "Your studio is one step away" : "Your clips are waiting"}</span>
        <h2>{title}</h2><p>{subtitle}</p>
        {isPassive ? (error === null ? <div className="auth-loader" /> : null) : (
          <form onSubmit={submit}>
            {(kind === "login" || kind === "signup") && <button type="button" className="oauth-button" onClick={() => void googleAuthorize().catch(setError)}>Continue with Google</button>}
            {(kind === "login" || kind === "signup") && <div className="auth-divider"><span>or use your email</span></div>}
            {kind === "signup" && <label>Name<input value={name} onChange={(event) => setName(event.target.value)} required autoComplete="name" placeholder="Your creator name" /></label>}
            {kind !== "reset-password" && <label>Email<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required autoComplete="email" placeholder="you@example.com" /></label>}
            {kind !== "forgot-password" && <div className="auth-field"><label htmlFor="auth-password">Password</label><span className="auth-password"><input id="auth-password" type={showPassword ? "text" : "password"} value={password} onChange={(event) => setPassword(event.target.value)} required minLength={8} autoComplete={kind === "login" ? "current-password" : "new-password"} placeholder="At least 8 characters" /><button type="button" onClick={() => setShowPassword((value) => !value)} aria-label={showPassword ? "Hide entered value" : "Show entered value"}>{showPassword ? <EyeOff size={17} /> : <Eye size={17} />}</button></span></div>}
            {kind === "login" && <button type="button" className="auth-link" onClick={() => navigatePath("/forgot-password")}>Forgot password?</button>}
            <button className="auth-submit" disabled={busy}>{busy ? "Please wait..." : kind === "login" ? "Log in" : kind === "signup" ? "Create free account" : kind === "forgot-password" ? "Send reset link" : "Update password"}{!busy && (kind === "login" || kind === "signup") && <ArrowRight size={17} />}</button>
            {kind === "signup" && <small className="auth-terms">By continuing, you agree to use only videos you own or have permission to repurpose.</small>}
          </form>
        )}
        {message && <div className="auth-message auth-message--success">{message}</div>}
        {error !== null && <CustomerError error={error} fallback="Unable to continue." />}
        {kind === "callback" && error !== null && <>
          <button className="auth-submit" onClick={() => navigatePath("/login", true)}>Return to login</button>
          <button className="auth-switch" onClick={() => navigatePath("/signup", true)}>Request a new confirmation link</button>
        </>}
        {!isPassive && <button className="auth-switch" onClick={() => navigatePath(kind === "login" ? "/signup" : "/login")}>{kind === "login" ? "New to DripCut? Create an account" : "Already have an account? Log in"}</button>}
      </section>
    </div>
  );
}
