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

Open `http://127.0.0.1:5173/signup`, create a local development account, then
open `http://127.0.0.1:5173/auto-clip`.

Authentication is required by default. Local development uses the signed,
file-backed local provider below `DRIPCUT_HOME`; production refuses to start
with that provider. See [SaaS foundation](saas-foundation.md) for Supabase setup.

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

The importer tries each bounded, supported strategy once in this order:

1. `web_embedded` for compatible public, embeddable videos
2. `mweb` with a configured GVS PO-token provider
3. `web_safari` HLS fallback
4. yt-dlp's current recommended public-client selection
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

The production package includes the bgutil yt-dlp plugin. The provider itself
must run separately; no temporary token is stored in DripCut. If YouTube
requires verification and no provider is configured, the API returns a
region-aware error and local uploads remain available.

`GET /api/youtube/diagnostics` reports yt-dlp, FFmpeg, FFprobe, EJS, Node/JS
runtime, PO-provider, cookie fallback, proxy, enabled strategies, last successful
strategy, last normalized failure class, HTTP status, login challenge state, and
the bounded attempt list. It returns only booleans, versions, status codes, and
strategy names, never cookie paths, proxy/provider URLs, tokens, or credentials.

AWS and other datacenter IP ranges are challenged more aggressively than many
residential networks. Install the PO-provider plugin and run its provider as a
separate service for production workers; keep cookie fallback optional and
operator-managed. The frontend and SourceAsset pipeline do not change when the
network strategy changes.

### Render production configuration

#### ₹0 launch profile

Do **not** deploy the optional PoT provider during the zero-cost launch phase.
Leave `DRIPCUT_YOUTUBE_POT_PROVIDER_URL` unset on the API service. DripCut then
uses its existing `web_embedded`, `web_safari_hls`, and `recommended` yt-dlp
strategies, while local upload remains the reliable fallback for a challenged
public video.

There is no recommended zero-cost hosting arrangement for this provider that
keeps it private from the public internet:

- Render Private Services have no free compute plan.
- A separate Render Free Web Service is public, may sleep after inactivity, and
  cannot receive Render private-network traffic.
- Oracle Always Free and free demo-hosting platforms can run a small service, but
  the Render API would have to reach it through a public endpoint. The bgutil
  provider is not an authenticated customer-facing API, so this is not an
  acceptable launch configuration.

Revisit the private-service configuration below only after launch revenue
supports a paid internal service. No product route, job behavior, storage, or
editor behavior changes when the variable remains unset.

Create a Render **Private Service** named `dripcut-youtube-pot` from the pinned
container image `brainicism/bgutil-ytdlp-pot-provider:2.0.0`. The provider listens
on port `4416`; do not expose it publicly. Place it in the same Render region and
workspace/private network as the DripCut API.

Use Render's **Existing Image** source. It has no build command and no start command:
the image starts its own HTTP provider on port `4416`. Do not assign a public URL.
Copy the private-network URL shown by Render, including `:4416`, into the API
variable below. Version 2 is required because it contains the provider's current
security fixes; do not deploy the old `1.3.2` image.
The API enables `mweb_pot` only when that variable is non-empty and the installed
`bgutil-ytdlp-pot-provider` package is available; it passes the URL only to yt-dlp's
`youtubepot-bgutilhttp` extractor argument.

Configure the DripCut **Web Service** with:

| Variable | Value |
|---|---|
| `DRIPCUT_YOUTUBE_POT_PROVIDER_URL` | the provider's Render private-network URL, including port `4416` |
| `DRIPCUT_YOUTUBE_SOCKET_TIMEOUT` | `30` |
| `DRIPCUT_YOUTUBE_VERBOSE` | `1` while diagnosing, otherwise unset |

The private service needs outbound HTTPS access to YouTube. The DripCut API needs
outbound HTTPS access to YouTube and private-network access to the provider on
TCP `4416`. Do not put the provider URL or any YouTube credential in a `VITE_`
variable.

Cookies are an optional final fallback, not the primary strategy. In Render,
create a Secret File named `youtube-cookies.txt` mounted at
`/etc/secrets/youtube-cookies.txt`, then set either:

```text
DRIPCUT_YOUTUBE_COOKIE_FILE=/etc/secrets/youtube-cookies.txt
```

or the compatible alias:

```text
YOUTUBE_COOKIE_FILE=/etc/secrets/youtube-cookies.txt
```

Use a Netscape-format file managed by the operator. Never collect customer
browser cookies. Cookie-backed YouTube sessions can expire or be challenged and
must be rotated by the operator; using an account also carries YouTube account
risk. The cookie file pattern is excluded from Docker build context and its path
and contents are excluded from diagnostics.

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
