from __future__ import annotations

from datetime import datetime, timedelta, timezone

from planner.services.errors import PlanError
from planner.services.geo import haversine_miles, point_at
from planner.services.models import ScoredRoute
from planner.services.providers import driving_routes, fetch_hourly, round_key
from planner.services.risk import (
    LEVELS,
    classify_conditions,
    deciding_factor,
    recommendation_text,
    risk_index,
    sort_key,
)
from planner.services.sampling import (
    build_segments,
    corridor_points,
    sample_checkpoints,
    summarize,
)


def plan_trip(
    origin: dict,
    destination: dict,
    departure: datetime,
    load_lb: float,
    sample_miles: int,
) -> dict:
    _validate(origin, destination, departure, load_lb, sample_miles)
    raw_routes, notes = driving_routes(
        (origin["lat"], origin["lon"]),
        (destination["lat"], destination["lon"]),
    )

    prepared = []
    for raw in raw_routes:
        checkpoints, cumulative, scale = sample_checkpoints(
            raw.coords,
            raw.distance_miles,
            raw.duration_seconds,
            departure,
            sample_miles,
        )
        prepared.append((raw, checkpoints, cumulative, scale))

    grid = corridor_points([(route.coords, cumulative) for route, _, cumulative, _ in prepared])
    weather_points = [(cp.lat, cp.lon) for _, checkpoints, _, _ in prepared for cp in checkpoints]
    weather_points.extend(grid)
    forecasts = fetch_hourly(weather_points, departure)

    scored: list[ScoredRoute] = []
    for raw, checkpoints, cumulative, scale in prepared:
        for checkpoint in checkpoints:
            _apply_weather(checkpoint, forecasts, load_lb)
        segments = build_segments(raw.coords, cumulative, checkpoints, scale)
        buckets, average = summarize(segments)
        mid_lat = point_at(raw.coords, cumulative, cumulative[-1] * 0.5)[0]
        scored.append(
            ScoredRoute(
                coords=raw.coords,
                distance_miles=raw.distance_miles,
                duration_seconds=raw.duration_seconds,
                duration_label=format_duration(raw.duration_seconds),
                checkpoints=checkpoints,
                segments=segments,
                risk_miles=buckets,
                average_risk=average,
                mid_lat=mid_lat,
                cumulative=cumulative,
            )
        )

    if any(route.risk_miles["unknown"] > 1 for route in scored):
        notes.append("Some miles fall outside the published forecast and were left unscored.")

    _assign_labels(scored)
    scored.sort(key=sort_key)
    for index, route in enumerate(scored, start=1):
        route.route_id = f"route-{index}"
        route.recommended = index == 1
    factor = deciding_factor(scored)
    forecast_times = _forecast_times(departure)

    return {
        "origin": origin,
        "destination": destination,
        "departure": _iso(departure),
        "load_weight_lb": round(load_lb, 1),
        "sample_miles": sample_miles,
        "recommended_route_id": scored[0].route_id,
        "deciding_factor": factor,
        "recommendation": recommendation_text(scored, factor),
        "notes": notes,
        "forecast_times": [_iso(stamp) for stamp in forecast_times],
        "routes": [_route_payload(route) for route in scored],
        "heatmap": {
            "points": [
                {
                    "lat": round(lat, 4),
                    "lon": round(lon, 4),
                    "risks": _hour_risks(forecasts, lat, lon, forecast_times, load_lb),
                }
                for lat, lon in grid
            ]
        },
    }


def _validate(origin, destination, departure, load_lb, sample_miles):
    if sample_miles not in (10, 25, 50):
        raise PlanError("Sample interval must be 10, 25, or 50 miles.")
    if load_lb <= 0 or load_lb > 120000:
        raise PlanError("Load weight must be between 1 and 120,000 lb.")
    now = datetime.now(timezone.utc)
    if departure < now - timedelta(hours=6):
        raise PlanError("Departure is too far in the past for the forecast.")
    if departure > now + timedelta(days=5):
        raise PlanError("Departure must be within the next 5 days so the 48-hour forecast still covers the trip.")
    gap = haversine_miles(origin["lat"], origin["lon"], destination["lat"], destination["lon"])
    if gap < 1:
        raise PlanError("Choose a destination at least a mile from the origin.")


def _apply_weather(checkpoint, forecasts, load_lb: float) -> None:
    series = forecasts.get(round_key(checkpoint.lat, checkpoint.lon))
    if not series:
        return
    hour = checkpoint.eta.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    sample = series.get(hour)
    if sample is None:
        return
    wind, rain, snow = sample
    checkpoint.wind_mph = wind
    checkpoint.rain_in_hr = rain
    checkpoint.snow_in_hr = snow
    classified = classify_conditions(wind, rain, snow, load_lb)
    checkpoint.wind_risk = classified["wind_risk"]
    checkpoint.wind_risk_before_load = classified["wind_risk_before_load"]
    checkpoint.rain_risk = classified["rain_risk"]
    checkpoint.snow_risk = classified["snow_risk"]
    checkpoint.risk = classified["risk"]


