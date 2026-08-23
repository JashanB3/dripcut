# Web processing API

The React product shell talks to a FastAPI process on port `8000`. Local and
server deployments use the same API and processing services; only the storage
root and optional YouTube verification provider change.

## Local development

Run these in separate terminals from the repository root:

```bash
source .venv/bin/activate
make api-dev
```

```bash
cd web
npm run dev
```

Open `http://127.0.0.1:5173/#/auto-clip`.

## Storage

Sources and artifacts are stored below DripCut's project directory in `web/`.
Set `DRIPCUT_HOME` to move all runtime data without changing code. This is the
local adapter boundary that can later be replaced by S3 and a distributed job
store on AWS.

## YouTube imports

YouTube imports run as background jobs and report product stages instead of raw
yt-dlp output:

1. Fetching video information
2. Connecting to YouTube
3. Downloading video/audio
4. Preparing video
5. Checking downloaded video
6. Ready

The importer tries bounded, supported strategies in this order:

1. yt-dlp's current recommended client selection
2. `mweb` with a configured PO-token provider, when the plugin is installed
3. `web_embedded` progressive MP4 fallback
4. `web_safari` HLS fallback
5. an explicitly configured backend cookie file

Every successful download is limited to 1080p, normalized to MP4, and checked
with FFprobe before it is registered as a source. Private, paid, members-only,
DRM-protected, and otherwise unauthorized media are not bypassed.

YouTube increasingly requires per-video Proof-of-Origin tokens. DripCut never
reads browser cookies automatically. A deployment can explicitly configure:

- `DRIPCUT_YOUTUBE_POT_PROVIDER_URL`, for example `http://127.0.0.1:4416`
- `DRIPCUT_YOUTUBE_COOKIE_FILE`, an explicitly managed Netscape cookie file
- `DRIPCUT_YOUTUBE_PROXY`, an operator-managed HTTP/SOCKS proxy
- `DRIPCUT_YOUTUBE_SOCKET_TIMEOUT`, from 5 to 120 seconds (default 30)
- `DRIPCUT_YOUTUBE_VERBOSE=1`, for redacted server-side diagnostics

Install the optional Python plugin with `pip install -e '.[youtube-pot]'` and
run a compatible bgutil provider before setting the provider URL. If YouTube
requires verification and no provider is configured, the API returns a useful
error and local uploads remain available.

`GET /api/youtube/diagnostics` reports yt-dlp, FFmpeg, FFprobe, EJS, JS runtime,
PO-provider, cookie fallback, proxy, and enabled strategy status. It returns only
booleans and versions, never cookie paths, proxy URLs, tokens, or credentials.

AWS and other datacenter IP ranges are challenged more aggressively than many
residential networks. Install the PO-provider plugin and run its provider as a
separate service for production workers; keep cookie fallback optional and
operator-managed. The frontend and SourceAsset pipeline do not change when the
network strategy changes.

## Endpoints

- `POST /api/sources/upload`
- `POST /api/sources/youtube`
- `POST /api/jobs/youtube`
- `GET /api/youtube/diagnostics`
- `GET /api/sources/{source_id}`
- `GET /api/sources/{source_id}/media`
- `POST /api/sources/{source_id}/standard-plan`
- `POST /api/jobs/clips`
- `GET /api/jobs/{job_id}`
- `GET /api/artifacts/{artifact_id}/media`
- `GET /api/artifacts/{artifact_id}/download`
