from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from django.test import SimpleTestCase
from rest_framework.test import APIClient

from planner.services.geo import decode_polyline, destination_point, haversine_miles
from planner.services.plan import format_duration
from planner.services.risk import (
    classify_conditions,
    classify_rain,
    classify_snow,
    classify_wind,
    deciding_factor,
    recommendation_text,
    sort_key,
)
from planner.services.sampling import (
    build_segments,
    marker_miles,
    sample_checkpoints,
    summarize,
)


class RiskBandTests(SimpleTestCase):
    def test_wind_table_and_load_rules(self):
        cases = [
            (24.99, 80000, "low", "low"),
            (25, 1000, "moderate", "moderate"),
            (34.99, 80000, "moderate", "moderate"),
            (35, 40000, "high", "high"),
            (44.99, 40000, "high", "high"),
            (35, 40000.01, "severe", "high"),
            (44.99, 50000, "severe", "high"),
            (45, 30000, "severe", "severe"),
            (54.99, 30000, "severe", "severe"),
            (45, 30000.01, "no_travel", "severe"),
            (54.99, 80000, "no_travel", "severe"),
            (55, 1, "no_travel", "no_travel"),
            (70, 80000, "no_travel", "no_travel"),
        ]
        for mph, load, adjusted, base in cases:
            with self.subTest(mph=mph, load=load):
                self.assertEqual(classify_wind(mph, load), (adjusted, base))

    def test_rain_bands_include_stated_upper_severe_bound(self):
        self.assertEqual(classify_rain(0.099), "low")
        self.assertEqual(classify_rain(0.10), "moderate")
        self.assertEqual(classify_rain(0.249), "moderate")
        self.assertEqual(classify_rain(0.25), "high")
        self.assertEqual(classify_rain(0.499), "high")
        self.assertEqual(classify_rain(0.50), "severe")
        self.assertEqual(classify_rain(1), "severe")
        self.assertEqual(classify_rain(1.01), "no_travel")
        self.assertEqual(classify_rain(-1), "low")

    def test_snow_bands(self):
        self.assertEqual(classify_snow(0.49), "low")
        self.assertEqual(classify_snow(0.5), "moderate")
        self.assertEqual(classify_snow(0.99), "moderate")
        self.assertEqual(classify_snow(1), "high")
        self.assertEqual(classify_snow(1.99), "high")
        self.assertEqual(classify_snow(2), "severe")
        self.assertEqual(classify_snow(3), "severe")
        self.assertEqual(classify_snow(3.01), "no_travel")

    def test_worst_condition_wins_and_missing_data_stays_unknown(self):
        mixed = classify_conditions(10, 0.3, 0.2, 10000)
        self.assertEqual(mixed["risk"], "high")
        self.assertIsNone(mixed["wind_risk_before_load"])
        upgraded = classify_conditions(40, 0, 0, 45000)
        self.assertEqual(upgraded["wind_risk"], "severe")
        self.assertEqual(upgraded["wind_risk_before_load"], "high")
        self.assertEqual(upgraded["risk"], "severe")
        soaked = classify_conditions(0, 1.2, 0, 1000)
        self.assertEqual(soaked["risk"], "no_travel")
        self.assertIsNone(classify_conditions(None, None, None, 1000)["risk"])


def _route(label, no_travel, severe, high, average, duration):
    return SimpleNamespace(
        label=label,
        risk_miles={
            "no_travel": no_travel,
            "severe": severe,
            "high": high,
            "moderate": 0,
            "low": 0,
            "unknown": 0,
        },
        average_risk=average,
        duration_seconds=duration,
        duration_label=format_duration(duration),
    )


class RankingTests(SimpleTestCase):
    def test_priority_is_no_travel_then_severe_then_high_then_average_then_time(self):
        routes = [
            _route("Long severe", 0, 30, 0, 1.2, 1000),
            _route("Short no-travel", 5, 0, 0, 1.1, 500),
            _route("High but quick", 0, 10, 80, 2.0, 400),
            _route("High and slow", 0, 10, 20, 3.0, 9000),
            _route("Tied risk, slower", 0, 10, 20, 1.4, 8000),
            _route("Tied risk, faster", 0, 10, 20, 1.4, 3000),
        ]
        ordered = sorted(routes, key=sort_key)
        self.assertEqual(
            [route.label for route in ordered],
            [
                "Tied risk, faster",
                "Tied risk, slower",
                "High and slow",
                "High but quick",
                "Long severe",
                "Short no-travel",
            ],
        )
        factor = deciding_factor(ordered[:2])
        self.assertEqual(factor, "duration")
        text = recommendation_text(ordered, deciding_factor(ordered))
        self.assertIn("Fewest no-travel miles", text)
        self.assertIn("Short no-travel", text)

    def test_severe_miles_decide_before_a_faster_clock(self):
        routes = sorted(
            [
                _route("Fastest", 0, 40, 0, 1.5, 1000),
                _route("Safer", 0, 8, 10, 1.8, 5000),
            ],
            key=sort_key,
        )
        self.assertEqual(routes[0].label, "Safer")
        self.assertEqual(deciding_factor(routes), "severe_miles")
        self.assertIn("Fewest severe miles", recommendation_text(routes, "severe_miles"))


