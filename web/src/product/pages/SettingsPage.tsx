import { CheckCircle2, Instagram, ServerCog, Youtube } from "lucide-react";
import { useEffect, useState } from "react";

import { beginSocialOAuth, disconnectSocial, fetchSocialConnections } from "../api/client";
import { CustomerError } from "../components/CustomerError";
import type { SocialConnection } from "../models";
import "./social.css";

export function SettingsPage() {
  const [connections, setConnections] = useState<SocialConnection[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const params = new URLSearchParams(window.location.search);
  const socialResult = params.get("social");
  const socialError = params.get("social_error");

  const refresh = async () => {
    const connections = await fetchSocialConnections();
    setConnections(connections);
  };

  useEffect(() => { void refresh().catch(setError); }, []);

  const changeConnection = async (platform: "youtube" | "instagram") => {
    const connection = connections.find((item) => item.platform === platform);
    if (!connection) return;
    setBusy(true);
    setError(null);
    try {
      if (connection.connected) {
        await disconnectSocial(platform);
        await refresh();
        setBusy(false);
      } else {
        window.location.assign(await beginSocialOAuth(platform));
      }
    } catch (reason) {
      setError(reason);
      setBusy(false);
    }
  };

  return <div className="settings-page product-page narrow-page">
    <header className="page-heading-row"><div><span className="eyebrow">Publishing accounts</span><h1>Your studio, ready to publish.</h1><p>Connect YouTube and Instagram once, then schedule the same finished clips to either platform or both.</p></div></header>
    {error !== null && <CustomerError error={error} fallback="The social connection could not be updated." />}
    {socialResult === "youtube-connected" && <div className="social-notice"><CheckCircle2 size={16} /> YouTube connected successfully.</div>}
    {socialResult === "youtube-denied" && <div className="social-notice">YouTube connection was cancelled. Nothing changed.</div>}
    {(socialResult === "youtube-failed" || socialError === "youtube") && <CustomerError error={null} fallback="YouTube could not be connected. Check that this Google account owns a YouTube channel, then try again." />}
    {socialResult === "instagram-connected" && <div className="social-notice"><CheckCircle2 size={16} /> Instagram connected successfully.</div>}
    {socialResult === "instagram-denied" && <div className="social-notice">Instagram connection was cancelled. Nothing changed.</div>}
    {(socialResult === "instagram-failed" || socialError === "instagram") && <CustomerError error={null} fallback="Instagram could not be connected. Sign in with an Instagram Creator or Business account and allow publishing access, then try again." />}
    <section className="connection-cards">
      {!connections.length && !error && <div className="social-loading" role="status">Loading publishing accounts…</div>}
      {connections.map((connection) => <article className="social-connection-card" key={connection.platform} data-connected={connection.connected}>
        {connection.avatarUrl ? <img className="social-avatar" src={connection.avatarUrl} alt="" /> : connection.platform === "youtube" ? <Youtube size={22} /> : <Instagram size={22} />}
         <div><strong>{connection.platform === "youtube" ? "YouTube Shorts" : "Instagram Reels"}</strong><span>{connection.connected ? connection.detail : connection.platform === "youtube" ? "Connect a channel to schedule and publish finished clips." : "Connect an eligible Instagram professional account to publish Reels."}</span>{connection.channelId && <small>Account ID: {connection.channelId}</small>}<small>{connection.connected ? "Ready to publish. Credentials are encrypted and persist across restarts." : connection.configured ? "OAuth is ready. You will choose the account in the provider window." : connection.setupHint}</small></div>
         <button aria-label={`${connection.connected ? "Disconnect" : "Connect"} ${connection.label}`} disabled={(!connection.configured && !connection.connected) || busy} onClick={() => void changeConnection(connection.platform)}>{busy ? "Working…" : connection.connected ? "Disconnect" : connection.configured ? `Connect ${connection.platform === "youtube" ? "YouTube" : "Instagram"}` : "Admin setup required"}</button>
      </article>)}
    </section>
    <p className="settings-social-help"><Instagram size={16} /> Sign in directly with your Instagram Creator or Business account. No Facebook Page is required. After connecting it here, select Instagram Reels in Schedule and it will publish in the same time slot as YouTube when both are selected.</p>
    <section className="settings-cards">
      <article><ServerCog size={22} /><div><strong>Video processing</strong><span>Standard clipping works without AI</span><small>Upload a video or paste a supported YouTube link to begin.</small></div></article>
      <article><CheckCircle2 size={22} /><div><strong>Private project persistence</strong><span>Your projects belong to your workspace</span><small>Open Projects to continue working or download completed clips.</small></div></article>
    </section>
  </div>;
}
