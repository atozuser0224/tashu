from __future__ import annotations

from dataclasses import dataclass

from app.models import Location


@dataclass(frozen=True)
class TravelNode:
    node_id: str
    location: Location


@dataclass(frozen=True)
class TravelMetric:
    distance_meters: int
    duration_seconds: int


@dataclass
class TravelTimeMatrix:
    metrics: dict[tuple[str, str], TravelMetric]
    source: str

    def get(self, origin_id: str, destination_id: str) -> TravelMetric | None:
        if origin_id == destination_id:
            return TravelMetric(distance_meters=0, duration_seconds=0)
        return self.metrics.get((origin_id, destination_id))


def driver_node_id(driver_id: str) -> str:
    return f"driver:{driver_id}"


def station_node_id(station_id: str) -> str:
    return f"station:{station_id}"

