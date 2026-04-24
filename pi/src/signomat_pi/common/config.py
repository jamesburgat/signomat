from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class AppSection(BaseModel):
    device_name: str = "signomat-pi"
    base_data_dir: str = "/data/signomat"
    log_level: str = "INFO"
    wifi_interface: str = "wlan0"
    low_memory_warn_mb: int = 512


class CameraSection(BaseModel):
    backend: str = "auto"
    device: str | None = None
    index: int | None = None
    fourcc: str | None = None
    width: int = 1280
    height: int = 720
    fps: int = 20
    rotation: int = 0
    codec: str = "mp4v"
    warmup_seconds: float = 1.0
    chunk_seconds: int = 60
    annotate_recording: bool = True
    overlay_hold_seconds: float = 2.5
    retention_days: int = 14
    low_storage_stop_mb: int = 2048
    auto_exposure: bool = True
    exposure_compensation: float = 0.0
    brightness: float = 0.0
    contrast: float = 1.0
    exposure_time_us: int | None = None
    analogue_gain: float | None = None


class GPSSection(BaseModel):
    provider: str = "auto"
    sample_interval_seconds: float = 1.0
    ring_buffer_size: int = 300


class PreprocessingSection(BaseModel):
    downscale_width: int = 960
    color_normalization: bool = True
    contrast_normalization: bool = True


class InferenceSection(BaseModel):
    enabled: bool = True
    interval_seconds: float = 0.35
    save_crops: bool = False
    save_unknown_signs: bool = True
    thumbnail_max_edge: int = 480
    detector_backend: str = "yolo"
    detector_model_path: str = "models/sign_detector_yolo11n_any_sign_ncnn_model"
    detector_imgsz: int = 640
    classifier_backend: str = "yolo"
    classifier_model_path: str = "models/sign_classifier_yolo11n_raw_min100_ncnn_model"
    classifier_imgsz: int = 224
    model_verbose: bool = False
    max_candidates: int = 4
    min_box_area: int = 900
    max_box_area_ratio: float = 0.12
    min_box_fill_ratio: float = 0.2
    min_detector_confidence: float = 0.6
    min_classifier_confidence: float = 0.75
    border_ignore_margin_px: int = 6
    dedupe_window_seconds: float = 6.0
    dedupe_iou_threshold: float = 0.25
    preprocessing: PreprocessingSection = Field(default_factory=PreprocessingSection)


