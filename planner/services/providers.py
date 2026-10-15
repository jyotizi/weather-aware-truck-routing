
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone

import requests
from django.core.cache import cache
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from planner.services.errors import PlanError
from planner.services.geo import (
    cumulative_miles,
    decode_polyline,
    distinct_corridor,
)
from planner.services.models import RawRoute
from planner.services.sampling import via_candidates

logger = logging.getLogger("planner")

USER_AGENT = "Haulway/1.0 (weather-aware truck routing demo)"
OSRM_URL = "https://router.project-osrm.org/route/v1/driving"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
METEO_URL = "https://api.open-meteo.com/v1/forecast"

_session: requests.Session | None = None
_geocode_cache: dict[str, tuple[datetime, list[dict]]] = {}


def _http() -> requests.Session:
    global _session

    if _session is None:
        session = requests.Session()

        retry = Retry(
            total=2,
            backoff_factor=0.5,
            status_forcelist=(500, 502, 503, 504),
            allowed_methods=frozenset(["GET"]),
            respect_retry_after_header=True,
        )

        adapter = HTTPAdapter(
            max_retries=retry,
            pool_maxsize=8,
        )

        session.mount("https://", adapter)
        session.headers["User-Agent"] = USER_AGENT
        _session = session

    return _session


def round_key(lat: float, lon: float) -> tuple[float, float]:
    return round(float(lat), 2), round(float(lon), 2)


