from __future__ import annotations

LEVELS = ("low", "moderate", "high", "severe", "no_travel")
RANK = {name: index for index, name in enumerate(LEVELS)}
# 1 through 5, used for the distance-weighted average.
SCORE = {name: index + 1 for index, name in enumerate(LEVELS)}

FACTORS = (
    ("no_travel_miles", "fewest no-travel miles"),
    ("severe_miles", "fewest severe miles"),
    ("high_miles", "fewest high miles"),
    ("average_risk", "lowest average risk"),
    ("duration", "shortest travel time"),
)


def worse(left: str | None, right: str | None) -> str | None:
    if left is None:
        return right
    if right is None:
        return left
    return left if RANK[left] >= RANK[right] else right


def classify_wind(mph: float, load_lb: float) -> tuple[str, str]:
    """Return (risk after load rules, risk from the wind table alone)."""
    speed = max(0.0, float(mph))
    if speed < 25:
        base = "low"
    elif speed < 35:
        base = "moderate"
    elif speed < 45:
        base = "high"
    elif speed < 55:
        base = "severe"
    else:
        base = "no_travel"

    adjusted = base
    if base == "severe" and load_lb > 30000:
        adjusted = "no_travel"
    elif base == "high" and load_lb > 40000:
        adjusted = "severe"
    return adjusted, base


def classify_rain(inches_per_hour: float) -> str:
    rate = max(0.0, float(inches_per_hour))
    if rate > 1:
        return "no_travel"
    if rate >= 0.50:
        return "severe"
    if rate >= 0.25:
        return "high"
    if rate >= 0.10:
        return "moderate"
    return "low"


def classify_snow(inches_per_hour: float) -> str:
    rate = max(0.0, float(inches_per_hour))
    if rate > 3:
        return "no_travel"
    if rate >= 2:
        return "severe"
    if rate >= 1:
        return "high"
    if rate >= 0.5:
        return "moderate"
    return "low"


def classify_conditions(
    wind_mph: float | None,
    rain_in_hr: float | None,
    snow_in_hr: float | None,
    load_lb: float,
) -> dict:
    wind_risk = None
    wind_before = None
    rain_risk = None
    snow_risk = None
    if wind_mph is not None:
        wind_risk, wind_before = classify_wind(wind_mph, load_lb)
    if rain_in_hr is not None:
        rain_risk = classify_rain(rain_in_hr)
    if snow_in_hr is not None:
        snow_risk = classify_snow(snow_in_hr)

    overall = None
    for level in (wind_risk, rain_risk, snow_risk):
        overall = worse(overall, level)

    return {
        "wind_risk": wind_risk,
        "wind_risk_before_load": wind_before if wind_before != wind_risk else None,
        "rain_risk": rain_risk,
        "snow_risk": snow_risk,
        "risk": overall,
    }


def risk_index(level: str | None) -> int | None:
    if level is None:
        return None
    return RANK[level]


def sort_key(route) -> tuple:
    average = route.average_risk if route.average_risk is not None else 1e9
    miles = route.risk_miles
    return (
        miles["no_travel"],
        miles["severe"],
        miles["high"],
        average,
        route.duration_seconds,
    )


def deciding_factor(routes) -> str | None:
    """First ranking metric that actually separates the options."""
    if len(routes) < 2:
        return None
    readers = (
        ("no_travel_miles", lambda route: route.risk_miles["no_travel"], 0.05),
        ("severe_miles", lambda route: route.risk_miles["severe"], 0.05),
        ("high_miles", lambda route: route.risk_miles["high"], 0.05),
        (
            "average_risk",
            lambda route: 1e9 if route.average_risk is None else route.average_risk,
            0.005,
        ),
        ("duration", lambda route: route.duration_seconds, 30),
    )
    for name, reader, tolerance in readers:
        values = [reader(route) for route in routes]
        if max(values) - min(values) > tolerance:
            return name
    return None


def _metric_text(name: str, route) -> str:
    if name == "duration":
        return route.duration_label
    if name == "average_risk":
        if route.average_risk is None:
            return "n/a"
        return f"{route.average_risk:.2f}"
    bucket = {
        "no_travel_miles": "no_travel",
        "severe_miles": "severe",
        "high_miles": "high",
    }[name]
    return f"{route.risk_miles[bucket]:.1f} mi"


def recommendation_text(routes, factor: str | None) -> str:
    if len(routes) == 1:
        return "Only one distinct driving route was found."
    if factor is None:
        return "These routes match on weather risk and travel time."
    phrase = dict(FACTORS)[factor]
    best = _metric_text(factor, routes[0])
    others = "; ".join(
        f"{route.label} {_metric_text(factor, route)}" for route in routes[1:]
    )
    return f"{phrase[0].upper()}{phrase[1:]} ({best} versus {others})."
