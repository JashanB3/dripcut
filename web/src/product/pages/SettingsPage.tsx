import { CheckCircle2, ServerCog, Youtube } from "lucide-react";
import { useEffect, useState } from "react";

import { beginSocialOAuth, disconnectSocial, fetchSocialConnections } from "../api/client";
import { CustomerError } from "../components/CustomerError";
import type { SocialConnection } from "../models";

export function SettingsPage() {
  const [youtube, setYoutube] = useState<SocialConnection | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const socialResult = new URLSearchParams(window.location.search).get("social");

  const refresh = async () => {
    const connections = await fetchSocialConnections();
    setYoutube(connections.find((item) => item.platform === "youtube") ?? null);
  };

  useEffect(() => { void refresh().catch(setError); }, []);

  const changeConnection = async () => {
    if (!youtube) return;
    setBusy(true);
    setError(null);
    try {
      if (youtube.connected) {
        await disconnectSocial("youtube");
        await refresh();
      } else {
        window.location.assign(await beginSocialOAuth("youtube"));
      }
    } catch (reason) {
      setError(reason);
      setBusy(false);
    }
  };

  return <div className="settings-page product-page narrow-page">
    <header className="page-heading-row"><div><span className="eyebrow">Settings</span><h1>Your studio, ready to publish.</h1><p>Manage the YouTube channel DripCut uses for uploads and scheduling.</p></div></header>
    {error !== null && <CustomerError error={error} fallback="YouTube connection could not be updated." />}
    {socialResult === "youtube-connected" && <div className="social-notice"><CheckCircle2 size={16} /> YouTube connected successfully.</div>}
    {socialResult === "youtube-denied" && <div className="social-notice">YouTube connection was cancelled. Nothing changed.</div>}
    {socialResult === "youtube-failed" && <CustomerError error={null} fallback="YouTube could not be connected. Check that this Google account owns a YouTube channel, then try again." />}
    <section className="connection-cards">
      {youtube && <article data-connected={youtube.connected}>
        {youtube.avatarUrl ? <img className="social-avatar" src={youtube.avatarUrl} alt="" /> : <Youtube size={22} />}
        <div><strong>YouTube</strong><span>{youtube.connected ? youtube.detail : "Connect your channel to schedule and publish finished clips."}</span>{youtube.channelId && <small>Channel ID: {youtube.channelId}</small>}<small>{youtube.connected ? "Connected credentials are encrypted and persist across restarts." : youtube.configured ? "Official Google OAuth is configured." : youtube.setupHint}</small></div>
        <button disabled={!youtube.configured || busy} onClick={() => void changeConnection()}>{busy ? "Working…" : youtube.connected ? "Disconnect" : youtube.configured ? "Connect YouTube" : "Admin setup required"}</button>
      </article>}
    </section>
    <section className="settings-cards">
      <article><ServerCog size={22} /><div><strong>Video processing</strong><span>Standard clipping works without AI</span><small>Upload a video or paste a supported YouTube link to begin.</small></div></article>
      <article><CheckCircle2 size={22} /><div><strong>Private project persistence</strong><span>Your projects belong to your workspace</span><small>Open Projects to continue working or download completed clips.</small></div></article>
    </section>
  </div>;
}
