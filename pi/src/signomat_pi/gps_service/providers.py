from __future__ import annotations

import logging
from dataclasses import dataclass

from signomat_pi.common.models import GPSPoint
from signomat_pi.common.utils import utc_now_text

try:
    import gpsd
except ImportError:  # pragma: no cover
    gpsd = None


LOGGER = logging.getLogger(__name__)


class GPSProvider:
    def read(self) -> GPSPoint:  # pragma: no cover
        raise NotImplementedError


class NullGPSProvider(GPSProvider):
    def read(self) -> GPSPoint:
        return GPSPoint(
            timestamp_utc=utc_now_text(),
            lat=None,
            lon=None,
            speed=None,
            heading=None,
            altitude=None,
            fix_quality="unavailable",
            source="none",
        )


@dataclass
class MockGPSProvider(GPSProvider):
    seed_lat: float
    seed_lon: float
    speed_mps: float

    def __post_init__(self) -> None:
        self.index = 0

    def read(self) -> GPSPoint:
        self.index += 1
        lat = self.seed_lat + self.index * 0.00005
        lon = self.seed_lon + self.index * 0.00007
        return GPSPoint(
            timestamp_utc=utc_now_text(),
            lat=lat,
            lon=lon,
            speed=self.speed_mps,
            heading=90.0,
            altitude=12.0,
            fix_quality="fix",
            source="mock",
        )


class GPSDProvider(GPSProvider):
    def __init__(self) -> None:
        if gpsd is None:
            raise RuntimeError("gpsd package is not installed")
        gpsd.connect()

    def read(self) -> GPSPoint:
        packet = gpsd.get_current()
        mode = getattr(packet, "mode", 0)
        return GPSPoint(
            timestamp_utc=utc_now_text(),
            lat=getattr(packet, "lat", None),
            lon=getattr(packet, "lon", None),
            speed=getattr(packet, "hspeed", None),
            heading=getattr(packet, "track", None),
            altitude=getattr(packet, "alt", None),
            fix_quality="fix" if mode and mode >= 2 else "no_fix",
            source="gpsd",
        )


def create_gps_provider(config) -> GPSProvider:
    provider = config.gps.provider.lower()
    if config.mock.enabled or provider == "mock":
        return MockGPSProvider(
            seed_lat=config.mock.gps_seed_lat,
            seed_lon=config.mock.gps_seed_lon,
            speed_mps=config.mock.moving_speed_mps,
        )
    if provider == "none":
        return NullGPSProvider()
    if gpsd is None:
        LOGGER.warning("gpsd package is not installed; using unavailable GPS provider")
        return NullGPSProvider()
    return GPSDProvider()
