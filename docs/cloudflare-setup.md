# Cloudflare Repo Setup

## Repo Baseline

The repository now includes a GitHub Actions workflow at
[`deploy-worker.yml`](/home/jamesburgat/signomat/.github/workflows/deploy-worker.yml)
that deploys the Worker from [`archive/worker_api`](/home/jamesburgat/signomat/archive/worker_api).

That workflow assumes:

- the Worker source lives in [`archive/worker_api`](/home/jamesburgat/signomat/archive/worker_api)
- the archive frontend static assets live in [`archive/frontend`](/home/jamesburgat/signomat/archive/frontend) and are deployed by the same Worker
- D1 migrations are applied before deploy
- `SIGNOMAT_INGEST_TOKEN` is pushed as a Cloudflare Worker secret during deploy
- `SIGNOMAT_ADMIN_TOKEN` is pushed as a Cloudflare Worker secret during deploy

## Fill These Values

In [`wrangler.jsonc`](/home/jamesburgat/signomat/archive/worker_api/wrangler.jsonc):

- verify `database_name`
- verify `database_id`
- verify `bucket_name` values for `MEDIA_BUCKET` and `THUMBS_BUCKET`
- verify `PUBLIC_BASE_URL`
- verify the custom domain route under `routes`

The file in this repo already contains concrete values. If your Cloudflare
account, worker name, or subdomain changed, update them here before deploying.

In GitHub repository secrets:

- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID`
- `SIGNOMAT_INGEST_TOKEN`
- `SIGNOMAT_ADMIN_TOKEN`

The GitHub workflow uses the Cloudflare API token and account ID to deploy, and
it publishes `SIGNOMAT_INGEST_TOKEN` into the Worker as a secret.

If you deploy manually instead of GitHub Actions, set the Worker secret in
Cloudflare directly:

- `SIGNOMAT_INGEST_TOKEN`
- `SIGNOMAT_ADMIN_TOKEN`

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

## Troubleshooting Checklist

If the GitHub runner or Cloudflare deploy is failing, check these in order:

1. Confirm the workflow is deploying from the correct directory.
   The Worker code is under [`archive/worker_api`](/home/jamesburgat/signomat/archive/worker_api), not the repo root.
2. Confirm GitHub secrets exist and are spelled exactly:
   `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `SIGNOMAT_INGEST_TOKEN`.
3. Confirm the API token can edit Workers, D1, and R2 resources in the target account.
4. Confirm the D1 database ID in [`wrangler.jsonc`](/home/jamesburgat/signomat/archive/worker_api/wrangler.jsonc) matches the target Cloudflare account.
5. Confirm both R2 buckets already exist:
   `signomat-media` and `signomat-thumbs` unless you intentionally renamed them.
6. Confirm `PUBLIC_BASE_URL` matches the deployed Worker hostname.
7. If the deploy succeeds but ingest fails, call `GET /config-check` and verify `hasIngestToken` and `hasPublicBaseUrl` both return `true`.
8. If migrations fail, run `npx wrangler d1 migrations apply ARCHIVE_DB --remote` manually and inspect the exact D1 error before retrying the workflow.
9. If the workflow appears stuck in GitHub, check whether the job is tied to a protected GitHub environment that requires approval before secrets are released.

## Current Endpoints

- `GET /`
- `GET /health`
- `GET /config-check`
- `GET /public/stats`
- `POST /ingest/batch`
- `GET /public/detections`
- `GET /public/detections/:eventId`

## Authentication

The Pi should send:

```http
Authorization: Bearer <SIGNOMAT_INGEST_TOKEN>
```

The Worker rejects mismatched tokens with `401`.

## Custom Domain

The Worker is configured to attach directly to `signs.jamesburgat.com` via a
Cloudflare Custom Domain route in `wrangler.jsonc`.

If the hostname already has an existing DNS record, remove or replace that
record before the first deploy so Cloudflare can create the Worker-backed custom
domain record.
