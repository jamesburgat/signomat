# Event Flow

1. `capture_service` acquires frames continuously and keeps the latest frame in memory.
2. When recording is active, the same frame stream is written to chunked local video segments.
3. `gps_service` samples GPS independently and persists breadcrumb points during active trips.
4. `inference_service` snapshots the latest frame on its own cadence.
5. The frame passes through preprocessing.
6. Candidate sign localization proposes ROIs.
7. ROIs go through classification.
8. The taxonomy mapper converts raw outputs into `category_id`, `category_label`, `specific_label`, and `grouping_mode`.
9. The deduplicator suppresses repeated nearby detections of the same sign across adjacent frames.
10. Accepted events save:
    - clean frame
    - annotated frame
    - optional crop
    - thumbnails for public/archive performance
11. The detection row is persisted in SQLite and linked to:
    - latest GPS sample
    - active trip
    - current video segment
    - offset within the current segment
12. The upload queue receives metadata and file items for later sync.
13. BLE status and the local API both reflect the updated counters and last-detection summary.

