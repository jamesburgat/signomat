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
        self.alert_page_seconds = float(os.getenv("SIGNOMAT_LCD_ALERT_PAGE_SECONDS", "2.0"))
        self.enabled = self.driver != "off"
        self.available = False
        self.error = None
        self._lock = threading.Lock()
        self._last_refresh = 0.0
        self._steady_lines = ("", "")
        self._steady_alert = False
        self._transient_lines = None
        self._transient_alert = False
        self._transient_until = 0.0
        self._last_written = None
        self._last_alert_mode = False
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

    def _clean(self, text: str) -> str:
        cleaned = "".join(ch if 32 <= ord(ch) <= 126 else " " for ch in str(text))
        return " ".join(cleaned.split())

    def _chunks(self, text: str) -> list[str]:
        words = self._clean(text).split()
        chunks: list[str] = []
        current = ""
        for word in words:
            while len(word) > self.cols:
                if current:
                    chunks.append(current)
                    current = ""
                chunks.append(word[: self.cols])
                word = word[self.cols :]
            candidate = word if not current else f"{current} {word}"
            if len(candidate) <= self.cols:
                current = candidate
            else:
                chunks.append(current)
                current = word
        if current:
            chunks.append(current)
        return chunks or ["Check Pi"]

    def _alert_lines(self, alert: dict) -> tuple[str, str]:
        title_by_id = {
            "inference_error": "YOLO fault",
            "storage_low": "Low storage",
            "memory_low": "Low memory",
            "sync_error": "Sync error",
        }
        title = alert.get("lcd_title") or title_by_id.get(alert.get("id"), alert.get("title") or "Alert")
        line1 = self._fit(f"/!\\ {title}")
        detail = alert.get("lcd_message") or alert.get("message") or alert.get("id") or "Check Pi"
        chunks = self._chunks(detail)
        index = int(time.monotonic() // max(self.alert_page_seconds, 0.5)) % len(chunks)
        return line1, self._fit(chunks[index])

    def _set_alert_contrast(self, alert: bool) -> None:
        if not self.available or alert == self._last_alert_mode:
            return
        if hasattr(self.lcd, "backlight_enabled"):
            try:
                self.lcd.backlight_enabled = not alert
            except Exception:  # pragma: no cover
                pass
        self._last_alert_mode = alert

    def _write(self, lines, force: bool = False, alert: bool = False):
        if not self.available:
            return
        now = time.monotonic()
        if not force and (now - self._last_refresh) < self.refresh_interval:
            return
        if not force and lines == self._last_written and alert == self._last_alert_mode:
            return
        self._set_alert_contrast(alert)
        self.lcd.clear()
        self.lcd.write_string(lines[0])
        if self.rows > 1:
            self.lcd.cursor_pos = (1, 0)
            self.lcd.write_string(lines[1])
        self._last_written = lines
        self._last_refresh = now

    def _flush(self, force: bool = False):
        active_lines = self._steady_lines
        alert = self._steady_alert
        if self._transient_lines and time.monotonic() < self._transient_until and not self._steady_alert:
            active_lines = self._transient_lines
            alert = self._transient_alert
        else:
            self._transient_lines = None
            self._transient_alert = False
        self._write(active_lines, force=force, alert=alert)

    def show_message(self, line1: str = "", line2: str = "", force: bool = False, transient_seconds: float = 0, alert: bool = False):
        with self._lock:
            lines = (self._fit(line1), self._fit(line2))
            if transient_seconds > 0:
                self._transient_lines = lines
                self._transient_alert = alert
                self._transient_until = time.monotonic() + transient_seconds
            else:
                self._steady_lines = lines
                self._steady_alert = alert
            self._flush(force=force)

    def show_startup_stage(self, stage: str, detail: str = ""):
        line2 = stage if not detail else f"{stage} {detail}"
        self.show_message("Signomat", line2, force=True)

    def show_ready(self, detail: str = "Ready"):
        self.show_message("Signomat", detail, force=True)

    def show_error(self, message: str):
        self.show_message("/!\\ Alert", message, force=True, alert=True)

    def show_saved_event(self, label: str):
        self.show_message("Sign saved", label, transient_seconds=2, force=True)

    def show_classified_event(self, label: str):
        self.show_message("Classified sign", label, transient_seconds=2, force=True)

    def _status_flag(self, prefix: str, active: bool) -> str:
        return f"{prefix}{'+' if active else '-'}"

    def update_runtime(
        self,
        gps_health: str,
        speed_mps: float | None,
        event_count: int,
        last_label: str | None,
        trip_active: bool,
        recording_active: bool,
        inference_active: bool,
        ble_connected: bool,
        wifi_connected: bool,
        sync_status: str,
        alert: dict | None = None,
    ):
        if alert:
            line1, line2 = self._alert_lines(alert)
            self.show_message(line1, line2, alert=True)
            return
        speed_mph = None if speed_mps is None else speed_mps * 2.23694
        line1 = f"{self._status_flag('P', ble_connected)} {self._status_flag('W', wifi_connected)} "
        if gps_health in {"fix", "mock"}:
            speed_text = "GPS ok" if speed_mph is None else f"{int(round(speed_mph)):>3}mph"
        elif gps_health == "no_fix":
            speed_text = "GPS seek"
        elif gps_health == "error":
            speed_text = "GPS err"
        elif gps_health == "unavailable":
            speed_text = "GPS off"
        else:
            speed_text = "GPS idle"
        line1 = f"{line1}{speed_text}"
        if trip_active:
            line2 = f"Signs {event_count:03d}"
        elif sync_status not in {"idle", "ok", "success", "synced"}:
            line2 = f"Sync {sync_status}"
        elif inference_active:
            line2 = "Ready"
        else:
            line2 = "Detection off"
        self.show_message(line1, line2)

    def close(self):
        if not self.available:
            return
        try:
            self.show_message("Signomat", "Stopping...", force=True)
            self.lcd.close(clear=True)
        except Exception:  # pragma: no cover
            pass
