from __future__ import annotations

from datetime import datetime, timedelta

from planner.services.errors import PlanError
from planner.services.geo import (
    cumulative_miles,
    decimate,
    destination_point,
    haversine_miles,
    min_distance_miles,
    point_at,
    pose_at,
    slice_coords,
)
from planner.services.models import Checkpoint, Segment
from planner.services.risk import LEVELS, SCORE


def marker_miles(total_miles: float, interval: float) -> list[float]:
    if total_miles <= 0:
        return [0.0]
    miles = [0.0]
    cursor = float(interval)
    # Keep the destination instead of a sample that would sit on top of it.
    while cursor < total_miles - 0.5:
        miles.append(cursor)
        cursor += interval
    if miles[-1] != total_miles:
        miles.append(total_miles)
    return miles


def sample_checkpoints(
    coords: list[tuple[float, float]],
    distance_miles: float,
    duration_seconds: float,
    departure: datetime,
    interval: float,
) -> tuple[list[Checkpoint], list[float], float]:
    cumulative = cumulative_miles(coords)
    geometry_miles = cumulative[-1]
    if geometry_miles <= 0.2 or distance_miles <= 0.2:
        raise PlanError("That route is too short to sample.")
    scale = distance_miles / geometry_miles
    checkpoints: list[Checkpoint] = []
    for road_miles in marker_miles(distance_miles, interval):
        geometry_at = min(geometry_miles, road_miles / scale)
        lat, lon = point_at(coords, cumulative, geometry_at)
        fraction = road_miles / distance_miles
        eta = departure + timedelta(seconds=duration_seconds * fraction)
        checkpoints.append(
            Checkpoint(lat=lat, lon=lon, miles_along=road_miles, eta=eta)
        )
    checkpoints[0].lat, checkpoints[0].lon = coords[0]
    checkpoints[0].miles_along = 0.0
    checkpoints[0].eta = departure
    checkpoints[-1].lat, checkpoints[-1].lon = coords[-1]
    checkpoints[-1].miles_along = distance_miles
    checkpoints[-1].eta = departure + timedelta(seconds=duration_seconds)
    return checkpoints, cumulative, scale


def _pieces(checkpoints: list[Checkpoint]) -> list[tuple[float, float, str | None, int]]:
    pieces = []
    for index in range(len(checkpoints) - 1):
        start = checkpoints[index]
        end = checkpoints[index + 1]
        mid = (start.miles_along + end.miles_along) / 2
        pieces.append((start.miles_along, mid, start.risk, index))
        pieces.append((mid, end.miles_along, end.risk, index + 1))
    return pieces


def build_segments(
    coords: list[tuple[float, float]],
    cumulative: list[float],
    checkpoints: list[Checkpoint],
    scale: float,
) -> list[Segment]:
    geometry_miles = cumulative[-1]
    covers = [0.0] * len(checkpoints)
    segments: list[Segment] = []
    for start, end, risk, index in _pieces(checkpoints):
        covers[index] += end - start
        if end - start <= 0:
            continue
        g0 = min(geometry_miles, start / scale)
        g1 = min(geometry_miles, end / scale)
        segments.append(
            Segment(
                risk=risk,
                miles=end - start,
                coordinates=slice_coords(coords, cumulative, g0, g1),
            )
        )
    for checkpoint, covered in zip(checkpoints, covers):
        checkpoint.covers_miles = covered
    return _merge(segments)


def _merge(segments: list[Segment]) -> list[Segment]:
    merged: list[Segment] = []
    for segment in segments:
        if (
            merged
            and merged[-1].risk == segment.risk
            and segment.coordinates
        ):
            previous = merged[-1]
            previous.miles += segment.miles
            if previous.coordinates:
                previous.coordinates.extend(segment.coordinates[1:])
            else:
                previous.coordinates.extend(segment.coordinates)
        else:
            merged.append(
                Segment(segment.risk, segment.miles, list(segment.coordinates))
            )
    for segment in merged:
        segment.coordinates = decimate(segment.coordinates, 0.55)
    return merged


