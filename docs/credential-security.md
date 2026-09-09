# Credential Security

DripCut treats every provider credential, OAuth secret, signing key, database password, and
service-role token as backend-only data. A credential that appears in chat, a ticket, a log,
source control, or a frontend bundle must be revoked and replaced rather than merely deleted.

## Secret Boundaries

| Credential | Runtime | Browser access | Rotation owner |
|---|---|---:|---|
| Supabase service-role key | API and trusted workers | Never | Supabase project owner |
| Supabase anon key | API configuration; public use is permitted by Supabase | Allowed when intentionally used with RLS | Supabase project owner |
| R2/S3 access key pair | API and media workers | Never | Cloudflare/AWS administrator |
| Groq API key | API transcription worker | Never | Groq account owner |
| NVIDIA API key | API AI worker | Never | NVIDIA account owner |
| Google/YouTube client secret | API OAuth callback and publisher | Never | Google Cloud administrator |
| Meta app secret | API OAuth callback and publisher | Never | Meta app administrator |
| OAuth state secret | API only | Never | DripCut operator |
| Credential encryption key | API and social workers | Never | DripCut operator |

`VITE_API_BASE_URL`, `VITE_EXPERIMENTAL_TOOLS`, and
`VITE_YOUTUBE_PUBLISHING_BETA` are public frontend configuration. Never create a
`VITE_` variable containing `SECRET`, `TOKEN`, `PASSWORD`, `PRIVATE`, `SERVICE_ROLE`, or
`API_KEY`. Vite substitutes `VITE_` values into browser code at build time.

## Storage Rules

1. Keep local values only in the ignored root `.env` or an operator-managed secret store.
2. Do not place real values in `.env.example`, tests, screenshots, shell history, support chats,
   documentation, Dockerfiles, compose files, CI YAML, or frontend environment files.
3. Inject hosted values with the hosting provider's encrypted secret manager.
4. Give CI only the credentials required by a specific live-provider job. Normal unit, build,
   lint, and E2E jobs use fake/local providers and require no production credentials.
5. Scope R2/S3 credentials to the private DripCut bucket. Do not grant account-wide permissions.
6. Keep the Supabase service-role key out of React. Browser database access, if introduced, must
   use only the anon key plus RLS.

## Rotation Runbook

Use this order to avoid accidentally leaving an old credential active:

1. Create the replacement in the provider dashboard without deleting the old credential yet.
2. Add the replacement to local and hosted secret stores without displaying it in logs.
3. Restart the API/workers and run the provider-specific health or controlled smoke test.
4. Revoke the previous credential after the replacement is confirmed.
5. Confirm the revoked credential can no longer authenticate.
6. Record the provider, operator, rotation date, and verification result. Never record the value.

For the credential-encryption key, use an explicit key-rotation migration that decrypts existing
OAuth records with the previous key and re-encrypts them with the replacement. Replacing this key
without migration makes stored social connections unreadable.

## Incident Response

Treat a credential as exposed when its value reaches source control, a frontend bundle, an
untrusted log, chat, issue tracker, or third-party document. Revoke it promptly, review provider
access logs, invalidate related sessions where supported, inspect audit logs for misuse, and run
the repository/history/bundle scans below. Deleting the text does not make the credential safe.

## Verification

```bash
cd /Users/jashan/Documents/DripCut/dripcut
python scripts/check_secrets.py --history

cd web
npm run build
cd ..
python scripts/check_secrets.py --bundle web/dist --env-file .env
```

The scanner reports only the credential type and file/blob location. It never prints matched
values. The second command compares ignored backend-only values with the compiled browser bundle.
