# Worker API

Cloudflare Worker backed by D1 and R2.

## What Exists Now

- authenticated `POST /ingest/batch` endpoint using `SIGNOMAT_INGEST_TOKEN`
- public read endpoints:
  - `GET /health`
  - `GET /config-check`
  - `GET /public/detections`
  - `GET /public/detections/:eventId`
  - `GET /public/trips`
  - `GET /public/trips/:tripId`
- low-fi admin endpoints:
  - `GET /admin/review/queue`
  - `PATCH /admin/detections/:eventId/review`
  - `GET /admin/training/summary`
  - `GET /admin/training/jobs`
  - `POST /admin/training/jobs`
  - `GET /admin/training/jobs/:jobId/export`
- D1 schema + migration scaffold in `migrations/`
- Wrangler config with D1/R2 bindings

## What You Need To Fill In

Update `wrangler.jsonc`:

- `database_id`
- `PUBLIC_BASE_URL`

Set the Worker secret in Cloudflare:

- `SIGNOMAT_INGEST_TOKEN`

## Local Development

```bash
cd archive/worker_api
npm install
cp .dev.vars.example .dev.vars
npx wrangler d1 migrations apply ARCHIVE_DB --local
npx wrangler dev
```

## Deploy

```bash
cd archive/worker_api
npm install
npx wrangler d1 migrations apply ARCHIVE_DB --remote
npx wrangler deploy
```

## Current Shape

This is still a lightweight archive/control plane. It stores metadata, asset
keys, review state, and training-job drafts. The training endpoints prepare
exportable scopes from reviewed archive data; they do not run model training in
Cloudflare.
