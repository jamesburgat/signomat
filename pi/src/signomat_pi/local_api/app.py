from __future__ import annotations

import time

import cv2
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse


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
