# Haulway

Weather-aware truck routing. A driver enters an origin, destination, departure time, and load weight. The app returns up to three driving corridors, samples weather along each one, scores the load against wind, rain, and snow, and recommends the safest practical route.

Use the **Loom walkthrough** section at the bottom as the script while you record. Aim for 5–10 minutes. Click through the app on camera, and say the lines under each step.

## Run it

Python 3.12 and Node 18 or newer. No API keys.

Terminal 1, from the project folder:

```bash
python3.12 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/python manage.py runserver 8000
```

Terminal 2:

```bash
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173. The page talks to Django at http://127.0.0.1:8000. Vite proxies `/api` to that server.

One-process mode, after a frontend build:

```bash
cd frontend && npm run build
venv/bin/python manage.py runserver 8000
```

Then open http://127.0.0.1:8000.

## Check the API, one step at a time

Do these in a third terminal while Django is running. Each step should succeed before you go to the next.

**1. Health.** Confirms Django is up.

```bash
curl -s http://127.0.0.1:8000/api/health/
```

Expect `{"status":"ok"}`.

**2. Place search.** The user types a place. Nominatim returns the coordinates. There is no fixed list of cities.

```bash
curl -s "http://127.0.0.1:8000/api/geocode/?q=PLACE_NAME"
```

Expect a `results` list. Each item has `label`, `lat`, and `lon` for that search. A one-letter query returns 400.

**3. Plan a trip.** Use one result from step 2 as the origin and another as the destination. This is the main call. It can take several seconds because it asks the public routing and weather servers.

```bash
curl -s -X POST http://127.0.0.1:8000/api/plan/ \
  -H "Content-Type: application/json" \
  -d '{
    "origin": {"label":"ORIGIN_LABEL","lat":ORIGIN_LAT,"lon":ORIGIN_LON},
    "destination": {"label":"DESTINATION_LABEL","lat":DESTINATION_LAT,"lon":DESTINATION_LON},
    "departure": "2026-10-14T16:00:00Z",
    "load_weight_lb": 35000,
    "sample_miles": 25
  }'
```

Use a departure within the next 5 days. Expect JSON with:

- `routes`: up to 3 options
- `recommended_route_id` and `recommendation`
- `deciding_factor`: which rule broke the tie (`no_travel_miles`, `severe_miles`, `high_miles`, `average_risk`, or `duration`)
- each route: `distance_miles`, `duration_label`, `risk_miles`, `average_risk`, `checkpoints`, `segments`
- `heatmap.points`: corridor samples, each with 49 risk values (hours 0 through 48)
- `forecast_times`: the clock time for each slider hour

**4. Bad input.** Confirms validation, and that a bad request never calls the routing service.

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8000/api/plan/ \
  -H "Content-Type: application/json" \
  -d '{"origin":{"lat":41.8,"lon":-87.6},"destination":{"lat":43,"lon":-87.9},"departure":"2026-10-13T16:00:00Z","load_weight_lb":35000,"sample_miles":15}'
```

Expect `400`. `sample_miles` must be 10, 25, or 50.

**5. Unit tests.** These do not need the network. They lock the risk bands, load cutovers, mile totals, and ranking order.

```bash
venv/bin/python manage.py test planner
```

## Check the frontend, one step at a time

1. Open http://127.0.0.1:5173. You should see the form, an empty route board, a map, and a disabled forecast slider.
2. Type an origin and choose a suggestion. Type a destination and choose a suggestion. The coordinates under each box are the latitude and longitude returned for that place. They are not stored in the app.
3. Enter a load weight in pounds and choose 10, 25, or 50 miles. Leave departure as the next hour, or pick a time today.
4. Click **Find routes**. The button reads “Planning routes…” until the API returns.
5. The board shows a recommendation sentence, a comparison table, and up to three cards. The table’s deciding column is highlighted.
6. The map fits the trip. Routes are colored by risk. Dots are checkpoints. **A** and **B** are origin and destination. A green wash is the corridor forecast.
7. Click **Show on map** on a different card. That corridor gets darker and its checkpoints get larger.
8. Click **Zoom to route**. The map frames that corridor only.
9. Click a checkpoint dot. The popup shows ETA, wind, rain, snow, the combined level, and how many miles that sample covers.
10. Drag the forecast slider from 0 to 48. The label changes to “+Nh” plus the clock time. The wash updates. Checkpoint colors do not change, because those stay tied to arrival time.
11. Open **Risk, load, and ranking rules** and read the table on camera.

If every route is Low, the recommendation correctly falls through to shortest travel time. That is the last tie-break, not a bug.

## How the backend works

One request, `POST /api/plan/`, does the whole job. The browser does not call OSRM or Open-Meteo itself.

