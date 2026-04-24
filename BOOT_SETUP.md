# Signomat Boot Setup

This is the supported boot path for the packaged Pi runtime.

## Install on the Pi

Run:

```bash
cd /home/jamesburgat/signomat
./scripts/bootstrap_pi.sh
. .venv/bin/activate
pip install -e ".[ml]"
sudo bash install_signomat_service.sh
```

This installs `signomat.service` for the packaged runtime and keeps using
`/etc/default/signomat` for camera overrides.

The `ml` extra installs the optional Ultralytics/NCNN runtime used by the
learned detector and classifier. The default Pi runtime expects those learned
models to load; use `pi/config/mock.yaml` when you intentionally want the
mock detector/classifier dev path.

The installer also creates the runtime data directory. By default that is
`/data/signomat`. If you prefer a user-writable path, set
`SIGNOMAT_BASE_DATA_DIR` in `/etc/default/signomat` before rerunning the
installer, for example:

```bash
SIGNOMAT_BASE_DATA_DIR=/home/jamesburgat/signomat-data
```

## What it does

- Starts the packaged `signomat_pi` runtime at boot
- Restarts it if it crashes
- Does not wait for Wi-Fi because capture is offline-first
- Preserves the camera backend/device tuning from the legacy setup

## Useful commands

Check service status:

```bash
systemctl status signomat.service --no-pager
```

Restart manually:

```bash
sudo systemctl restart signomat.service
```

View logs:

```bash
journalctl -u signomat.service -n 100 --no-pager
```

Check GPS detection and fix state:

```bash
/home/jamesburgat/signomat/.venv/bin/python -m signomat_pi.cli.main --config /home/jamesburgat/signomat/pi/config/default.yaml gps-diagnose
```

Disable at boot:

```bash
sudo systemctl disable --now signomat.service
```

## Camera configuration

Edit `/etc/default/signomat` to match the connected camera, then restart the
service.

For a USB/UVC camera:

```bash
sudoedit /etc/default/signomat
```

Set:

```bash
SIGNOMAT_CAMERA_BACKEND=opencv
SIGNOMAT_CAMERA_DEVICE=/dev/video0
SIGNOMAT_CAMERA_FOURCC=MJPG
SIGNOMAT_CAMERA_WIDTH=1280
SIGNOMAT_CAMERA_HEIGHT=720
```

For a Pi camera module:

```bash
SIGNOMAT_CAMERA_BACKEND=picamera2
SIGNOMAT_CAMERA_INDEX=0
```

You can also leave `SIGNOMAT_CAMERA_BACKEND=auto` to prefer `Picamera2` when a
Pi camera is detected and fall back to OpenCV otherwise.

If the live image is too dark, start with modest exposure tuning in
`/etc/default/signomat`, then restart the service:

```bash
SIGNOMAT_CAMERA_AUTO_EXPOSURE=true
SIGNOMAT_CAMERA_EXPOSURE_COMPENSATION=0.8
SIGNOMAT_CAMERA_BRIGHTNESS=0.1
SIGNOMAT_CAMERA_CONTRAST=1.1
```

## Learned Model Configuration

The default config uses the tracked NCNN exports:

```bash
SIGNOMAT_DETECTOR_BACKEND=yolo
SIGNOMAT_DETECTOR_MODEL_PATH=models/sign_detector_yolo11n_any_sign_ncnn_model
SIGNOMAT_CLASSIFIER_BACKEND=yolo
SIGNOMAT_CLASSIFIER_MODEL_PATH=models/sign_classifier_yolo11n_raw_min100_ncnn_model
SIGNOMAT_SAVE_CROPS=false
SIGNOMAT_SAVE_UNKNOWN_SIGNS=true
SIGNOMAT_LOW_MEMORY_WARN_MB=512
SIGNOMAT_MIN_BOX_AREA=900
SIGNOMAT_MIN_DETECTOR_CONFIDENCE=0.6
SIGNOMAT_MIN_CLASSIFIER_CONFIDENCE=0.75
```

If the classifier uses too much memory on the Pi, keep the learned detector and
disable classification temporarily:

```bash
SIGNOMAT_CLASSIFIER_BACKEND=none
```
