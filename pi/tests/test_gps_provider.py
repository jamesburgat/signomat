from types import SimpleNamespace

from signomat_pi.gps_service import providers


def test_gpsd_provider_omits_coordinates_without_fix(monkeypatch):
    monkeypatch.setattr(providers, "gpsd", SimpleNamespace(connect=lambda: None, get_current=lambda: SimpleNamespace(mode=1, lat=0.0, lon=0.0, hspeed=0.0, track=0.0, alt=0.0)))

    provider = providers.GPSDProvider()
    point = provider.read()

    assert point.fix_quality == "no_fix"
    assert point.lat is None
    assert point.lon is None
    assert point.speed is None
    assert point.heading is None
    assert point.altitude is None


def test_gpsd_provider_reconnects_when_watch_goes_inactive(monkeypatch):
    calls = {"connect": 0, "read": 0}

    def connect():
        calls["connect"] += 1

    def get_current():
        calls["read"] += 1
        if calls["read"] == 1:
            raise UserWarning("GPS not active")
        return SimpleNamespace(mode=1, lat=0.0, lon=0.0, hspeed=0.0, track=0.0, alt=0.0)

    monkeypatch.setattr(providers, "gpsd", SimpleNamespace(connect=connect, get_current=get_current))

    provider = providers.GPSDProvider()
    point = provider.read()

    assert calls["connect"] == 2
    assert point.fix_quality == "no_fix"
    assert point.lat is None
