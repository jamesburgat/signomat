# Worker API

Cloudflare Worker backed by D1 and R2.

## What Exists Now

- authenticated `POST /ingest/batch` endpoint using `SIGNOMAT_INGEST_TOKEN`
- public read endpoints:
  - `GET /health`
  - `GET /config-check`
  - `GET /public/detections`
  - `GET /public/detections/:eventId`
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

This first version is metadata-first. It stores archive rows and asset keys, but
does not yet implement bulk media upload handling through the Worker. That is
the next sync-side step.
