from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Checkpoint:
    lat: float
    lon: float
    miles_along: float
    eta: datetime
    wind_mph: float | None = None
    rain_in_hr: float | None = None
    snow_in_hr: float | None = None
    wind_risk: str | None = None
    wind_risk_before_load: str | None = None
    rain_risk: str | None = None
    snow_risk: str | None = None
    risk: str | None = None
    covers_miles: float = 0.0


@dataclass
class Segment:
    risk: str | None
    miles: float
    coordinates: list[tuple[float, float]]


@dataclass
class RawRoute:
    coords: list[tuple[float, float]]
    distance_miles: float
    duration_seconds: float


@dataclass
class ScoredRoute:
    coords: list[tuple[float, float]]
    distance_miles: float
    duration_seconds: float
    duration_label: str
    checkpoints: list[Checkpoint]
    segments: list[Segment]
    risk_miles: dict[str, float]
    average_risk: float | None
    mid_lat: float
    label: str = ""
    route_id: str = ""
    recommended: bool = False
    cumulative: list[float] = field(default_factory=list)
