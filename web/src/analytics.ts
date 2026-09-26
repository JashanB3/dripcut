declare global {
  interface Window {
    dataLayer: unknown[];
  }
}
const GA_ID_PATTERN = /^G-[A-Z0-9]+$/;
const GTM_ID_PATTERN = /^GTM-[A-Z0-9]+$/;

function appendScript(src: string, id: string): void {
  if (document.getElementById(id)) return;
  const script = document.createElement("script");
  script.id = id;
  script.async = true;
  script.src = src;
  document.head.append(script);
}

export function initializeAnalytics(): void {
  const measurementId = import.meta.env.VITE_GA_MEASUREMENT_ID?.trim().toUpperCase();
  const containerId = import.meta.env.VITE_GTM_CONTAINER_ID?.trim().toUpperCase();

  if (!GA_ID_PATTERN.test(measurementId ?? "") && !GTM_ID_PATTERN.test(containerId ?? "")) return;

  window.dataLayer = window.dataLayer || [];
  const dataLayerPush = (...args: unknown[]) => window.dataLayer.push(args);

  if (GTM_ID_PATTERN.test(containerId ?? "")) {
    window.dataLayer.push({ "gtm.start": Date.now(), event: "gtm.js" });
    appendScript(`https://www.googletagmanager.com/gtm.js?id=${encodeURIComponent(containerId!)}`, "dripcut-gtm");

    const fallback = document.createElement("noscript");
    fallback.id = "dripcut-gtm-noscript";
    const iframe = document.createElement("iframe");
    iframe.src = `https://www.googletagmanager.com/ns.html?id=${encodeURIComponent(containerId!)}`;
    iframe.height = "0";
    iframe.width = "0";
    iframe.style.display = "none";
    iframe.style.visibility = "hidden";
    iframe.title = "Google Tag Manager";
    fallback.append(iframe);
    document.body.prepend(fallback);
  }

  if (GA_ID_PATTERN.test(measurementId ?? "")) {
    appendScript(`https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(measurementId!)}`, "dripcut-ga");
    dataLayerPush("js", new Date());
    dataLayerPush("config", measurementId!, { anonymize_ip: true });
  }
}
