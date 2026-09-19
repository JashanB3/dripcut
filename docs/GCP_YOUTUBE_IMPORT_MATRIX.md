# GCP YouTube import reliability matrix

Test date: 2026-09-19. Only public, non-authenticated samples were used. No
private, geo-restricted or login-required access controls were bypassed.

## Baselines before GCE

| Environment | URL form/content | Result | Strategy/failure | Time | Bytes | Peak process RSS | Format |
|---|---|---|---|---:|---:|---:|---|
| Local macOS | `youtube.com/watch`, public short (`jNQXAC9IVRw`) | PASS | `web_embedded` | 7.11 s | 633,632 | 346.7 MiB | verified media |
| Local macOS | `youtu.be`, same public short | PASS | `web_embedded` | 7.11 s | 633,632 | 348.9 MiB | verified media |
| Local macOS | `/shorts/`, same public short | PASS | `web_embedded` | 6.85 s | 633,632 | 308.2 MiB | verified media |
| Local macOS | `/shorts/`, second channel (`3UNbabACgHU`) | PASS | repository strategy | 9.43 s | 4,798,215 | 337.0 MiB | verified media |
| Local macOS | normal 10:35 public video (`aqz-KE-bpKQ`) | PASS acquisition | repository strategy | 42.75 s | 288,739,510 | 285.0 MiB | verified media |
| Render | public short (`jNQXAC9IVRw`) | FAIL | `BOT_CHALLENGE` | 22.17 s wall | — | — | — |
| Render | second-channel Short (`3UNbabACgHU`) | FAIL | `BOT_CHALLENGE` | 20.86 s wall | — | — | — |
| Render | normal public video (`aqz-KE-bpKQ`) | FAIL | `BOT_CHALLENGE` | 20.26 s wall | — | — | — |

The 10:35 sample proves acquisition behavior but exceeds the new production
10-minute source-duration limit, so the deployed API must reject it after probe.

## Existing GCE VM

| URL type | Result | Strategy/failure | Download time | Bytes | Peak RAM | Final format |
|---|---|---|---:|---:|---:|---|
| Public short video | PENDING GOOGLE LOGIN | — | — | — | — | — |
| Normal public video | PENDING GOOGLE LOGIN | — | — | — | — | — |
| YouTube Shorts URL | PENDING GOOGLE LOGIN | — | — | — | — | — |
| `youtu.be` URL (`jNQXAC9IVRw`) | BLOCKED `BOT_CHALLENGE` | yt-dlp requested sign-in/cookies | 4 s | — | — | — |
| `youtube.com/watch` URL (`jNQXAC9IVRw`) | BLOCKED `BOT_CHALLENGE` | yt-dlp requested sign-in/cookies | 5 s | — | — | — |
| 5–10 minute public video | PENDING GOOGLE LOGIN | — | — | — | — | — |
| Multiple channels | PENDING GOOGLE LOGIN | — | — | — | — | — |

The two GCE checks above were run from `instance-20260915-154845` without
authenticated cookies. A user must complete the exact Google/YouTube login step
on the VM (or provide a short-lived cookie file) before claiming authenticated
import reliability. No login/cookie/access-control bypass was used.