class SamplingTests(SimpleTestCase):
    def _northbound(self, hops, hop_miles):
        coords = [(39.0, -90.0)]
        lat, lon = coords[0]
        for _ in range(hops):
            lat, lon = destination_point(lat, lon, 0, hop_miles)
            coords.append((lat, lon))
        return coords

    def test_marker_spacing_always_includes_the_destination(self):
        self.assertEqual(marker_miles(100, 25), [0, 25, 50, 75, 100])
        self.assertEqual(marker_miles(50, 50), [0, 50])
        self.assertEqual(marker_miles(10.2, 10), [0, 10.2])
        self.assertEqual(marker_miles(10.6, 10), [0, 10, 10.6])

    def test_each_sample_owns_the_miles_halfway_to_its_neighbors(self):
        coords = self._northbound(10, 10)
        departure = datetime(2026, 10, 13, 15, tzinfo=timezone.utc)
        checkpoints, cumulative, scale = sample_checkpoints(
            coords, 100, 7200, departure, 50
        )
        self.assertEqual(len(checkpoints), 3)
        self.assertEqual(checkpoints[0].eta, departure)
        self.assertAlmostEqual(
            (checkpoints[1].eta - departure).total_seconds(), 3600, delta=1
        )
        self.assertEqual(checkpoints[2].eta, departure + timedelta(seconds=7200))
        checkpoints[0].risk = "low"
        checkpoints[1].risk = "severe"
        checkpoints[2].risk = "low"
        segments = build_segments(coords, cumulative, checkpoints, scale)
        buckets, average = summarize(segments)
        self.assertAlmostEqual(buckets["severe"], 50, places=2)
        self.assertAlmostEqual(buckets["low"], 50, places=2)
        self.assertAlmostEqual(sum(buckets.values()), 100, places=2)
        self.assertAlmostEqual(checkpoints[1].covers_miles, 50, places=2)
        self.assertAlmostEqual(checkpoints[0].covers_miles, 25, places=2)
        self.assertAlmostEqual(average, (25 * 1 + 50 * 4 + 25 * 1) / 100, places=2)

    def test_polyline_and_distance_helpers(self):
        decoded = decode_polyline(r"_p~iF~ps|U_ulLnnqC_mqNvxq`@")
        self.assertEqual(len(decoded), 3)
        self.assertAlmostEqual(decoded[0][0], 38.5, places=3)
        self.assertAlmostEqual(decoded[0][1], -120.2, places=3)
        self.assertAlmostEqual(decoded[2][0], 43.252, places=3)
        lat, lon = destination_point(40, -90, 0, 60)
        self.assertAlmostEqual(haversine_miles(40, -90, lat, lon), 60, delta=0.2)
        back_lat, back_lon = destination_point(lat, lon, 180, 60)
        self.assertAlmostEqual(back_lat, 40, delta=0.02)
        self.assertAlmostEqual(back_lon, -90, delta=0.02)


class ApiTests(SimpleTestCase):
    def setUp(self):
        self.client = APIClient()

    def test_health(self):
        response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_plan_rejects_bad_input_without_calling_upstream(self):
        departure = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
        body = {
            "origin": {"label": "A", "lat": 41.8, "lon": -87.6},
            "destination": {"label": "B", "lat": 43.0, "lon": -87.9},
            "departure": departure,
            "load_weight_lb": 35000,
            "sample_miles": 15,
        }
        response = self.client.post("/api/plan/", body, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("10, 25, or 50", response.json()["detail"])

        body["sample_miles"] = 25
        body["load_weight_lb"] = 0
        response = self.client.post("/api/plan/", body, format="json")
        self.assertEqual(response.status_code, 400)

        body["load_weight_lb"] = 1000
        body["origin"] = {"label": "Same", "lat": 41.8, "lon": -87.6}
        body["destination"] = {"label": "Same", "lat": 41.8, "lon": -87.6}
        response = self.client.post("/api/plan/", body, format="json")
        self.assertEqual(response.status_code, 400)

    def test_geocode_requires_a_real_query(self):
        response = self.client.get("/api/geocode/", {"q": "a"})
        self.assertEqual(response.status_code, 400)
