# Google Compute Engine production deployment

This deployment targets only `instance-20260915-154845` in project `dripcut`,
zone `asia-south1-a`. It runs one API/video worker behind Caddy. The API port is
Docker-internal; only 80/443 are published.

## VM layout

- Repository: `/opt/dripcut/repository`
- Protected environment: `/opt/dripcut/.env.production` (`chmod 600`)
- Durable application state: Docker volume `dripcut_state`
- Transient acquisition/render data: `/tmp/dripcut`
- R2: durable source and artifact objects
- Supabase: auth and tenant metadata

The production environment must set `DRIPCUT_API_HOST` to the real API hostname,
for example `api.dripcut.in`, and set both `DRIPCUT_PUBLIC_API_URL` and the
explicit CORS origin list. Never use `*` with credentialed requests.

## Deploy/update

Run from `/opt/dripcut/repository` after checking out the approved commit:

```sh
sudo install -d -m 1777 /tmp/dripcut
sudo chmod 600 /opt/dripcut/.env.production
sudo docker compose --env-file /opt/dripcut/.env.production \
  -f deploy/gcp/docker-compose.yml build --pull
sudo docker compose --env-file /opt/dripcut/.env.production \
  -f deploy/gcp/docker-compose.yml up -d --remove-orphans
sudo docker compose -f deploy/gcp/docker-compose.yml ps
```

Before updating, record the current Git commit and image ID. Rollback is a Git
checkout of that known-good commit followed by the same build/up commands. The
existing Render backend remains untouched as a temporary reference, but must not
consume the same processing queue after cutover.

## Operations

```sh
sudo docker compose -f deploy/gcp/docker-compose.yml logs --tail=200 api
sudo docker compose -f deploy/gcp/docker-compose.yml logs --tail=100 caddy
sudo docker stats --no-stream
free -h
df -h / /tmp
curl -fsS https://api.dripcut.in/api/health
```

The container defaults enforce one video job, a ten-minute/512 MB source limit,
720p output, 30 fps, one FFmpeg thread, sequential clip upload, and a 1536 MB
free-disk admission floor. AI selection, local Whisper, thumbnails, animated
captions, Instagram and ZIP creation are off in the initial MVP profile.
