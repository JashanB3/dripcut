# YouTube scheduling quota

Checked: 2026-09-20. This is an operational note, not a request to buy or increase quota.

## Current MVP capacity

- The YouTube Data API is enabled in the DripCut Google Cloud project.
- Google currently documents a default **Video Uploads quota of 100 uploads per day** per project.
- `videos.insert` consumes **1 Video Upload unit** in the current granular quota model.
- Channel identity lookup (`channels.list`) uses the separate general YouTube Data API quota.
- Google documents a default **10,000 general units per day**, resetting at midnight Pacific Time.
- DripCut therefore treats approximately **100 upload attempts per day** as the practical default ceiling until the Cloud Console shows a project-specific override.

Retries must be bounded because a new upload attempt can consume another upload unit. A successful YouTube video ID is persisted immediately so DripCut does not intentionally submit the same completed upload again.

## Verification notes

- A scheduled public video is uploaded with `privacyStatus=private` and a UTC `publishAt` timestamp. YouTube owns the final transition to public.
- Publish-now QA should use Private or Unlisted unless public release is explicitly intended.
- Projects whose OAuth consent screen is in Testing can issue refresh tokens that expire after seven days for external apps using non-basic scopes. Production scheduling requires the OAuth app to be moved to Production and, where applicable, verified by Google.
- YouTube may force uploads from an unverified API project to remain private. The production E2E test must verify the actual project behavior before launch.

Official references:

- <https://developers.google.com/youtube/v3/determine_quota_cost>
- <https://developers.google.com/youtube/v3/docs/videos/insert>
- <https://developers.google.com/youtube/v3/docs/videos>
