# Mac YouTube acquisition worker

This worker keeps the customer journey unchanged. It polls the public API over HTTPS, obtains
the source on the Mac, uploads directly to the configured private S3/R2 storage, and reports a
small completion payload. It does not open an inbound port. When
`DRIPCUT_YOUTUBE_COOKIES_FROM_BROWSER` is configured, yt-dlp reads the current signed-in browser
session locally for each job, so no cookie file is uploaded to DripCut or copied to the cloud.

## Before enabling it

1. Apply `supabase/migrations/202609160001_acquisition_jobs.sql` in Supabase after rehearsing it
   on a non-production project.
2. Set these API environment variables in Render's secret manager:

   - `DRIPCUT_YOUTUBE_ACQUISITION_MODE=worker`
   - `DRIPCUT_WORKER_ENABLED=true`
   - `DRIPCUT_WORKER_TOKEN` to a newly generated long random secret
   - `DRIPCUT_WORKER_LEASE_SECONDS=120`

   The API already needs the existing Supabase service-role key and S3/R2 credentials. Do not
   expose any of these values to the frontend.

3. On the Mac, copy `.env.worker.example` to `.env.worker`. Set the same worker token and the
   existing private storage credentials. Set `DRIPCUT_WORKER_API_URL` to the public Render API.
   Keep the configured browser signed into YouTube. The worker reads fresh cookies at job time;
   you do not need to export and replace `youtube-cookies.txt` every few days.

4. Run `./scripts/install-youtube-worker.sh`, review the generated `.env.worker`, then run
   `./scripts/start-youtube-worker.sh`.

The worker intentionally runs one job at a time. If it stops, its lease expires and the job is
available for a later worker retry. A user job remains queued while no worker is online.

## Rollback

Set `DRIPCUT_YOUTUBE_ACQUISITION_MODE=local` on the API and redeploy. The original in-process
YouTube path resumes. Stop the Mac worker. Existing completed acquisition jobs and storage objects
remain intact; queued worker jobs should be allowed to finish or be cancelled before rollback.

## Required acceptance test

After a staging rehearsal, use `https://www.youtube.com/watch?v=YXtkp7-aDEI` and verify the full
path: queued job, Mac claim, full download, FFprobe validation, object upload, source finalization,
editor load, one clip render. Do not enable the production mode until this succeeds.
