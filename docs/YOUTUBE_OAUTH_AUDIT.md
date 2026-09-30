# YouTube OAuth and publishing audit

Audit date: 2026-09-20. This file records configuration names and behavior only; it must never contain credential values.

## Existing implementation

- [x] OAuth start: `GET /api/social/youtube/authorize`.
- [x] OAuth callback: `GET /api/social/youtube/callback`.
- [x] The client ID and secret are server-only (`DRIPCUT_YOUTUBE_CLIENT_ID`, `DRIPCUT_YOUTUBE_CLIENT_SECRET`).
- [x] OAuth state is signed, expires after ten minutes, and is bound to the authenticated user, workspace, and provider.
- [x] Authorization uses an authorization code, offline access, incremental authorization, and an explicit consent prompt when connecting.
- [x] Credentials are encrypted at rest with `DRIPCUT_CREDENTIAL_ENCRYPTION_KEY`.
- [x] Access-token expiry and refresh tokens are retained in the encrypted credential payload.
- [x] Expired access tokens are refreshed before publishing and the refreshed credential is saved.
- [x] `channels.list(mine=true)` validates a real YouTube channel before marking the connection active.
- [x] Disconnect removes the workspace-scoped credential.
- [x] Scheduling records are stored in Supabase and selected through workspace RLS.
- [x] The publisher uses YouTube's resumable-upload endpoint and streams from a file rather than loading the video into memory.
- [x] Interrupted uploads require checking the remote account before retrying; they are not automatically uploaded again.

## Gaps found in the deployed state

- [ ] No YouTube OAuth client ID or secret is configured on the production VM.
- [ ] `DRIPCUT_PUBLIC_API_URL` has duplicate values; the last value is a stale HTTP IP, so the generated callback is invalid for production OAuth.
- [x] Publishing is visible in the production navigation and completed-clip results.
- [x] YouTube connection is shown in Settings and in the scheduling flow.
- [x] The default scope requests upload access and read-only channel identity access.
- [x] The callback returns to Settings with friendly connected/cancelled states.
- [x] A missing refresh token is rejected instead of being stored as a successful connection.
- [x] Connection responses expose channel ID and avatar metadata without exposing tokens.
- [x] The form schedules one selected clip and includes title, description, privacy, now/future, and timezone controls.
- [x] Future public publishing uploads immediately with YouTube `status.publishAt` in UTC.
- [x] Supabase artifact, social connection, scopes, expiry, attempt, and error metadata are populated.
- [x] Provider errors are mapped to safe user messages and persisted error codes.

## Production contract

- Callback: `https://dripcut.onrender.com/api/social/youtube/callback` (the existing HTTPS frontend origin proxies `/api` and keeps the DripCut session cookie on the callback request).
- Minimum scopes: `youtube.upload` plus `youtube.readonly`; no Gmail, Drive, Calendar, Analytics, or unrelated scopes.
- A connection is active only when a refresh token and an authenticated channel ID are present.
- Future public publishing is uploaded as private with an ISO-8601 UTC `status.publishAt`, which lets YouTube own the final publish transition.
- Private and unlisted QA uploads are accepted immediately without a public `publishAt`.

## Scheduling reliability review — 2026-10-01

The connector code now preserves connection IDs on reconnect, normalizes OAuth
transport failures, and rejects failed Meta long-lived-token exchanges. Publishing
uses conditional database claims so concurrent dispatchers cannot start the same
scheduled post. Due filtering runs before the Supabase batch limit, so future
Instagram posts cannot starve native YouTube scheduling. Background publishing
uses worker credentials instead of an expiring browser session.

Already uploaded/published posts cannot be requeued through the edit endpoint.
Whole-upload automatic retries are disabled because a lost provider response does
not prove publishing failed. Local interrupted uploads are flagged at restart;
Supabase uploads older than one hour are flagged for inspection during polling.
Successful remote IDs are saved before refreshed credential maintenance, and an
Instagram permalink lookup failure cannot undo a successful publication.

The Schedule page restores the latest schedule after reload, supports selecting
Instagram alone when YouTube is disconnected, ignores stale project clip responses,
and labels YouTube privacy separately from Instagram audience visibility.

### Remaining live prerequisites

Only local configuration files were inspected; these are not a live deployment audit.
`.env` contains YouTube app credentials but no Meta app credentials. `.env.render`
contains neither provider's app credentials. Both files have worker/encryption/state
configuration and select S3 storage. No secret values were printed or changed.

Before claiming live publishing works:

1. Configure YouTube client ID/secret and Meta app ID/secret on the deployed server.
2. Register the exact browser-facing HTTPS callbacks shown above in Google and Meta.
3. Confirm Google consent access and YouTube Data API enablement. Public uploads from
   unverified API projects can remain private until Google's API compliance audit:
   https://developers.google.com/youtube/v3/docs/videos/insert
4. Confirm Meta permissions/app access and a professional Instagram account linked
   to a Facebook Page for this Facebook Login adapter.
5. Verify the existing social database migrations, persistent credential encryption
   key, service-role worker access, always-running scheduler, and externally fetchable
   S3/R2 signed HTTPS media URLs.
6. Complete real consent, token refresh, a private YouTube upload, and a deliberately
   approved Instagram Reel/future public YouTube schedule. Automated tests use fake
   provider responses and do not establish these live prerequisites.

Known limits: provider-side reconciliation of an ambiguous upload is manual;
YouTube's final transition from native scheduled to published is not polled here.
The JSON social store remains intended for a single application process; use
Supabase for multiple instances. No deployment or production publishing was done.
