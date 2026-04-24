# Archive Frontend

Minimal static frontend for the archive and admin workflows.

## Current Scope

- public archive landing page with a low-fi detection map and recent trip list
- trip detail page with route sketch, detections, and uploaded video segments
- detection detail page with clean/annotated/crop media where available
- admin review page for quick relabeling, notes, and false-positive marking
- training page for drafting export jobs from reviewed archive data

## Run It

Serve this folder with any static file server and point the UI at the Worker API
base URL in the top bar.

Examples:

```bash
cd archive/frontend
python -m http.server 4173
```

Then open `http://localhost:4173`.
