from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse


def resize_frame_for_preview(frame, max_width: int | None):
    if not max_width or frame.shape[1] <= max_width:
        return frame
    scale = max_width / max(frame.shape[1], 1)
    height = max(1, int(round(frame.shape[0] * scale)))
    return cv2.resize(frame, (max_width, height))


def encode_preview_jpeg(frame, jpeg_quality: int, max_width: int | None):
    preview_frame = resize_frame_for_preview(frame, max_width)
    quality = max(30, min(jpeg_quality, 95))
    ok, encoded = cv2.imencode(".jpg", preview_frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        return None
    return encoded.tobytes()


class CameraTuningUpdate(BaseModel):
    auto_exposure: bool | None = None
    exposure_compensation: float | None = None
    brightness: float | None = None
    contrast: float | None = None
    exposure_time_us: int | None = None
    analogue_gain: float | None = None


def create_app(runtime) -> FastAPI:
    app = FastAPI(title="Signomat Local API", version="0.1.0")

    def preview_stream(frame_interval_seconds: float, jpeg_quality: int, max_frames: int | None, max_width: int | None):
        emitted = 0
        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality]
        while True:
            if max_frames is not None and emitted >= max_frames:
                return
            packet = runtime.capture_service.latest_frame()
            if packet is None:
                time.sleep(frame_interval_seconds)
                continue
            preview_frame = resize_frame_for_preview(packet.frame, max_width)
            ok, encoded = cv2.imencode(".jpg", preview_frame, encode_params)
            if not ok:
                time.sleep(frame_interval_seconds)
                continue
            emitted += 1
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + encoded.tobytes() + b"\r\n"
            )
            time.sleep(frame_interval_seconds)

    @app.get("/", response_class=HTMLResponse)
    def root():
        return """
        <html>
          <head><title>Signomat Local API</title></head>
          <body style="font-family: sans-serif;">
            <h1>Signomat Local API</h1>
            <p><a href="/docs">Open API docs</a></p>
            <p><a href="/preview">Open live preview</a></p>
            <p><a href="/recordings">Browse trip recordings</a></p>
          </body>
        </html>
        """

    @app.get("/health")
    def health():
        return runtime.health()

    @app.get("/status")
    def status():
        return runtime.status_snapshot()

    @app.get("/ble/payloads")
    def ble_payloads():
        return runtime.ble_service.characteristic_payloads()

    @app.get("/session")
    def session():
        return {"trip_id": runtime.current_trip_id, "trip_active": bool(runtime.current_trip_id)}

    @app.post("/session/start")
    def session_start():
        return runtime.start_trip()

    @app.post("/session/stop")
    def session_stop():
        return runtime.stop_trip()

    @app.post("/recording/start")
    def recording_start():
        return runtime.start_recording()

    @app.post("/recording/stop")
    def recording_stop():
        return runtime.stop_recording()

    @app.post("/inference/enable")
    def inference_enable():
        return runtime.enable_inference()

    @app.post("/inference/disable")
    def inference_disable():
        return runtime.disable_inference()

    @app.get("/detections/recent")
    def detections_recent(limit: int = 20):
        return runtime.database.recent_detections(limit)

    @app.get("/detections/{event_id}")
    def detection_detail(event_id: str):
        detection = runtime.database.detection_by_id(event_id)
        if not detection:
            raise HTTPException(status_code=404, detail="detection not found")
        return detection

    @app.get("/trips")
    def trips(limit: int = 20):
        return runtime.database.recent_trips(limit)

    @app.get("/gps/recent")
    def gps_recent(limit: int = 50):
        return runtime.database.recent_gps_points(limit)

    @app.get("/video/recent")
    def video_recent(limit: int = 20):
        return runtime.database.recent_video_segments(limit)

    @app.get("/camera/tuning")
    def camera_tuning():
        return runtime.camera_tuning()

    @app.post("/camera/tuning")
    def camera_tuning_update(update: CameraTuningUpdate):
        return runtime.update_camera_tuning(update.model_dump(exclude_none=False))

    @app.get("/recordings", response_class=HTMLResponse)
    def recordings():
        trips = runtime.database.recent_trips(100)
        trip_sections: list[str] = []
        for trip in trips:
            trip_id = trip["trip_id"]
            segments = runtime.database.video_segments_for_trip(trip_id)
            if not segments:
                continue
            segment_links: list[str] = []
            for segment in segments:
                size_mb = (segment.get("file_size") or 0) / 1024 / 1024
                segment_links.append(
                    (
                        "<li>"
                        f"<a href=\"/recordings/{trip_id}\">{trip_id}</a> :: "
                        f"<a href=\"/recordings/video/{segment['video_segment_id']}\">{segment['video_segment_id']}</a> "
                        f"({size_mb:.1f} MB)"
                        "</li>"
                    )
                )
            trip_sections.append(
                (
                    "<section style=\"margin-bottom:24px;\">"
                    f"<h2 style=\"margin:0 0 8px;\">{trip_id}</h2>"
                    f"<div style=\"color:#666;margin-bottom:8px;\">Status: {trip.get('status')} | Started: {trip.get('started_at_utc')}</div>"
                    "<ul style=\"margin:0;padding-left:20px;\">"
                    + "".join(segment_links)
                    + "</ul></section>"
                )
            )

        body = "".join(trip_sections) or "<p>No trip recordings found yet.</p>"
        return (
            "<html><head><title>Signomat Recordings</title></head>"
            "<body style=\"font-family:sans-serif;margin:24px;\">"
            "<h1>Trip Recordings</h1>"
            "<p><a href=\"/\">Back to local API</a></p>"
            f"{body}</body></html>"
        )

    @app.get("/recordings/{trip_id}", response_class=HTMLResponse)
    def recordings_trip(trip_id: str):
        segments = runtime.database.video_segments_for_trip(trip_id)
        if not segments:
            raise HTTPException(status_code=404, detail="trip recordings not found")
        trip = next((item for item in runtime.database.recent_trips(500) if item["trip_id"] == trip_id), None)
        sources = [f"/recordings/video/{segment['video_segment_id']}" for segment in reversed(segments)]
        playlist_json = json.dumps(sources)
        rows: list[str] = []
        for segment in segments:
            size_mb = (segment.get("file_size") or 0) / 1024 / 1024
            duration = segment.get("duration_sec") or 0
            rows.append(
                (
                    "<li style=\"margin-bottom:10px;\">"
                    f"<button type=\"button\" onclick=\"playSegment('/recordings/video/{segment['video_segment_id']}')\" "
                    "style=\"padding:8px 12px;margin-right:8px;\">Play</button>"
                    f"<strong>{segment['video_segment_id']}</strong><br />"
                    f"<span style=\"color:#666;\">Start: {segment.get('start_timestamp_utc')} | Duration: {duration:.1f}s | Size: {size_mb:.1f} MB</span> "
                    f"<a href=\"/recordings/video/{segment['video_segment_id']}\">Direct link</a>"
                    "</li>"
                )
            )
        status_line = ""
        if trip is not None:
            status_line = f"<p style=\"color:#666;\">Status: {trip.get('status')} | Started: {trip.get('started_at_utc')}</p>"
        return (
            "<html><head><title>Signomat Trip Recordings</title></head>"
            "<body style=\"font-family:sans-serif;margin:24px;\">"
            f"<h1>{trip_id}</h1>"
            f"{status_line}"
            "<p><a href=\"/recordings\">Back to recordings</a></p>"
            "<div style=\"margin-bottom:24px;padding:16px;border:1px solid #ddd;border-radius:12px;\">"
            "<h2 style=\"margin-top:0;\">Trip Player</h2>"
            "<p style=\"color:#666;\">Chunks stay separate on disk for reliability, but this player lets you watch the whole trip in sequence in the browser.</p>"
            "<video id=\"trip-player\" controls preload=\"metadata\" style=\"width:100%;max-width:960px;background:#000;\"></video>"
            "<div style=\"margin-top:12px;display:flex;gap:10px;\">"
            "<button type=\"button\" onclick=\"playAll()\" style=\"padding:8px 12px;\">Play Full Trip</button>"
            "<button type=\"button\" onclick=\"playFirst()\" style=\"padding:8px 12px;\">Restart From Beginning</button>"
            "</div></div>"
            "<h2>Segments</h2>"
            "<ul style=\"padding-left:20px;\">"
            + "".join(rows)
            + "</ul>"
            + (
                "<script>"
                f"const playlist = {playlist_json};"
                "const player = document.getElementById('trip-player');"
                "let currentIndex = 0;"
                "function loadIndex(index, autoplay) {"
                "  if (!playlist.length) return;"
                "  currentIndex = Math.max(0, Math.min(index, playlist.length - 1));"
                "  player.src = playlist[currentIndex];"
                "  player.load();"
                "  if (autoplay) player.play().catch(() => {});"
                "}"
                "function playSegment(src) {"
                "  const index = playlist.indexOf(src);"
                "  if (index >= 0) loadIndex(index, true);"
                "}"
                "function playAll() { loadIndex(currentIndex, true); }"
                "function playFirst() { loadIndex(0, true); }"
                "player.addEventListener('ended', () => {"
                "  if (currentIndex + 1 < playlist.length) {"
                "    loadIndex(currentIndex + 1, true);"
                "  }"
                "});"
                "if (playlist.length) loadIndex(0, false);"
                "</script>"
            )
            + "</body></html>"
        )

    @app.get("/recordings/video/{segment_id}")
    def recordings_video(segment_id: str):
        segment = runtime.database.video_segment_by_id(segment_id)
        if not segment:
            raise HTTPException(status_code=404, detail="video segment not found")
        relative_path = segment.get("file_path")
        if not relative_path:
            raise HTTPException(status_code=404, detail="video file missing")
        video_path = runtime.storage.base_dir / Path(relative_path)
        if not video_path.exists():
            raise HTTPException(status_code=404, detail="video file missing on disk")
        return FileResponse(video_path, media_type="video/mp4", filename=video_path.name)

    @app.get("/preview", response_class=HTMLResponse)
    def preview():
        return """
        <html>
          <head><title>Signomat Preview</title></head>
          <body style="margin:0;background:#111;color:#eee;font-family:sans-serif;">
            <div style="padding:12px 16px;">Signomat live preview</div>
            <div style="display:grid;grid-template-columns:minmax(0,1fr) 360px;gap:16px;padding:0 16px 16px;align-items:start;">
              <div>
                <img src="/preview.mjpg" style="display:block;max-width:100%;height:auto;border:1px solid #333;" />
              </div>
              <div style="display:grid;gap:16px;">
                <div style="background:#1a1a1a;border:1px solid #333;border-radius:12px;padding:16px;">
                  <h2 style="margin-top:0;">Camera Exposure Audit</h2>
                  <p style="color:#bbb;font-size:14px;">Forced exposure, gain, brightness, and contrast adjustments are disabled. The app now leaves camera hardware controls unmanaged.</p>
                  <div id="camera-status" style="min-height:20px;color:#9fe870;margin-bottom:12px;"></div>
                  <div id="camera-audit" style="display:grid;gap:8px;color:#ddd;font-size:14px;"></div>
                  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:14px;">
                    <button type="button" onclick="loadCameraTuning()" style="padding:8px 12px;">Refresh</button>
                  </div>
                </div>
                <div style="background:#1a1a1a;border:1px solid #333;border-radius:12px;padding:16px;">
                  <h2 style="margin-top:0;">Post-Trip Classification</h2>
                  <p style="color:#bbb;font-size:14px;">Strong frames are classified after trips end, then written back into the trip records.</p>
                  <div id="classification-status" style="min-height:20px;color:#9fe870;margin-bottom:12px;"></div>
                  <div id="classification-audit" style="display:grid;gap:8px;color:#ddd;font-size:14px;"></div>
                  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:14px;">
                    <button id="classification-refresh" type="button" onclick="loadClassificationStatus()" style="padding:8px 12px;">Refresh</button>
                    <button id="classification-run" type="button" onclick="runClassification()" style="padding:8px 12px;">Run Pending Trip</button>
                  </div>
                </div>
              </div>
            </div>
            <script>
              async function loadCameraTuning() {
                const response = await fetch('/camera/tuning');
                const payload = await response.json();
                const tuning = payload.tuning;
                document.getElementById('camera-status').textContent = payload.message || '';
                document.getElementById('camera-audit').innerHTML = [
                  `Backend: ${tuning.backend ?? 'unknown'}`,
                  `Forced adjustments supported: ${tuning.forced_adjustments_supported ? 'yes' : 'no'}`,
                  `Forced adjustments active: ${tuning.forced_adjustments_active ? 'yes' : 'no'}`,
                  'Startup camera control writes: disabled',
                  'Live exposure presets: removed',
                  'Live tuning POST path: disabled'
                ].map((line) => `<div>${line}</div>`).join('');
              }
              loadCameraTuning().catch((err) => {
                document.getElementById('camera-status').textContent = String(err);
              });
              function renderPendingTrips(pendingTrips) {
                if (!pendingTrips.length) {
                  return 'Pending trips: none';
                }
                return `Pending trips: ${pendingTrips.map((trip) => `${trip.trip_id} (${trip.pending_groups} groups)`).join(', ')}`;
              }
              async function loadClassificationStatus() {
                const response = await fetch('/classification/status');
                const payload = await response.json();
                const running = payload.running ? 'yes' : 'no';
                const trip = payload.current_trip_id ?? payload.last_completed_trip_id ?? 'none';
                const stage = payload.current_stage ?? payload.state ?? 'idle';
                const progress = payload.total_groups ? `${payload.processed_groups}/${payload.total_groups} (${payload.progress_pct}%)` : 'n/a';
                document.getElementById('classification-status').textContent = payload.last_error || `State: ${payload.state}`;
                document.getElementById('classification-audit').innerHTML = [
                  `Running: ${running}`,
                  `Trip: ${trip}`,
                  `Stage: ${stage}`,
                  `Progress: ${progress}`,
                  `Last completed at: ${payload.last_completed_at ?? 'n/a'}`,
                  renderPendingTrips(payload.pending_trips || []),
                ].map((line) => `<div>${line}</div>`).join('');
                const runButton = document.getElementById('classification-run');
                runButton.disabled = payload.running || !(payload.launchable || (payload.pending_trips || []).length);
              }
              async function runClassification() {
                const response = await fetch('/classification/run', {method: 'POST'});
                const payload = await response.json();
                document.getElementById('classification-status').textContent = payload.message || `Queued ${payload.trip_id ?? ''}`.trim();
                await loadClassificationStatus();
              }
              loadClassificationStatus().catch((err) => {
                document.getElementById('classification-status').textContent = String(err);
              });
              setInterval(() => {
                loadClassificationStatus().catch(() => {});
              }, 3000);
            </script>
          </body>
        </html>
        """

    @app.get("/preview.mjpg")
    def preview_mjpg(
        fps: float | None = None,
        jpeg_quality: int | None = None,
        max_width: int | None = None,
        max_frames: int | None = None,
    ):
        target_fps = fps if fps is not None else runtime.config.api.preview_fps
        target_quality = jpeg_quality if jpeg_quality is not None else runtime.config.api.preview_jpeg_quality
        target_width = max_width if max_width is not None else runtime.config.api.preview_max_width
        frame_interval_seconds = 1.0 / max(target_fps, 0.2)
        quality = max(30, min(target_quality, 95))
        return StreamingResponse(
            preview_stream(frame_interval_seconds, quality, max_frames, target_width),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    @app.get("/preview.jpg")
    def preview_jpg(
        jpeg_quality: int | None = None,
        max_width: int | None = None,
    ):
        packet = runtime.capture_service.latest_frame()
        if packet is None:
            raise HTTPException(status_code=503, detail="preview frame unavailable")
        target_quality = jpeg_quality if jpeg_quality is not None else runtime.config.api.preview_jpeg_quality
        target_width = max_width if max_width is not None else runtime.config.api.preview_max_width
        encoded = encode_preview_jpeg(packet.frame, target_quality, target_width)
        if encoded is None:
            raise HTTPException(status_code=500, detail="preview encoding failed")
        return Response(content=encoded, media_type="image/jpeg")

    @app.get("/uploads/status")
    def uploads_status():
        return runtime.sync_service.status()

    @app.post("/sync/force")
    def sync_force():
        return runtime.sync_service.force_sync()

    @app.post("/snapshot")
    def snapshot():
        return runtime.diagnostic_snapshot()

    @app.post("/replay/{trip_id}")
    def replay_trip(trip_id: str, export: bool = True):
        return runtime.replay_trip(trip_id, export=export)

    @app.get("/classification/status")
    def classification_status():
        return runtime.classification_status()

    @app.post("/classification/run")
    def classification_run(trip_id: str | None = None):
        return runtime.run_post_trip_classification(trip_id)

    @app.get("/config")
    def config():
        return runtime.config.model_dump()

    return app
