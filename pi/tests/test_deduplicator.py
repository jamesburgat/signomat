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

