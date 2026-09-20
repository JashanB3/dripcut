# DripCut production performance baseline

Measured on 20 September 2026 before the performance recovery changes.

## Environment

- Frontend: `https://dripcut.onrender.com`
- Processing VM: GCE `e2-highcpu-4`, `asia-south1-a`
- Container limit: 3.5 vCPU, 3 GiB RAM
- Encoder: CPU `libx264`, `ultrafast`, four FFmpeg threads
- Output: portrait 720×1280, 30 fps, captions off
- Source: Blender Foundation Big Buck Bunny, 635 seconds
- Production commit: `4f8bcc6` plus the unpushed infrastructure commit `5f31bac`

## End-to-end baseline

| Stage | Result | Target | Status |
|---|---:|---:|---|
| Landing to login screen | visually responsive | <2 s | pass |
| Google consent to authenticated home | ~5.4 s | <2 s feedback | needs improvement |
| Auto Clip route visible | ~3.7 s | <2 s | fail |
| YouTube import accepted | 3.2 s | <2 s | fail |
| YouTube source ready | 75.0 s backend / ~84.3 s UI | <30 s | fail |
| Render accepted | 3.17 s | <2 s | fail |
| First clip registered | ~17 s backend / ~32.8 s UI | <30 s | UI fail |
| All 22 clips ready | 449.4 s | progressive | fail |
| Job-status response while encoding | 0.86–3.69 s | <1 s | fail |

The backend first artifact met the 30-second objective, but slow API polling made the
visible result miss it. Creating all possible clips by default also turned an ordinary
test into a 7.5-minute batch without the user explicitly asking for 22 clips.

## YouTube import breakdown

Job: `b6c848ae-0a70-4bfc-a392-efb61cbe85b4`

| Measurement | Value |
|---|---:|
| Queue-to-finish | 75.0 s |
| Pipeline total | 74.252 s |
| Metadata | 22.749 s |
| Download attempts | 5 |
| Successful strategy | `authenticated_cookie` |
| Selected format | `299+258` |
| Download stage | 42.661 s |
| Registration/R2 remainder | ~8.7 s |
| Downloaded source | 288,739,510 bytes |

Failed strategies were tried in this order before the known-working cookie path:
`mweb_pot`, `web_embedded`, `web_safari_hls`, and `recommended`. The selected video
stream was substantially larger and higher-frame-rate than the 720p/30-fps export
profile required.

## Clip render breakdown

Job: `bb751dd0-437d-4288-9e08-14900a4e6179`

| Measurement | Value |
|---|---:|
| Clips | 22 (21×30 s, 1×4.6 s) |
| Queue wait | 0.59 s |
| Pipeline total | 448.475 s |
| Render/upload loop | 448.203 s |
| R2 clip uploads | 46.404 s |
| Approximate encode time | 401.8 s |
| Peak process RSS | 208.6 MiB |
| VM RAM during render | ~925 MiB used / 3.9 GiB total |
| API container CPU | ~250–305% |
| FFmpeg CPU | ~284–291% |
| Disk | 40% used, 18 GiB free |

Representative command:

```text
ffmpeg -ss 58.000 -i <1080p60-source.mp4> -ss 2.000 -t 30.000 \
  -vf scale=720:1280:force_original_aspect_ratio=increase:flags=lanczos,crop=720:1280 \
  -c:v libx264 -crf 21 -preset ultrafast -threads 4 -pix_fmt yuv420p -r 30 \
  -c:a aac -b:a 192k -movflags +faststart clip-03.mp4
```

Memory and disk were healthy. CPU work, oversized acquisition, synchronous R2 job-state
checkpoints, and the 22-clip UI regression were the limiting factors.

## Corrective benchmark contract

Run the repeatable isolated smoke test with:

```bash
.venv/bin/python scripts/performance_smoke.py /path/to/source.mp4 \
  --durations 15 30 45 60 --count 1
```

The script uses local temporary storage, captions off, portrait 720p, 30 fps, and
`ultrafast`; it reports source registration, first artifact, total wall time, CPU,
RSS, and pipeline timings without touching the normal workspace.
