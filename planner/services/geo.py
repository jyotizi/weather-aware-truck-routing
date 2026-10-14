from __future__ import annotations

import math

EARTH_MILES = 3958.7613


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lon / 2) ** 2
    )
    return 2 * EARTH_MILES * math.asin(min(1.0, math.sqrt(a)))


def bearing_degrees(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_lon = math.radians(lon2 - lon1)
    y = math.sin(d_lon) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(d_lon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def destination_point(
    lat: float, lon: float, bearing: float, distance_miles: float
) -> tuple[float, float]:
    angular = distance_miles / EARTH_MILES
    theta = math.radians(bearing)
    phi1 = math.radians(lat)
    lam1 = math.radians(lon)
    phi2 = math.asin(
        math.sin(phi1) * math.cos(angular)
        + math.cos(phi1) * math.sin(angular) * math.cos(theta)
    )
    lam2 = lam1 + math.atan2(
        math.sin(theta) * math.sin(angular) * math.cos(phi1),
        math.cos(angular) - math.sin(phi1) * math.sin(phi2),
    )
    lon2 = (math.degrees(lam2) + 540) % 360 - 180
    return math.degrees(phi2), lon2


def cumulative_miles(coords: list[tuple[float, float]]) -> list[float]:
    totals = [0.0]
    for (lat1, lon1), (lat2, lon2) in zip(coords, coords[1:]):
        totals.append(totals[-1] + haversine_miles(lat1, lon1, lat2, lon2))
    return totals


def point_at(
    coords: list[tuple[float, float]], cumulative: list[float], miles: float
) -> tuple[float, float]:
    if miles <= 0:
        return coords[0]
    if miles >= cumulative[-1]:
        return coords[-1]
    lo = 1
    hi = len(cumulative) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if cumulative[mid] < miles:
            lo = mid + 1
        else:
            hi = mid
    start = cumulative[lo - 1]
    end = cumulative[lo]
    span = end - start
    fraction = 0.0 if span == 0 else (miles - start) / span
    lat1, lon1 = coords[lo - 1]
    lat2, lon2 = coords[lo]
    return lat1 + fraction * (lat2 - lat1), lon1 + fraction * (lon2 - lon1)


def pose_at(
    coords: list[tuple[float, float]], cumulative: list[float], miles: float
) -> tuple[float, float, float]:
    """Point and forward bearing at a distance along the line."""
    lat, lon = point_at(coords, cumulative, miles)
    ahead = point_at(coords, cumulative, min(cumulative[-1], miles + 1))
    behind = point_at(coords, cumulative, max(0.0, miles - 1))
    if (ahead[0], ahead[1]) != (lat, lon):
        bearing = bearing_degrees(lat, lon, ahead[0], ahead[1])
    else:
        bearing = bearing_degrees(behind[0], behind[1], lat, lon)
    return lat, lon, bearing


def slice_coords(
    coords: list[tuple[float, float]],
    cumulative: list[float],
    start_miles: float,
    end_miles: float,
) -> list[tuple[float, float]]:
    if end_miles < start_miles:
        start_miles, end_miles = end_miles, start_miles
    points = [point_at(coords, cumulative, start_miles)]
    for index in range(1, len(coords) - 1):
        if start_miles < cumulative[index] < end_miles:
            points.append(coords[index])
    points.append(point_at(coords, cumulative, end_miles))
    cleaned = [points[0]]
    for point in points[1:]:
        if haversine_miles(cleaned[-1][0], cleaned[-1][1], point[0], point[1]) >= 0.01:
            cleaned.append(point)
    if cleaned[-1] != points[-1]:
        cleaned.append(points[-1])
    return cleaned


def decimate(
    coords: list[tuple[float, float]], minimum_miles: float
) -> list[tuple[float, float]]:
    if len(coords) < 3:
        return list(coords)
    kept = [coords[0]]
    for point in coords[1:-1]:
        if haversine_miles(kept[-1][0], kept[-1][1], point[0], point[1]) >= minimum_miles:
            kept.append(point)
    if kept[-1] != coords[-1]:
        kept.append(coords[-1])
    return kept


def decode_polyline(encoded: str, precision: int = 5) -> list[tuple[float, float]]:
    factor = float(10**precision)
    coords: list[tuple[float, float]] = []
    index = 0
    lat = 0
    lon = 0
    length = len(encoded)
    while index < length:
        for coord in range(2):
            shift = 0
            result = 0
            while True:
                chunk = ord(encoded[index]) - 63
                index += 1
                result |= (chunk & 0x1F) << shift
                shift += 5
                if chunk < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if coord == 0:
                lat += delta
            else:
                lon += delta
        coords.append((lat / factor, lon / factor))
    return coords


def min_distance_miles(
    lat: float,
    lon: float,
    samples: list[tuple[float, float]],
) -> float:
    best = float("inf")
    for sample_lat, sample_lon in samples:
        distance = haversine_miles(lat, lon, sample_lat, sample_lon)
        if distance < best:
            best = distance
    return best


def distinct_corridor(
    coords: list[tuple[float, float]],
    cumulative: list[float],
    others: list[list[tuple[float, float]]],
    sample_miles: float = 20,
    far_miles: float = 12,
    far_fraction: float = 0.28,
) -> bool:
    """True when enough of this route sits away from every route already kept."""
    if not others or cumulative[-1] <= 0:
        return True
    total = cumulative[-1]
    miles = 0.0
    samples: list[tuple[float, float]] = []
    while miles < total:
        samples.append(point_at(coords, cumulative, miles))
        miles += sample_miles
    samples.append(coords[-1])
    other_samples = []
    for other in others:
        other_cum = cumulative_miles(other)
        step = 8.0
        walked = 0.0
        packed: list[tuple[float, float]] = []
        while walked < other_cum[-1]:
            packed.append(point_at(other, other_cum, walked))
            walked += step
        packed.append(other[-1])
        other_samples.append(packed)

    far = 0
    for lat, lon in samples:
        nearest = min(min_distance_miles(lat, lon, packed) for packed in other_samples)
        if nearest >= far_miles:
            far += 1
    return far / len(samples) >= far_fraction
