from __future__ import annotations

import time
from pathlib import Path

import cv2
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse


def create_app(runtime) -> FastAPI:
    app = FastAPI(title="Signomat Local API", version="0.1.0")

    def preview_stream(frame_interval_seconds: float, jpeg_quality: int, max_frames: int | None):
        emitted = 0
        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality]
        while True:
            if max_frames is not None and emitted >= max_frames:
                return
            packet = runtime.capture_service.latest_frame()
            if packet is None:
                time.sleep(frame_interval_seconds)
                continue
            ok, encoded = cv2.imencode(".jpg", packet.frame, encode_params)
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
        cards: list[str] = []
        for segment in segments:
            size_mb = (segment.get("file_size") or 0) / 1024 / 1024
            duration = segment.get("duration_sec") or 0
            cards.append(
                (
                    "<article style=\"margin-bottom:28px;padding:16px;border:1px solid #ddd;border-radius:12px;\">"
                    f"<h3 style=\"margin-top:0;\">{segment['video_segment_id']}</h3>"
                    f"<div style=\"margin-bottom:8px;color:#666;\">Start: {segment.get('start_timestamp_utc')} | "
                    f"Duration: {duration:.1f}s | Size: {size_mb:.1f} MB</div>"
                    f"<video controls preload=\"metadata\" style=\"width:100%;max-width:960px;background:#000;\" src=\"/recordings/video/{segment['video_segment_id']}\"></video>"
                    f"<div style=\"margin-top:8px;\"><a href=\"/recordings/video/{segment['video_segment_id']}\">Open video file</a></div>"
                    "</article>"
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
            + "".join(cards)
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
            <img src="/preview.mjpg" style="display:block;max-width:100vw;height:auto;" />
          </body>
        </html>
        """

    @app.get("/preview.mjpg")
    def preview_mjpg(
        fps: float = 5.0,
        jpeg_quality: int = 80,
        max_frames: int | None = None,
    ):
        frame_interval_seconds = 1.0 / max(fps, 0.2)
        quality = max(30, min(jpeg_quality, 95))
        return StreamingResponse(
            preview_stream(frame_interval_seconds, quality, max_frames),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    @app.get("/uploads/status")
    def uploads_status():
        return runtime.sync_service.status()

    @app.post("/sync/force")
    def sync_force():
        return runtime.sync_service.force_sync()

    @app.post("/snapshot")
    def snapshot():
        return runtime.diagnostic_snapshot()

    @app.get("/config")
    def config():
        return runtime.config.model_dump()

    return app
