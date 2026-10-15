
import hashlib
import json
import logging
import time

import requests
from django.core.cache import cache

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
CACHE_TTL = 900
MAX_RETRIES = 2


class WeatherServiceError(Exception):
    """Raised when weather data cannot be retrieved."""


def fetch_weather(params):
    """
    Fetch an Open-Meteo forecast, using Django cache
    to reduce repeated requests.

    params must be a dictionary of Open-Meteo query parameters.
    """
    normalized_params = json.dumps(
        params, sort_keys=True, separators=(",", ":")
    )

    digest = hashlib.sha256(
        normalized_params.encode("utf-8")
    ).hexdigest()

    cache_key = f"open_meteo:v1:{digest}"

    cached_data = cache.get(cache_key)
    if cached_data is not None:
        return cached_data

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = requests.get(
                OPEN_METEO_URL,
                params=params,
                timeout=20,
            )

            if response.status_code == 429:
                if attempt < MAX_RETRIES:
                    retry_after = response.headers.get("Retry-After")
                    try:
                        delay = min(int(retry_after), 10)
                    except (TypeError, ValueError):
                        delay = 2 ** attempt

                    time.sleep(max(delay, 1))
                    continue

                raise WeatherServiceError(
                    "Weather service rate limit reached. "
                    "Please try again later."
                )

            response.raise_for_status()
            data = response.json()

            # Cache only a successful response.
            cache.set(cache_key, data, CACHE_TTL)
            return data

        except WeatherServiceError:
            raise

        except (requests.RequestException, ValueError) as exc:
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)
                continue

            logger.warning("Open-Meteo request failed: %s", exc)
            raise WeatherServiceError(
                "Weather data is temporarily unavailable."
            ) from exc

    raise WeatherServiceError("Weather data is temporarily unavailable.")
