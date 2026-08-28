import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

export default function globalSetup() {
  const directory = resolve(".e2e");
  const target = resolve(directory, "sample.mp4");
  mkdirSync(directory, { recursive: true });
  execFileSync("ffmpeg", [
    "-hide_banner", "-loglevel", "error", "-y",
    "-f", "lavfi", "-i", "testsrc=size=160x120:rate=8:duration=18",
    "-f", "lavfi", "-i", "sine=frequency=440:duration=18",
    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
    "-c:a", "aac", "-shortest", target,
  ]);
}
