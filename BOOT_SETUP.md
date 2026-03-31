# Signomat Boot Setup

This is the supported boot path for the packaged Pi runtime.

## Install on the Pi

Run:

```bash
cd /home/jamesburgat/signomat
./scripts/bootstrap_pi.sh
sudo bash install_signomat_service.sh
```

This installs `signomat.service` for the packaged runtime and keeps using
`/etc/default/signomat` for camera overrides.

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
