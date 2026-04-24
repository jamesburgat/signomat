from signomat_pi.ble_control_service.protocol import detection_summary_payload, device_status_payload


def test_device_status_includes_primary_alert():
    payload = device_status_payload(
        {
            "ble_connected": True,
            "inference_active": True,
            "sync_status": "idle",
            "pi_temperature_c": 42.0,
            "preview_base_url": "http://cornichon.local:8080",
            "preview_fallback_base_url": "http://10.1.76.38:8080",
            "primary_alert": {
                "id": "memory_low",
                "level": "warning",
                "symbol": "!",
                "title": "Memory low",
                "message": "400 MB available",
            },
        }
    )

    assert payload["alert"]["id"] == "memory_low"
    assert payload["alert"]["title"] == "Memory low"
    assert payload["preview_base_url"] == "http://cornichon.local:8080"
    assert payload["preview_fallback_base_url"] == "http://10.1.76.38:8080"


def test_detection_summary_includes_recent_classified_signs():
    payload = detection_summary_payload(
        {
            "detection_count_trip": 3,
            "last_detection_label": "stop",
            "last_detection_timestamp": "2026-04-13T12:00:00Z",
            "trip_sign_categories": [{"category_label": "stop", "count": 2}],
            "trip_recent_signs": [
                {
                    "event_id": "det_1",
                    "category_label": "stop",
                    "specific_label": "regulatory_stop_g1",
                    "timestamp_utc": "2026-04-13T12:00:00Z",
                    "classifier_confidence": 0.93,
                }
            ],
        }
    )

    assert payload["det"] == 3
    assert payload["cats"] == {"stop": 2}
    assert payload["recent"] == [
        {
            "id": "det_1",
            "label": "regulatory_stop_g1",
            "category": "stop",
            "ts": "2026-04-13T12:00:00Z",
            "conf": 0.93,
        }
    ]