def geocode_search(query: str) -> list[dict]:
    cleaned = " ".join(query.split())

    if len(cleaned) < 2:
        raise PlanError("Enter at least two characters to search.")

    if len(cleaned) > 120:
        raise PlanError("That place name is too long.")

    now = datetime.now(timezone.utc)
    cache_key = cleaned.lower()
    cached = _geocode_cache.get(cache_key)

    if cached and now - cached[0] < timedelta(minutes=10):
        return cached[1]

    try:
        response = _http().get(
            NOMINATIM_URL,
            params={
                "q": cleaned,
                "format": "jsonv2",
                "limit": 5,
            },
            timeout=12,
        )
        response.raise_for_status()
        payload = response.json()

    except requests.RequestException as exc:
        logger.warning("Geocode failed: %s", exc)
        raise PlanError(
            "Place search is unavailable. Try again in a moment.",
            502,
        ) from exc

    results = []

    for item in payload if isinstance(payload, list) else []:
        try:
            results.append(
                {
                    "label": str(
                        item.get("display_name") or cleaned
                    )[:180],
                    "lat": float(item["lat"]),
                    "lon": float(item["lon"]),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue

    _geocode_cache[cache_key] = (now, results)

    if len(_geocode_cache) > 100:
        oldest = sorted(
            _geocode_cache.items(),
            key=lambda item: item[1][0],
        )[:20]

        for key, _ in oldest:
            _geocode_cache.pop(key, None)

    return results


def _osrm(
    coordinates: list[tuple[float, float]],
    alternatives: int | None,
) -> list[RawRoute]:
    path = ";".join(
        f"{lon:.6f},{lat:.6f}"
        for lat, lon in coordinates
    )

    params = {
        "overview": "full",
        "geometries": "polyline",
        "steps": "false",
    }

    if alternatives:
        params["alternatives"] = str(alternatives)
    else:
        params["continue_straight"] = "false"

    try:
        response = _http().get(
            f"{OSRM_URL}/{path}",
            params=params,
            timeout=40,
        )
        response.raise_for_status()
        payload = response.json()

    except requests.RequestException as exc:
        logger.warning("OSRM failed: %s", exc)
        raise PlanError(
            "Routing service is unavailable. Try again in a moment.",
            502,
        ) from exc

    code = payload.get("code")

    if code == "NoRoute":
        raise PlanError(
            "No drivable route was found between those points.",
            404,
        )

    if code != "Ok":
        logger.warning(
            "OSRM code %s: %s",
            code,
            payload.get("message"),
        )
        raise PlanError(
            "Routing service could not build a route. Try again.",
            502,
        )

    routes: list[RawRoute] = []

    for route in payload.get("routes") or []:
        geometry = route.get("geometry")

        if not isinstance(geometry, str):
            continue

        coords = decode_polyline(geometry)

        if len(coords) < 2:
            continue

        try:
            distance = float(route["distance"]) / 1609.344
            duration = float(route["duration"])
        except (KeyError, TypeError, ValueError):
            continue

        if distance <= 0 or duration <= 0:
            continue

        routes.append(
            RawRoute(
                coords=coords,
                distance_miles=distance,
                duration_seconds=duration,
            )
        )

    return routes


def driving_routes(
    origin: tuple[float, float],
    destination: tuple[float, float],
) -> tuple[list[RawRoute], list[str]]:
    """Return up to three distinct driving routes."""
    notes: list[str] = []

    found = _osrm(
        [origin, destination],
        alternatives=3,
    )

    kept: list[RawRoute] = []

    for route in found:
        cumulative = cumulative_miles(route.coords)

        if not kept or distinct_corridor(
            route.coords,
            cumulative,
            [item.coords for item in kept],
        ):
            kept.append(route)

        if len(kept) == 3:
            return kept, notes

    if not kept:
        raise PlanError(
            "No drivable route was found between those points.",
            404,
        )

    base_cumulative = cumulative_miles(kept[0].coords)

    for via in via_candidates(
        kept[0].coords,
        base_cumulative,
    ):
        if len(kept) >= 3:
            break

        try:
            detours = _osrm(
                [origin, via, destination],
                alternatives=None,
            )
        except PlanError as exc:
            logger.info(
                "Via route skipped: %s",
                exc.message,
            )
            continue

        for route in detours:
            cumulative = cumulative_miles(route.coords)

            if distinct_corridor(
                route.coords,
                cumulative,
                [item.coords for item in kept],
            ):
                kept.append(route)
                break

    if len(kept) < 3:
        notes.append(
            "Fewer than three distinct driving corridors "
            "were available for this trip."
        )

    return kept[:3], notes


def _optional_float(values, index: int) -> float | None:
    if index >= len(values):
        return None

    value = values[index]

    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sum_optional(
    left: float | None,
    right: float | None,
) -> float | None:
    if left is None and right is None:
        return None

    return (left or 0.0) + (right or 0.0)


def _parse_series(
    item: dict,
) -> dict[
    datetime,
    tuple[float | None, float | None, float | None],
]:
    hourly = item.get("hourly") or {}

    times = hourly.get("time") or []
    wind = hourly.get("wind_speed_10m") or []
    rain = hourly.get("rain") or []
    showers = hourly.get("showers") or []
    snow = hourly.get("snowfall") or []

    series = {}

    for index, stamp in enumerate(times):
        try:
            hour = datetime.fromisoformat(stamp).replace(
                tzinfo=timezone.utc
            )
        except (ValueError, TypeError):
            continue

        wind_value = _optional_float(wind, index)

        rain_value = _sum_optional(
            _optional_float(rain, index),
            _optional_float(showers, index),
        )

        snow_value = _optional_float(snow, index)

        series[hour] = (
            wind_value,
            rain_value,
            snow_value,
        )

    return series


def _weather_cache_key(
    lat: float,
    lon: float,
    start_date: str,
    end_date: str,
) -> str:
    coordinate = f"{lat:.2f},{lon:.2f}"

    digest = hashlib.sha256(
        coordinate.encode("utf-8")
    ).hexdigest()

    return (
        f"open_meteo:v1:{start_date}:{end_date}:{digest}"
    )


def _fetch_batch(
    keys: list[tuple[float, float]],
    start_date: str,
    end_date: str,
) -> dict[
    tuple[float, float],
    dict[datetime, tuple[float | None, float | None, float | None]],
]:
    """Fetch forecasts, reusing cached data whenever possible."""
    merged = {}
    missing = []

    for point in keys:
        lat, lon = point

        cached = cache.get(
            _weather_cache_key(
                lat,
                lon,
                start_date,
                end_date,
            )
        )

        if cached is None:
            missing.append(point)
        else:
            merged[point] = cached

    if not missing:
        return merged

    batch_size = 10

    for offset in range(0, len(missing), batch_size):
        batch = missing[offset:offset + batch_size]

        params = {
            "latitude": ",".join(
                f"{lat:.2f}" for lat, _ in batch
            ),
            "longitude": ",".join(
                f"{lon:.2f}" for _, lon in batch
            ),
            "hourly": "wind_speed_10m,rain,showers,snowfall",
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "snowfall_unit": "inch",
            "timezone": "UTC",
            "start_date": start_date,
            "end_date": end_date,
        }

        try:
            response = _http().get(
                METEO_URL,
                params=params,
                timeout=40,
            )

            if response.status_code == 429:
                logger.warning(
                    "Open-Meteo rate limit reached"
                )
                raise PlanError(
                    "Weather service is busy. Please try again later.",
                    503,
                )

            response.raise_for_status()
            payload = response.json()

        except PlanError:
            raise

        except requests.RequestException as exc:
            logger.warning(
                "Open-Meteo request failed: %s",
                exc,
            )
            raise PlanError(
                "Weather service is temporarily unavailable. "
                "Try again later.",
                503,
            ) from exc

        except ValueError as exc:
            logger.warning(
                "Open-Meteo returned invalid JSON: %s",
                exc,
            )
            raise PlanError(
                "Weather service returned an invalid response.",
                502,
            ) from exc

        if isinstance(payload, dict) and payload.get("error"):
            logger.warning(
                "Open-Meteo error: %s",
                payload.get("reason"),
            )
            raise PlanError(
                "Weather service rejected the forecast request.",
                502,
            )

        items = (
            payload
            if isinstance(payload, list)
            else [payload]
        )

        if len(items) != len(batch):
            logger.warning(
                "Open-Meteo returned %s locations for %s",
                len(items),
                len(batch),
            )
            raise PlanError(
                "Weather service returned an unexpected forecast.",
                502,
            )

        for point, item in zip(batch, items):
            series = _parse_series(item)

            if series:
                cache.set(
                    _weather_cache_key(
                        point[0],
                        point[1],
                        start_date,
                        end_date,
                    ),
                    series,
                    timeout=900,
                )

            merged[point] = series

    return merged


def fetch_hourly(
    points: list[tuple[float, float]],
    departure: datetime,
) -> dict[
    tuple[float, float],
    dict[datetime, tuple[float | None, float | None, float | None]],
]:
    """Fetch hourly weather sequentially in small batches."""
    unique = list(
        dict.fromkeys(
            round_key(lat, lon)
            for lat, lon in points
        )
    )

    if not unique:
        return {}

    start = departure.astimezone(timezone.utc)
    end = start + timedelta(hours=48)

    start_date = start.date().isoformat()
    end_date = end.date().isoformat()

    batches = [
        unique[index:index + 10]
        for index in range(0, len(unique), 10)
    ]

    merged = {}

    for batch in batches:
        result = _fetch_batch(
            batch,
            start_date,
            end_date,
        )
        merged.update(result)

    return merged
