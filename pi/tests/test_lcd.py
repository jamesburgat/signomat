from signomat_pi.common import lcd as lcd_module


def test_lcd_shows_stable_trip_count(monkeypatch):
    monkeypatch.setenv("SIGNOMAT_LCD_DRIVER", "off")
    display = lcd_module.LCDStatusDisplay()

    monkeypatch.setattr(lcd_module.time, "monotonic", lambda: 0.0)
    display.update_runtime(
        gps_health="fix",
        speed_mps=13.4,
        event_count=4,
        last_label="yield",
        trip_active=True,
        recording_active=True,
        inference_active=True,
        ble_connected=True,
        wifi_connected=False,
        sync_status="idle",
    )
    assert display._steady_lines[1].strip() == "Signs 004"


def test_lcd_flashes_classified_sign(monkeypatch):
    monkeypatch.setenv("SIGNOMAT_LCD_DRIVER", "off")
    display = lcd_module.LCDStatusDisplay()

    monkeypatch.setattr(lcd_module.time, "monotonic", lambda: 0.0)
    display.show_classified_event("stop")

    assert display._transient_lines[0].strip() == "Classified sign"
    assert display._transient_lines[1].strip() == "stop"


def test_lcd_shows_phone_wifi_and_gps_feedback(monkeypatch):
    monkeypatch.setenv("SIGNOMAT_LCD_DRIVER", "off")
    display = lcd_module.LCDStatusDisplay()

    monkeypatch.setattr(lcd_module.time, "monotonic", lambda: 0.0)
    display.update_runtime(
        gps_health="no_fix",
        speed_mps=None,
        event_count=0,
        last_label=None,
        trip_active=False,
        recording_active=False,
        inference_active=True,
        ble_connected=False,
        wifi_connected=True,
        sync_status="idle",
    )

    assert display._steady_lines[0].strip() == "P- W+ GPS seek"
    assert display._steady_lines[1].strip() == "Ready"


def test_lcd_shows_alert_with_alert_mode(monkeypatch):
    monkeypatch.setenv("SIGNOMAT_LCD_DRIVER", "off")
    display = lcd_module.LCDStatusDisplay()

    monkeypatch.setattr(lcd_module.time, "monotonic", lambda: 0.0)
    display.update_runtime(
        gps_health="fix",
        speed_mps=None,
        event_count=0,
        last_label=None,
        trip_active=False,
        recording_active=False,
        inference_active=True,
        ble_connected=False,
        wifi_connected=False,
        sync_status="idle",
        alert={"id": "memory_low", "title": "Memory low", "message": "400 MB available"},
    )

    assert display._steady_lines[0].strip() == "/!\\ Low memory"
    assert display._steady_lines[1].strip() == "400 MB available"
    assert display._steady_alert is True


def test_lcd_alert_details_rotate_without_truncating_everything(monkeypatch):
    monkeypatch.setenv("SIGNOMAT_LCD_DRIVER", "off")
    display = lcd_module.LCDStatusDisplay()

    current_time = {"value": 0.0}
    monkeypatch.setattr(lcd_module.time, "monotonic", lambda: current_time["value"])

    alert = {
        "id": "inference_error",
        "title": "YOLO fault",
        "message": "model path missing at /home/pi/models/detector/model.ncnn.param",
        "lcd_message": "Model error: model path missing at /home/pi/models/detector/model.ncnn.param",
    }
    display.update_runtime(
        gps_health="fix",
        speed_mps=None,
        event_count=0,
        last_label=None,
        trip_active=False,
        recording_active=False,
        inference_active=True,
        ble_connected=False,
        wifi_connected=False,
        sync_status="idle",
        alert=alert,
    )
    first_page = display._steady_lines[1].strip()

    current_time["value"] = display.alert_page_seconds
    display.update_runtime(
        gps_health="fix",
        speed_mps=None,
        event_count=0,
        last_label=None,
        trip_active=False,
        recording_active=False,
        inference_active=True,
        ble_connected=False,
        wifi_connected=False,
        sync_status="idle",
        alert=alert,
    )

    assert display._steady_lines[0].strip() == "/!\\ YOLO fault"
    assert first_page == "Model error:"
    assert display._steady_lines[1].strip() == "model path"