class APISection(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080
    preview_fps: float = 5.0
    preview_jpeg_quality: int = 70
    preview_max_width: int | None = 960


class SyncSection(BaseModel):
    enabled: bool = False
    batch_size: int = 25
    base_url: str | None = None
    ingest_token: str | None = None
    device_id: str | None = None
    interval_seconds: float = 60.0
    request_timeout_seconds: float = 15.0


class BLESection(BaseModel):
    enabled: bool = False
    mode: str = "mock"
    adapter: str | None = None
    advertise_name: str | None = None
    discoverable: bool = True
    pairable: bool = False
    refresh_interval_seconds: float = 1.0


class MockSection(BaseModel):
    enabled: bool = False
    gps_seed_lat: float = 40.7128
    gps_seed_lon: float = -74.0060
    moving_speed_mps: float = 10.0
    frame_text_overlay: bool = True


class TaxonomySection(BaseModel):
    config_path: str = "pi/config/taxonomy.yaml"


class SignomatConfig(BaseModel):
    app: AppSection = Field(default_factory=AppSection)
    camera: CameraSection = Field(default_factory=CameraSection)
    gps: GPSSection = Field(default_factory=GPSSection)
    inference: InferenceSection = Field(default_factory=InferenceSection)
    api: APISection = Field(default_factory=APISection)
    sync: SyncSection = Field(default_factory=SyncSection)
    ble: BLESection = Field(default_factory=BLESection)
    mock: MockSection = Field(default_factory=MockSection)
    taxonomy: TaxonomySection = Field(default_factory=TaxonomySection)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _env_text(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _env_int(name: str) -> int | None:
    value = _env_text(name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _env_float(name: str) -> float | None:
    value = _env_text(name)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _env_bool(name: str) -> bool | None:
    value = _env_text(name)
    if value is None:
        return None
    normalized = value.lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def env_overrides() -> dict[str, Any]:
    app: dict[str, Any] = {}
    camera: dict[str, Any] = {}
    gps: dict[str, Any] = {}
    inference: dict[str, Any] = {}
    ble: dict[str, Any] = {}
    sync: dict[str, Any] = {}
    app_mapping = {
        "base_data_dir": _env_text("SIGNOMAT_BASE_DATA_DIR"),
        "log_level": _env_text("SIGNOMAT_LOG_LEVEL"),
        "wifi_interface": _env_text("SIGNOMAT_WIFI_INTERFACE"),
        "low_memory_warn_mb": _env_int("SIGNOMAT_LOW_MEMORY_WARN_MB"),
    }
    for key, value in app_mapping.items():
        if value is not None:
            app[key] = value
    mapping = {
        "backend": _env_text("SIGNOMAT_CAMERA_BACKEND"),
        "device": _env_text("SIGNOMAT_CAMERA_DEVICE"),
        "index": _env_int("SIGNOMAT_CAMERA_INDEX"),
        "fourcc": _env_text("SIGNOMAT_CAMERA_FOURCC"),
        "width": _env_int("SIGNOMAT_CAMERA_WIDTH"),
        "height": _env_int("SIGNOMAT_CAMERA_HEIGHT"),
        "fps": _env_int("SIGNOMAT_CAMERA_FPS"),
        "warmup_seconds": _env_float("SIGNOMAT_CAMERA_WARMUP_SECONDS"),
        "chunk_seconds": _env_int("SIGNOMAT_CAMERA_CHUNK_SECONDS"),
        "auto_exposure": _env_bool("SIGNOMAT_CAMERA_AUTO_EXPOSURE"),
        "exposure_compensation": _env_float("SIGNOMAT_CAMERA_EXPOSURE_COMPENSATION"),
        "brightness": _env_float("SIGNOMAT_CAMERA_BRIGHTNESS"),
        "contrast": _env_float("SIGNOMAT_CAMERA_CONTRAST"),
        "exposure_time_us": _env_int("SIGNOMAT_CAMERA_EXPOSURE_TIME_US"),
        "analogue_gain": _env_float("SIGNOMAT_CAMERA_ANALOGUE_GAIN"),
    }
    for key, value in mapping.items():
        if value is not None:
            camera[key] = value
    gps_mapping = {
        "provider": _env_text("SIGNOMAT_GPS_PROVIDER"),
    }
    for key, value in gps_mapping.items():
        if value is not None:
            gps[key] = value
    inference_mapping = {
        "detector_backend": _env_text("SIGNOMAT_DETECTOR_BACKEND"),
        "detector_model_path": _env_text("SIGNOMAT_DETECTOR_MODEL_PATH"),
        "detector_imgsz": _env_int("SIGNOMAT_DETECTOR_IMGSZ"),
        "classifier_backend": _env_text("SIGNOMAT_CLASSIFIER_BACKEND"),
        "classifier_model_path": _env_text("SIGNOMAT_CLASSIFIER_MODEL_PATH"),
        "classifier_imgsz": _env_int("SIGNOMAT_CLASSIFIER_IMGSZ"),
        "model_verbose": _env_bool("SIGNOMAT_MODEL_VERBOSE"),
        "interval_seconds": _env_float("SIGNOMAT_INFERENCE_INTERVAL_SECONDS"),
        "save_crops": _env_bool("SIGNOMAT_SAVE_CROPS"),
        "save_unknown_signs": _env_bool("SIGNOMAT_SAVE_UNKNOWN_SIGNS"),
        "min_box_area": _env_int("SIGNOMAT_MIN_BOX_AREA"),
        "min_detector_confidence": _env_float("SIGNOMAT_MIN_DETECTOR_CONFIDENCE"),
        "min_classifier_confidence": _env_float("SIGNOMAT_MIN_CLASSIFIER_CONFIDENCE"),
    }
    for key, value in inference_mapping.items():
        if value is not None:
            inference[key] = value
    ble_mapping = {
        "enabled": _env_bool("SIGNOMAT_BLE_ENABLED"),
        "mode": _env_text("SIGNOMAT_BLE_MODE"),
        "adapter": _env_text("SIGNOMAT_BLE_ADAPTER"),
        "advertise_name": _env_text("SIGNOMAT_BLE_ADVERTISE_NAME"),
        "discoverable": _env_bool("SIGNOMAT_BLE_DISCOVERABLE"),
        "pairable": _env_bool("SIGNOMAT_BLE_PAIRABLE"),
        "refresh_interval_seconds": _env_float("SIGNOMAT_BLE_REFRESH_INTERVAL_SECONDS"),
    }
    for key, value in ble_mapping.items():
        if value is not None:
            ble[key] = value
    sync_mapping = {
        "enabled": _env_bool("SIGNOMAT_SYNC_ENABLED"),
        "base_url": _env_text("SIGNOMAT_SYNC_BASE_URL"),
        "ingest_token": _env_text("SIGNOMAT_INGEST_TOKEN"),
        "device_id": _env_text("SIGNOMAT_SYNC_DEVICE_ID"),
        "interval_seconds": _env_float("SIGNOMAT_SYNC_INTERVAL_SECONDS"),
        "request_timeout_seconds": _env_float("SIGNOMAT_SYNC_REQUEST_TIMEOUT_SECONDS"),
    }
    for key, value in sync_mapping.items():
        if value is not None:
            sync[key] = value
    api: dict[str, Any] = {}
    api_mapping = {
        "preview_fps": _env_float("SIGNOMAT_PREVIEW_FPS"),
        "preview_jpeg_quality": _env_int("SIGNOMAT_PREVIEW_JPEG_QUALITY"),
        "preview_max_width": _env_int("SIGNOMAT_PREVIEW_MAX_WIDTH"),
    }
    for key, value in api_mapping.items():
        if value is not None:
            api[key] = value
    overrides: dict[str, Any] = {}
    if app:
        overrides["app"] = app
    if camera:
        overrides["camera"] = camera
    if gps:
        overrides["gps"] = gps
    if inference:
        overrides["inference"] = inference
    if ble:
        overrides["ble"] = ble
    if sync:
        overrides["sync"] = sync
    if api:
        overrides["api"] = api
    return overrides


def resolve_repo_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return repo_root() / path


def load_config(config_path: str | Path) -> SignomatConfig:
    requested = Path(config_path)
    requested = requested if requested.is_absolute() else repo_root() / requested
    default_path = repo_root() / "pi/config/default.yaml"
    merged = _deep_merge(load_yaml(default_path), load_yaml(requested))
    merged = _deep_merge(merged, env_overrides())
    return SignomatConfig.model_validate(merged)
