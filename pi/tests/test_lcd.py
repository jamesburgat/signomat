from signomat_pi.common import lcd as lcd_module


def test_lcd_cycles_between_activity_count_and_last_sign(monkeypatch):
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
    assert display._steady_lines[1].strip() == "Trip Rec Scan"

    monkeypatch.setattr(lcd_module.time, "monotonic", lambda: 3.1)
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

    monkeypatch.setattr(lcd_module.time, "monotonic", lambda: 6.1)
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
    assert display._steady_lines[1].strip() == "Last yield"


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
