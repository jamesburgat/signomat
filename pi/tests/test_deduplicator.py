from datetime import UTC, datetime, timedelta

from signomat_pi.inference_service.pipeline import Deduplicator


def test_deduplicator_suppresses_nearby_same_label():
    deduper = Deduplicator(window_seconds=4.0, iou_threshold=0.2)
    now = datetime.now(UTC)

    accepted, first_event_id = deduper.accept_or_suppress("stop", (10, 10, 60, 60), now)
    assert accepted is True
    assert first_event_id.startswith("event_")

    accepted, same_ref = deduper.accept_or_suppress("stop", (12, 12, 62, 62), now + timedelta(seconds=1))
    assert accepted is False
    assert same_ref == first_event_id

    accepted, second_event_id = deduper.accept_or_suppress("yield", (12, 12, 62, 62), now + timedelta(seconds=1))
    assert accepted is True
    assert second_event_id != first_event_id


def test_deduplicator_tracks_same_sign_as_bbox_moves():
    deduper = Deduplicator(window_seconds=4.0, iou_threshold=0.2)
    now = datetime.now(UTC)

    accepted, first_event_id = deduper.accept_or_suppress("stop", (10, 10, 50, 50), now)
    assert accepted is True

    accepted, second_ref = deduper.accept_or_suppress("stop", (25, 10, 65, 50), now + timedelta(milliseconds=500))
    assert accepted is False
    assert second_ref == first_event_id

    accepted, third_ref = deduper.accept_or_suppress("stop", (40, 10, 80, 50), now + timedelta(seconds=1))
    assert accepted is False
    assert third_ref == first_event_id


def test_deduplicator_suppresses_same_sign_when_box_drifts_without_overlap():
    deduper = Deduplicator(window_seconds=4.0, iou_threshold=0.2)
    now = datetime.now(UTC)

    accepted, first_event_id = deduper.accept_or_suppress("speed_limit", (10, 10, 50, 50), now)
    assert accepted is True

    accepted, same_ref = deduper.accept_or_suppress("speed_limit", (45, 12, 85, 52), now + timedelta(seconds=1))
    assert accepted is False
    assert same_ref == first_event_id


def test_deduplicator_keeps_distant_same_label_signs():
    deduper = Deduplicator(window_seconds=4.0, iou_threshold=0.2)
    now = datetime.now(UTC)

    accepted, first_event_id = deduper.accept_or_suppress("warning_general", (10, 10, 50, 50), now)
    assert accepted is True

    accepted, second_event_id = deduper.accept_or_suppress("warning_general", (110, 10, 150, 50), now + timedelta(seconds=1))
    assert accepted is True
    assert second_event_id != first_event_id
