# Cloudflare Repo Setup

## Fill These Values

In [`wrangler.jsonc`](/home/jamesburgat/signomat/archive/worker_api/wrangler.jsonc):

- replace `REPLACE_WITH_D1_DATABASE_ID`
- replace `REPLACE_WITH_SUBDOMAIN`

In Cloudflare Worker secrets:

- `SIGNOMAT_INGEST_TOKEN`

## Bindings

The Worker expects:

- D1 binding: `ARCHIVE_DB`
- R2 binding: `MEDIA_BUCKET`
- R2 binding: `THUMBS_BUCKET`

## Recommended Commands

```bash
cd archive/worker_api
npm install
npx wrangler d1 migrations apply ARCHIVE_DB --remote
npx wrangler deploy
```

## Current Endpoints

- `GET /health`
- `GET /config-check`
- `POST /ingest/batch`
- `GET /public/detections`
- `GET /public/detections/:eventId`

## Authentication

The Pi should send:

```http
Authorization: Bearer <SIGNOMAT_INGEST_TOKEN>
```

The Worker rejects mismatched tokens with `401`.

## Next Cloudflare Steps

- add media upload endpoints or direct upload flow for R2-backed assets
- add trip and breadcrumb public endpoints
- add admin review auth and mutation endpoints
- connect Pages later when `archive/frontend` is ready
