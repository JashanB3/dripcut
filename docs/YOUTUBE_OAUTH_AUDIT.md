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
- [x] The background scheduler recovers interrupted `uploading` records after restart.

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
