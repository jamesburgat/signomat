# Worker API

Cloudflare Worker backed by D1 and R2, with the archive frontend served as
static assets from the same Worker.

## What Exists Now

- authenticated `POST /ingest/batch` endpoint using `SIGNOMAT_INGEST_TOKEN`
- same-origin static asset hosting for the archive SPA in `../frontend`
- public read endpoints:
  - `GET /health`
  - `GET /config-check`
  - `GET /public/stats`
  - `GET /public/detections`
  - `GET /public/detections/:eventId`
  - `GET /public/trips`
  - `GET /public/trips/:tripId`
- protected admin endpoints:
  - `GET /admin/review/queue`
  - `PATCH /admin/detections/:eventId/review`
  - `GET /admin/training/summary`
  - `GET /admin/training/jobs`
  - `POST /admin/training/jobs`
  - `GET /admin/training/jobs/:jobId/export`
- D1 schema + migrations in `migrations/`
- Wrangler config with D1/R2 bindings

## What You Need To Fill In

Update `wrangler.jsonc`:

- `database_id`
- `PUBLIC_BASE_URL`
- the custom domain route if you are not using `signs.jamesburgat.com`

Set the Worker secret in Cloudflare:

- `SIGNOMAT_INGEST_TOKEN`
- `SIGNOMAT_ADMIN_TOKEN`

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

Once deployed, the archive UI is served from the Worker root and the API remains
available on the same origin under `/public/*`, `/admin/*`, `/ingest/*`,
`/health`, and `/config-check`.

## Current Shape

This is still a lightweight archive/control plane. It stores metadata, asset
keys, review state, and training-job drafts. The training endpoints prepare
exportable scopes from reviewed archive data; they do not run model training in
Cloudflare.