1. `planner/views.py` reads origin, destination, departure, load, and sample interval.
2. `planner/services/providers.py` asks the public OSRM server for up to three driving routes. If the server returns fewer than three distinct corridors, the app routes through a point off to the side of the fastest road and keeps the detour when it is a different corridor.
3. `planner/services/sampling.py` places checkpoints every 10, 25, or 50 road miles, plus the destination. ETA at each point is departure plus that fraction of the route duration.
4. The same module builds a grid of points in a buffer around the routes. That grid is the heatmap.
5. `providers.py` asks Open-Meteo once, in batches, for hourly wind (mph), rain plus showers (in/hr), and snowfall (in/hr) at every checkpoint and grid point.
6. `planner/services/risk.py` scores each checkpoint at its arrival hour. The level is the worst of wind (after the load rules), rain, and snow.
7. Each sample owns the miles halfway back to the previous sample and halfway forward to the next one. Those miles are what “severe miles” and “high miles” mean. The map splits color at the halfway point.
8. Routes are sorted by fewest no-travel miles, then fewest severe miles, then fewest high miles, then lowest average risk (Low 1 through No Travel 5, weighted by miles), then shortest travel time.
9. The heatmap stores a risk level for every grid point at each hour from 0 through 48 after departure. The slider only picks which of those 49 frames to draw. It does not call the API again.

| File | Job |
|---|---|
| `planner/views.py` | HTTP: `/api/health/`, `/api/geocode/`, `/api/plan/` |
| `planner/services/plan.py` | Orders the steps above and builds the JSON |
| `planner/services/providers.py` | Nominatim, OSRM, Open-Meteo |
| `planner/services/sampling.py` | Checkpoint spacing, mile ownership, corridor grid |
| `planner/services/risk.py` | Bands, load rules, ranking |
| `frontend/src` | Form, route board, Leaflet map, canvas heatmap |

## Risk rules

A checkpoint’s level is the worst of wind (after the load rules), rain, and snow.

| | Low | Moderate | High | Severe | No travel |
|---|---|---|---|---|---|
| Wind | < 25 mph | 25–34 | 35–44 | 45–54 | ≥ 55 mph |
| Rain | < 0.10 in/hr | 0.10–0.25 | 0.25–0.50 | 0.50–1.00 | > 1.00 |
| Snow | < 0.5 in/hr | 0.5–1.0 | 1.0–2.0 | 2.0–3.0 | > 3.0 |

A value on a boundary steps up. Rain at 0.25 in/hr is High. Rain at 1.00 is still Severe. Snow at 3.0 is still Severe. Wind at 55 mph is No Travel.

Load changes only wind:

- 55 mph or more is No Travel for every load.
- 45–54 mph and a load over 30,000 lb is No Travel.
- 35–44 mph and a load over 40,000 lb is Severe.

## Limits to say on camera

- OSRM’s driving profile is a car network. It does not know truck height, weight, or hazmat limits.
- Weather is the forecast for the arrival hour, not a guarantee between samples.
- Departure must be from 6 hours ago through 5 days ahead.
- The public routing, geocoding, and weather servers are shared demos and can be slow.

## Loom walkthrough

Record the browser at http://127.0.0.1:5173, full screen, with the map visible. Speak the line, then do the action. Skip a step if the picture already shows it.

1. **Open.** “This is Haulway. A driver enters origin, destination, departure, and load weight. The app builds three routes, samples weather on the truck’s ETA, and recommends the safest practical one.”
2. **Empty state.** Point at the form, the empty route board, and the map. “Nothing is planned yet. The forecast slider stays off until there is a corridor.”
3. **Places.** Type an origin, pick a suggestion, then do the same for the destination. “The driver types the places. The coordinates under the boxes come back from place search. The app does not ship with a list of cities.”
4. **Inputs.** Enter a load weight and choose 10, 25, or 50 miles. “Load changes wind risk. Over 30,000 pounds, 45 mph wind is no-travel. Over 40,000 pounds, 35 mph wind is severe.”
5. **Submit.** Click **Find routes**. “Django asks OSRM for routes, then Open-Meteo for wind, rain, and snow at each checkpoint’s arrival hour.”
6. **Recommendation.** Read the sentence and the table. “Ranking is no-travel miles, then severe miles, then high miles, then average risk, then travel time. If the weather is calm, time wins, which is what you see here.” Point at the highlighted column.
7. **Cards.** Point at distance, duration, arrival, the risk bar, and “Worst sample”. “Each checkpoint owns the miles halfway to its neighbors. Those miles are what the bar and the table count.”
8. **Map.** Point at the colored lines, the dots, and A and B. “Line color is the risk of that stretch. Click a dot for ETA, wind, rain, snow, and the combined level.” Click one dot.
9. **Switch route.** Click **Show on map** on another card, then **Zoom to route**. “All three corridors stay on the map. The selected one is drawn on top.”
10. **Slider.** Drag from 0 to about 24, then to 48. “This is the same risk rules along the corridor for the next 48 hours. It redraws locally. Checkpoint colors stay on the truck’s arrival time, not the slider hour.”
11. **Rules.** Open **Risk, load, and ranking rules** and leave it on screen for a few seconds.
12. **Close.** “Tests cover the band edges, the load cutovers, the mile totals, and the sort order. Routing is a public driving profile, not a truck-legal network.”
