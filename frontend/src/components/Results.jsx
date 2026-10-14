import { formatLoad, formatMiles, formatWhen } from "../format";
import { RISKS, UNKNOWN, riskLabel, riskMeta } from "../risks";

const COLUMNS = [
  { key: "no_travel_miles", label: "No-travel", text: (route) => route.risk_miles.no_travel.toFixed(0) },
  { key: "severe_miles", label: "Severe", text: (route) => route.risk_miles.severe.toFixed(0) },
  { key: "high_miles", label: "High", text: (route) => route.risk_miles.high.toFixed(0) },
  {
    key: "average_risk",
    label: "Avg",
    text: (route) => (route.average_risk == null ? "—" : route.average_risk.toFixed(2)),
  },
  { key: "duration", label: "Time", text: (route) => route.duration_label },
];

export default function Results({ result, selectedId, onSelect, onHover, onFocusRoute }) {
  if (!result) {
    return (
      <section className="results empty-results">
        <h2>Route board</h2>
        <p>Three corridors show up here with severe miles, high miles, average risk, and travel time.</p>
      </section>
    );
  }

  return (
    <section className="results" aria-live="polite">
      <div className="recommend">
        <p className="eyebrow">Recommendation</p>
        <h2>{result.recommendation}</h2>
        <p className="meta">
          {formatLoad(result.load_weight_lb)} · sample every {result.sample_miles} mi · depart{" "}
          {formatWhen(result.departure)}
        </p>
      </div>

      <div className="compare-wrap">
        <table className="compare">
          <caption>Lower is better. No-travel miles outrank severe, then high, then average risk, then time.</caption>
          <thead>
            <tr>
              <th>Route</th>
              {COLUMNS.map((column) => (
                <th key={column.key} className={column.key === result.deciding_factor ? "is-key" : ""}>
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {result.routes.map((route) => (
              <tr
                key={route.id}
                className={route.id === selectedId ? "is-selected" : ""}
                onClick={() => onSelect(route.id)}
              >
                <th>
                  {route.label}
                  {route.recommended ? " · pick" : ""}
                </th>
                {COLUMNS.map((column) => (
                  <td key={column.key} className={column.key === result.deciding_factor ? "is-key" : ""}>
                    {column.text(route)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="cards">
        {result.routes.map((route) => {
          const active = route.id === selectedId;
          const miles = ["low", "moderate", "high", "severe", "no_travel", "unknown"].map((id) => ({
            id,
            miles: route.risk_miles[id] || 0,
          }));
          const total = miles.reduce((sum, item) => sum + item.miles, 0) || 1;
          return (
            <article
              key={route.id}
              className={`card${active ? " is-selected" : ""}`}
              onMouseEnter={() => onHover(route.id)}
              onMouseLeave={() => onHover(selectedId)}
            >
              <header>
                <div>
                  <h3>{route.label}</h3>
                  <p>
                    {formatMiles(route.distance_miles)} · {route.duration_label}
                    {route.arrival ? ` · arrive ${formatWhen(route.arrival)}` : ""}
                  </p>
                </div>
                {route.recommended && <span className="pill">Recommended</span>}
              </header>
              <div className="bar" aria-hidden="true">
                {miles.map((item) =>
                  item.miles > 0 ? (
                    <span
                      key={item.id}
                      style={{
                        width: `${(item.miles / total) * 100}%`,
                        background: item.id === "unknown" ? UNKNOWN.color : riskMeta(item.id).color,
                      }}
                    />
                  ) : null
                )}
              </div>
              <p className="worst">
                {route.worst
                  ? `Worst sample: ${riskLabel(route.worst.risk)} at mile ${route.worst.miles_along.toFixed(0)}`
                  : "No scored weather on this route."}
                {route.checkpoints ? ` · ${route.checkpoints.length} checkpoints` : ""}
              </p>
              {route.risk_miles.no_travel > 0 && (
                <p className="banner">Includes no-travel miles. Do not dispatch this load into that wind or precip.</p>
              )}
              <div className="card-actions">
                <button type="button" className={active ? "primary" : ""} onClick={() => onSelect(route.id)}>
                  {active ? "Showing on map" : "Show on map"}
                </button>
                <button type="button" onClick={() => onFocusRoute(route.id)}>
                  Zoom to route
                </button>
              </div>
            </article>
          );
        })}
      </div>
      {result.notes?.length > 0 && (
        <ul className="notes">
          {result.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function legendItems() {
  return [...RISKS, UNKNOWN];
}
