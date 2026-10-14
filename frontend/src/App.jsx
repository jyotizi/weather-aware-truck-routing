import { useRef, useState } from "react";
import { planTrip } from "./api";
import MapView from "./components/MapView";
import PlaceField from "./components/PlaceField";
import Results from "./components/Results";
import { defaultDepartureValue, formatLoad } from "./format";

export default function App() {
  const mapRef = useRef(null);
  const requestRef = useRef(null);
  const [originText, setOriginText] = useState("");
  const [origin, setOrigin] = useState(null);
  const [destinationText, setDestinationText] = useState("");
  const [destination, setDestination] = useState(null);
  const [departure, setDeparture] = useState(defaultDepartureValue);
  const [load, setLoad] = useState("");
  const [sample, setSample] = useState(25);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [selectedId, setSelectedId] = useState(null);

  async function onSubmit(event) {
    event.preventDefault();
    if (!origin || !destination) {
      setError("Pick an origin and a destination from the suggestion list.");
      return;
    }
    const weight = Number(load);
    if (!Number.isFinite(weight) || weight <= 0) {
      setError("Enter a load weight in pounds.");
      return;
    }
    const when = new Date(departure);
    if (Number.isNaN(when.getTime())) {
      setError("Enter a departure date and time.");
      return;
    }
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setLoading(true);
    setError("");
    try {
      const plan = await planTrip(
        {
          origin,
          destination,
          departure: when.toISOString(),
          load_weight_lb: weight,
          sample_miles: sample,
        },
        controller.signal
      );
      setResult(plan);
      setSelectedId(plan.recommended_route_id);
    } catch (err) {
      if (err.name === "AbortError") return;
      setError(err.message || "Could not plan that trip.");
    } finally {
      if (requestRef.current === controller) setLoading(false);
    }
  }

  return (
    <div className="app">
      <aside className="panel">
        <header className="brand">
          <p className="eyebrow">Weather-aware truck routing</p>
          <h1>Haulway</h1>
          <p className="lede">
            Three driving corridors, weather at the truck’s ETA, and a 48-hour forecast along the trip.
          </p>
        </header>

        <form onSubmit={onSubmit}>
          <PlaceField
            label="Origin"
            value={originText}
            place={origin}
            onText={setOriginText}
            onPlace={setOrigin}
          />
          <PlaceField
            label="Destination"
            value={destinationText}
            place={destination}
            onText={setDestinationText}
            onPlace={setDestination}
          />
          <label className="field">
            <span>Departure</span>
            <input type="datetime-local" value={departure} onChange={(event) => setDeparture(event.target.value)} required />
          </label>
          <label className="field">
            <span>Load weight</span>
            <input
              type="number"
              min="1"
              max="120000"
              step="1"
              value={load}
              placeholder="Pounds"
              onChange={(event) => setLoad(event.target.value)}
              required
            />
            <small className="hint">
              Over 30,000 lb, 45 mph wind is no-travel. Over 40,000 lb, 35 mph wind is severe.
              {load ? ` Current load ${formatLoad(load)}.` : ""}
            </small>
          </label>
          <fieldset className="interval">
            <legend>Sample every</legend>
            {[10, 25, 50].map((miles) => (
              <label key={miles}>
                <input
                  type="radio"
                  name="sample"
                  value={miles}
                  checked={sample === miles}
                  onChange={() => setSample(miles)}
                />
                {miles} mi
              </label>
            ))}
          </fieldset>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <button className="submit" type="submit" disabled={loading}>
            {loading ? "Planning routes…" : "Find routes"}
          </button>
          {loading && (
            <p className="status">Sampling weather along each corridor. A long haul can take half a minute.</p>
          )}
        </form>

        <Results
          result={result}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onHover={(id) => mapRef.current?.emphasize(id)}
          onFocusRoute={(id) => {
            setSelectedId(id);
            mapRef.current?.focusRoute(id);
          }}
        />

        <details className="rules">
          <summary>Risk, load, and ranking rules</summary>
          <p>Each checkpoint is the worst of wind, rain, and snow at the truck’s arrival hour.</p>
          <table>
            <thead>
              <tr>
                <th></th>
                <th>Low</th>
                <th>Moderate</th>
                <th>High</th>
                <th>Severe</th>
                <th>No travel</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <th>Wind</th>
                <td>&lt; 25 mph</td>
                <td>25–34</td>
                <td>35–44</td>
                <td>45–54</td>
                <td>≥ 55</td>
              </tr>
              <tr>
                <th>Rain</th>
                <td>&lt; 0.10 in/hr</td>
                <td>0.10–0.25</td>
                <td>0.25–0.50</td>
                <td>0.50–1.00</td>
                <td>&gt; 1.00</td>
              </tr>
              <tr>
                <th>Snow</th>
                <td>&lt; 0.5 in/hr</td>
                <td>0.5–1.0</td>
                <td>1.0–2.0</td>
                <td>2.0–3.0</td>
                <td>&gt; 3.0</td>
              </tr>
            </tbody>
          </table>
          <p>
            A sample owns the miles halfway to the neighboring samples. Routes are ordered by no-travel miles,
            then severe miles, then high miles, then average risk (1–5), then travel time.
          </p>
        </details>

        <footer>
          Routes from the public OSRM driving profile (not truck-legal restrictions). Weather from Open-Meteo.
          Places from OpenStreetMap Nominatim. Map © OpenStreetMap.
        </footer>
      </aside>
      <MapView ref={mapRef} result={result} selectedId={selectedId} onSelect={setSelectedId} />
    </div>
  );
}
