import { useEffect, useState } from "react";

export function useVideoThumbnails(url: string | null, duration: number, count = 12) {
  const [thumbnails, setThumbnails] = useState<string[]>([]);

  useEffect(() => {
    if (!url || duration <= 0) {
      setThumbnails([]);
      return;
    }

    let cancelled = false;
    const video = document.createElement("video");
    video.muted = true;
    video.preload = "auto";
    video.src = url;

    const capture = async () => {
      await new Promise<void>((resolve, reject) => {
        video.addEventListener("loadedmetadata", () => resolve(), { once: true });
        video.addEventListener("error", () => reject(new Error("Unable to read video")), { once: true });
      });
      const canvas = document.createElement("canvas");
      canvas.width = 160;
      canvas.height = 90;
      const context = canvas.getContext("2d");
      if (!context) return;
      const frames: string[] = [];

      for (let index = 0; index < count; index += 1) {
        video.currentTime = Math.max(0, Math.min(duration - 0.05, (duration / count) * index));
        await new Promise<void>((resolve) => {
          video.addEventListener("seeked", () => resolve(), { once: true });
        });
        if (cancelled) return;
        context.drawImage(video, 0, 0, canvas.width, canvas.height);
        frames.push(canvas.toDataURL("image/jpeg", 0.64));
      }
      if (!cancelled) setThumbnails(frames);
    };

    void capture().catch(() => {
      if (!cancelled) setThumbnails([]);
    });
    return () => {
      cancelled = true;
      video.removeAttribute("src");
      video.load();
    };
  }, [count, duration, url]);

  return thumbnails;
}