def _hour_risks(forecasts, lat, lon, times, load_lb) -> list[int | None]:
    series = forecasts.get(round_key(lat, lon)) or {}
    risks = []
    for stamp in times:
        sample = series.get(stamp)
        if sample is None:
            risks.append(None)
            continue
        wind, rain, snow = sample
        level = classify_conditions(wind, rain, snow, load_lb)["risk"]
        risks.append(risk_index(level))
    return risks


def _forecast_times(departure: datetime) -> list[datetime]:
    base = departure.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return [base + timedelta(hours=hour) for hour in range(49)]


def _assign_labels(routes: list[ScoredRoute]) -> None:
    fastest = min(routes, key=lambda route: route.duration_seconds)
    bases = []
    for route in routes:
        if route is fastest:
            base = "Fastest"
        elif route.mid_lat > fastest.mid_lat + 0.35:
            base = "Northern"
        elif route.mid_lat < fastest.mid_lat - 0.35:
            base = "Southern"
        else:
            base = "Alternate"
        bases.append(base)
    counts: dict[str, int] = {}
    for base in bases:
        counts[base] = counts.get(base, 0) + 1
    seen: dict[str, int] = {}
    for route, base in zip(routes, bases):
        if counts[base] == 1:
            route.label = base
            continue
        seen[base] = seen.get(base, 0) + 1
        route.label = f"{base} {seen[base]}"


def _route_payload(route: ScoredRoute) -> dict:
    worst = _worst_checkpoint(route.checkpoints)
    arrival = route.checkpoints[-1].eta if route.checkpoints else None
    return {
        "id": route.route_id,
        "label": route.label,
        "recommended": route.recommended,
        "distance_miles": round(route.distance_miles, 1),
        "duration_seconds": round(route.duration_seconds),
        "duration_label": route.duration_label,
        "arrival": _iso(arrival) if arrival else None,
        "average_risk": None if route.average_risk is None else round(route.average_risk, 2),
        "risk_miles": {key: round(value, 1) for key, value in route.risk_miles.items()},
        "worst": worst,
        "checkpoints": [_checkpoint_payload(point) for point in route.checkpoints],
        "segments": [
            {
                "risk": segment.risk or "unknown",
                "miles": round(segment.miles, 2),
                "coordinates": [
                    [round(lat, 5), round(lon, 5)] for lat, lon in segment.coordinates
                ],
            }
            for segment in route.segments
            if segment.coordinates
        ],
    }


def _worst_checkpoint(checkpoints) -> dict | None:
    known = [point for point in checkpoints if point.risk in LEVELS]
    if not known:
        return None
    worst = max(known, key=lambda point: (LEVELS.index(point.risk), point.miles_along))
    return _checkpoint_payload(worst)


def _checkpoint_payload(point) -> dict:
    return {
        "lat": round(point.lat, 5),
        "lon": round(point.lon, 5),
        "miles_along": round(point.miles_along, 1),
        "covers_miles": round(point.covers_miles, 1),
        "eta": _iso(point.eta),
        "wind_mph": _round(point.wind_mph, 1),
        "rain_in_hr": _round(point.rain_in_hr, 2),
        "snow_in_hr": _round(point.snow_in_hr, 2),
        "wind_risk": point.wind_risk,
        "wind_risk_before_load": point.wind_risk_before_load,
        "rain_risk": point.rain_risk,
        "snow_risk": point.snow_risk,
        "risk": point.risk,
    }


def _round(value, places):
    if value is None:
        return None
    return round(value, places)


def format_duration(seconds: float) -> str:
    minutes = int(round(seconds / 60))
    hours, mins = divmod(minutes, 60)
    if hours <= 0:
        return f"{mins} min"
    return f"{hours} h {mins} min"


def _iso(stamp: datetime) -> str:
    return stamp.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_departure(value) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise PlanError("Departure date and time are required.")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise PlanError("Departure time is not a valid date.") from exc
    if parsed.tzinfo is None:
        raise PlanError("Departure time must include a time zone.")
    return parsed.astimezone(timezone.utc)


def parse_place(value, name: str) -> dict:
    if not isinstance(value, dict):
        raise PlanError(f"Choose a {name} from the suggestions.")
    try:
        lat = float(value["lat"])
        lon = float(value["lon"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PlanError(f"Choose a {name} from the suggestions.") from exc
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise PlanError(f"The {name} coordinates are out of range.")
    label = str(value.get("label") or name).strip()[:180] or name
    return {"label": label, "lat": lat, "lon": lon}


def parse_load(value) -> float:
    try:
        load = float(value)
    except (TypeError, ValueError) as exc:
        raise PlanError("Load weight must be a number of pounds.") from exc
    return load


def parse_sample_miles(value) -> int:
    try:
        miles = int(value)
    except (TypeError, ValueError) as exc:
        raise PlanError("Sample interval must be 10, 25, or 50 miles.") from exc
    return miles
