from signomat_pi.ble_control_service.protocol import detection_summary_payload


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
