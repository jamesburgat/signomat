from __future__ import annotations

import os
import threading
import time


class LCDStatusDisplay:
    def __init__(self):
        self.cols = int(os.getenv("SIGNOMAT_LCD_COLS", "16"))
        self.rows = int(os.getenv("SIGNOMAT_LCD_ROWS", "2"))
        self.driver = os.getenv("SIGNOMAT_LCD_DRIVER", "i2c").strip().lower()
        self.refresh_interval = float(os.getenv("SIGNOMAT_LCD_REFRESH_SECONDS", "0.5"))
        self.enabled = self.driver != "off"
        self.available = False
        self.error = None
        self._lock = threading.Lock()
        self._last_refresh = 0.0
        self._steady_lines = ("", "")
        self._transient_lines = None
        self._transient_until = 0.0
        self._last_written = None
        self.lcd = None

        if not self.enabled:
            return

        try:
            if self.driver == "gpio":
                self.lcd = self._build_gpio_lcd()
            else:
                self.lcd = self._build_i2c_lcd()
            self.available = True
            self.show_message("Signomat", "Booting...", force=True)
        except Exception as exc:  # pragma: no cover
            self.error = str(exc)
            self.available = False

    def _build_i2c_lcd(self):
        from RPLCD.i2c import CharLCD

        port = int(os.getenv("SIGNOMAT_LCD_I2C_PORT", "1"))
        address = int(os.getenv("SIGNOMAT_LCD_I2C_ADDRESS", "0x27"), 0)
        expander = os.getenv("SIGNOMAT_LCD_I2C_EXPANDER", "PCF8574")
        return CharLCD(
            i2c_expander=expander,
            address=address,
            port=port,
            cols=self.cols,
            rows=self.rows,
            charmap="A02",
            auto_linebreaks=False,
        )

    def _build_gpio_lcd(self):
        from RPLCD.gpio import CharLCD

        rs = int(os.getenv("SIGNOMAT_LCD_PIN_RS", "26"))
        enable = int(os.getenv("SIGNOMAT_LCD_PIN_E", "19"))
        data_pins = [
            int(os.getenv("SIGNOMAT_LCD_PIN_D4", "13")),
            int(os.getenv("SIGNOMAT_LCD_PIN_D5", "6")),
            int(os.getenv("SIGNOMAT_LCD_PIN_D6", "5")),
            int(os.getenv("SIGNOMAT_LCD_PIN_D7", "11")),
        ]
        pin_rw = os.getenv("SIGNOMAT_LCD_PIN_RW")
        kwargs = {
            "numbering_mode": "BCM",
            "pin_rs": rs,
            "pin_e": enable,
            "pins_data": data_pins,
            "cols": self.cols,
            "rows": self.rows,
            "charmap": "A02",
            "auto_linebreaks": False,
        }
        if pin_rw:
            kwargs["pin_rw"] = int(pin_rw)
        return CharLCD(**kwargs)

    def _fit(self, text: str) -> str:
        cleaned = "".join(ch if 32 <= ord(ch) <= 126 else " " for ch in str(text))
        return cleaned[: self.cols].ljust(self.cols)

    def _write(self, lines, force: bool = False):
        if not self.available:
            return
        now = time.monotonic()
        if not force and (now - self._last_refresh) < self.refresh_interval:
            return
        if not force and lines == self._last_written:
            return
        self.lcd.clear()
        self.lcd.write_string(lines[0])
        if self.rows > 1:
            self.lcd.cursor_pos = (1, 0)
            self.lcd.write_string(lines[1])
        self._last_written = lines
        self._last_refresh = now

    def _flush(self, force: bool = False):
        active_lines = self._steady_lines
        if self._transient_lines and time.monotonic() < self._transient_until:
            active_lines = self._transient_lines
        else:
            self._transient_lines = None
        self._write(active_lines, force=force)

    def show_message(self, line1: str = "", line2: str = "", force: bool = False, transient_seconds: float = 0):
        with self._lock:
            lines = (self._fit(line1), self._fit(line2))
            if transient_seconds > 0:
                self._transient_lines = lines
                self._transient_until = time.monotonic() + transient_seconds
            else:
                self._steady_lines = lines
            self._flush(force=force)

    def show_startup_stage(self, stage: str, detail: str = ""):
        line2 = stage if not detail else f"{stage} {detail}"
        self.show_message("Signomat", line2, force=True)

    def show_ready(self, detail: str = "Ready"):
        self.show_message("Signomat", detail, force=True)

    def show_error(self, message: str):
        self.show_message("Signomat", message, force=True)

    def show_saved_event(self, label: str):
        self.show_message("Event saved", label, transient_seconds=2, force=True)

    def update_runtime(
        self,
        gps_health: str,
        speed_mps: float | None,
        event_count: int,
        best_label: str | None,
        trip_active: bool,
        recording_active: bool,
        inference_active: bool,
    ):
        gps_text = "GPS" if gps_health in {"fix", "mock"} else "NO GPS"
        speed_mph = None if speed_mps is None else speed_mps * 2.23694
        line1 = gps_text if speed_mph is None else f"{gps_text} {speed_mph:>4.1f}mph"

        if event_count and best_label:
            line2 = f"{event_count} {best_label}"
        elif trip_active and recording_active and inference_active:
            line2 = "Recording+AI"
        elif trip_active and recording_active:
            line2 = "Recording"
        elif trip_active:
            line2 = "Trip active"
        else:
            line2 = "Idle"
        self.show_message(line1, line2)

    def close(self):
        if not self.available:
            return
        try:
            self.show_message("Signomat", "Stopping...", force=True)
            self.lcd.close(clear=True)
        except Exception:  # pragma: no cover
            pass
