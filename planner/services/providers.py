from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone

import requests
from django.core.cache import cache
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from planner.services.errors import PlanError
from planner.services.geo import cumulative_miles, decode_polyline, distinct_corridor
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
        adapter = HTTPAdapter(max_retries=retry, pool_maxsize=8)
        session.mount("https://", adapter)
        session.headers["User-Agent"] = USER_AGENT
        _session = session
    return _session


def round_key(lat: float, lon: float) -> tuple[float, float]:
    return (round(float(lat), 2), round(float(lon), 2))


def geocode_search(query: str) -> list[dict]:
    cleaned = " ".join(query.split())
    if len(cleaned) < 2:
        raise PlanError("Enter at least two characters to search.")
    if len(cleaned) > 120:
        raise PlanError("That place name is too long.")
    cached = _geocode_cache.get(cleaned.lower())
    now = datetime.now(timezone.utc)
    if cached and now - cached[0] < timedelta(minutes=10):
        return cached[1]
    try:
        # Coordinates come from this search. The user types a place name;
        # Nominatim returns the matching label, latitude, and longitude.
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
        logger.warning("geocode failed: %s", exc)
        raise PlanError("Place search is unavailable. Try again in a moment.", 502) from exc
    results = []
    for item in payload if isinstance(payload, list) else []:
        try:
            results.append(
                {
                    "label": str(item.get("display_name") or cleaned)[:180],
                    "lat": float(item["lat"]),
                    "lon": float(item["lon"]),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    _geocode_cache[cleaned.lower()] = (now, results)
    if len(_geocode_cache) > 100:
        oldest = sorted(_geocode_cache.items(), key=lambda item: item[1][0])[:20]
        for key, _ in oldest:
            _geocode_cache.pop(key, None)
    return results