def summarize(segments: list[Segment]) -> tuple[dict[str, float], float | None]:
    buckets = {name: 0.0 for name in (*LEVELS, "unknown")}
    weighted = 0.0
    known = 0.0
    for segment in segments:
        if segment.risk is None:
            buckets["unknown"] += segment.miles
            continue
        buckets[segment.risk] += segment.miles
        weighted += SCORE[segment.risk] * segment.miles
        known += segment.miles
    average = (weighted / known) if known else None
    return buckets, average


def corridor_points(
    routes: list[tuple[list[tuple[float, float]], list[float]]],
    limit: int = 100,
) -> list[tuple[float, float]]:
    """A loose grid inside a buffer around every route, capped for one forecast fetch."""
    samples: list[tuple[float, float]] = []
    for coords, cumulative in routes:
        if not coords or cumulative[-1] <= 0:
            continue
        walked = 0.0
        while walked < cumulative[-1]:
            samples.append(point_at(coords, cumulative, walked))
            walked += 12
        samples.append(coords[-1])
    if not samples:
        return []

    lats = [lat for lat, _ in samples]
    lons = [lon for _, lon in samples]
    buffer_miles = 34.0
    lat_pad = buffer_miles / 69.0
    mid_lat = (min(lats) + max(lats)) / 2
    lon_scale = max(0.25, math_cos_lat(mid_lat))
    lon_pad = buffer_miles / (69.0 * lon_scale)
    min_lat, max_lat = min(lats) - lat_pad, max(lats) + lat_pad
    min_lon, max_lon = min(lons) - lon_pad, max(lons) + lon_pad

    chosen: list[tuple[float, float]] = []
    for spacing in (38, 26, 18):
        chosen = _grid(
            min_lat, max_lat, min_lon, max_lon, mid_lat, spacing, samples, buffer_miles
        )
        if len(chosen) >= 28:
            break
    if len(chosen) < 8:
        stride = max(1, len(samples) // 40)
        chosen = samples[::stride]
    if len(chosen) > limit:
        step = len(chosen) / limit
        chosen = [chosen[int(index * step)] for index in range(limit)]
    return chosen


def _grid(
    min_lat, max_lat, min_lon, max_lon, mid_lat, spacing, samples, buffer_miles
):
    lat_step = spacing / 69.0
    lon_step = spacing / (69.0 * max(0.25, math_cos_lat(mid_lat)))
    points = []
    lat = min_lat
    # A little slack so a point beside a straight segment between samples is kept.
    keep_within = buffer_miles + spacing * 0.35
    while lat <= max_lat + 1e-9:
        lon = min_lon
        while lon <= max_lon + 1e-9:
            if min_distance_miles(lat, lon, samples) <= keep_within:
                points.append((lat, lon))
            lon += lon_step
        lat += lat_step
    return points


def math_cos_lat(lat: float) -> float:
    import math

    return math.cos(math.radians(lat))


def via_candidates(
    coords: list[tuple[float, float]], cumulative: list[float]
) -> list[tuple[float, float]]:
    """Side points used to ask the router for another corridor."""
    total = cumulative[-1]
    offset = min(170.0, max(28.0, total * 0.14))
    candidates = []
    for fraction in (0.42, 0.62):
        lat, lon, bearing = pose_at(coords, cumulative, total * fraction)
        for turn in (90, -90):
            for scale in (1.0, 1.65):
                point = destination_point(lat, lon, bearing + turn, offset * scale)
                origin_gap = haversine_miles(point[0], point[1], coords[0][0], coords[0][1])
                dest_gap = haversine_miles(point[0], point[1], coords[-1][0], coords[-1][1])
                if origin_gap < 15 or dest_gap < 15:
                    continue
                candidates.append(point)
    return candidates
