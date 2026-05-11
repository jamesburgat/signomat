# Archive Frontend

Frontend for the archive and admin workflows.

## Current Scope

- public archive landing page with an interactive Leaflet detection map,
  filtering, and trip list
- trip detail page with mapped route context, detections, and uploaded video
  segments
- detection detail page with clean/annotated/crop media and a location map
- admin review page for relabeling, notes, and false-positive marking
- training page for drafting export jobs from reviewed archive data
- same-origin admin token support for protected review/training routes

## Run It

Serve this folder with any static file server and point the UI at the Worker API
base URL in the settings panel.

Examples:

```bash
cd archive/frontend
python -m http.server 4173
```

Then open `http://localhost:4173`.

For production, `archive/worker_api/wrangler.jsonc` is configured to ship this
directory as Worker static assets so the site can live directly at
`https://signs.jamesburgat.com`.
