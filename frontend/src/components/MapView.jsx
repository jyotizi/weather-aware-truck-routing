import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import L from "leaflet";
import { formatWhen } from "../format";
import { RISKS, riskLabel, riskMeta } from "../risks";

const TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';

function hexToRgba(hex, alpha) {
  const value = hex.replace("#", "");
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function makeSprite(hex) {
  const canvas = document.createElement("canvas");
  canvas.width = 96;
  canvas.height = 96;
  const ctx = canvas.getContext("2d");
  const gradient = ctx.createRadialGradient(48, 48, 0, 48, 48, 48);
  gradient.addColorStop(0, hexToRgba(hex, 0.82));
  gradient.addColorStop(0.4, hexToRgba(hex, 0.34));
  gradient.addColorStop(1, hexToRgba(hex, 0));
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, 96, 96);
  return canvas;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

function reading(label, value, unit, level) {
  if (value == null) return `${label} unavailable`;
  const shown = Number(value).toFixed(unit === "mph" ? 1 : 2);
  return `${label} ${shown} ${unit} · ${riskLabel(level)}`;
}

function popupHtml(routeLabel, checkpoint) {
  const loadNote = checkpoint.wind_risk_before_load
    ? `<br />Load raises wind from ${escapeHtml(riskLabel(checkpoint.wind_risk_before_load))} to ${escapeHtml(riskLabel(checkpoint.wind_risk))}.`
    : "";
  return `
    <strong>${escapeHtml(routeLabel)} · mile ${checkpoint.miles_along.toFixed(0)}</strong><br />
    ETA ${escapeHtml(formatWhen(checkpoint.eta))}<br />
    ${escapeHtml(reading("Wind", checkpoint.wind_mph, "mph", checkpoint.wind_risk))}${loadNote}<br />
    ${escapeHtml(reading("Rain", checkpoint.rain_in_hr, "in/hr", checkpoint.rain_risk))}<br />
    ${escapeHtml(reading("Snow", checkpoint.snow_in_hr, "in/hr", checkpoint.snow_risk))}<br />
    <strong>Combined ${escapeHtml(checkpoint.risk ? riskLabel(checkpoint.risk) : "no forecast")}</strong><br />
    Covers ${checkpoint.covers_miles.toFixed(1)} mi around this sample.
  `;
}

function indexHeat(points) {
  const byHour = Array.from({ length: 49 }, () => [[], [], [], [], []]);
  (points || []).forEach((point) => {
    (point.risks || []).forEach((risk, hour) => {
      if (risk == null || risk < 0 || risk > 4 || !byHour[hour]) return;
      byHour[hour][risk].push(point);
    });
  });
  return byHour;
}

const MapView = forwardRef(function MapView({ result, selectedId, onSelect }, ref) {
  const hostRef = useRef(null);
  const mapRef = useRef(null);
  const canvasRef = useRef(null);
  const groupsRef = useRef(new Map());
  const endsRef = useRef([]);
  const heatRef = useRef(null);
  const hourRef = useRef(0);
  const labelRef = useRef(null);
  const sliderRef = useRef(null);
  const resultRef = useRef(result);
  const selectedRef = useRef(selectedId);
  const onSelectRef = useRef(onSelect);
  const frameRef = useRef(0);
  resultRef.current = result;
  selectedRef.current = selectedId;
  onSelectRef.current = onSelect;

  function paintLabel(hour) {
    const times = resultRef.current?.forecast_times;
    if (!labelRef.current) return;
    if (!times || !times[hour]) {
      labelRef.current.textContent = "Plan a trip to load the corridor";
      return;
    }
    labelRef.current.textContent = `+${hour} h · ${formatWhen(times[hour])}`;
  }

  function drawHeat() {
    const map = mapRef.current;
    const canvas = canvasRef.current;
    if (!map || !canvas) return;
    const ctx = canvas.getContext("2d");
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    ctx.setTransform(canvas.width / width, 0, 0, canvas.height / height, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const hour = Math.max(0, Math.min(48, hourRef.current));
    const buckets = heatRef.current?.[hour];
    if (!buckets) return;
    const zoom = map.getZoom();
    const radius = Math.max(20, Math.min(84, 16 * 1.38 ** (zoom - 5)));
    const sprites = canvas._sprites;
    buckets.forEach((points, level) => {
      points.forEach((point) => {
        const projected = map.latLngToContainerPoint([point.lat, point.lon]);
        ctx.drawImage(sprites[level], projected.x - radius, projected.y - radius, radius * 2, radius * 2);
      });
    });
  }

  function scheduleHeat() {
    if (frameRef.current) return;
    frameRef.current = requestAnimationFrame(() => {
      frameRef.current = 0;
      drawHeat();
    });
  }

  function emphasize(activeId) {
    const map = mapRef.current;
    if (!map) return;
    groupsRef.current.forEach((group, id) => {
      const active = id === activeId;
      group.casing.forEach((line) => {
        line.setStyle({ opacity: active ? 0.9 : 0.28, weight: active ? 10 : 7 });
        if (active) line.bringToFront();
      });
      group.lines.forEach((line) => {
        line.setStyle({ opacity: active ? 0.98 : 0.42, weight: active ? 5.5 : 3.5 });
        if (active) line.bringToFront();
      });
      group.markers.forEach((marker) => {
        marker.setStyle({
          opacity: active ? 1 : 0.45,
          fillOpacity: active ? 1 : 0.4,
          radius: active ? 6.5 : 4,
        });
        if (active && marker.bringToFront) marker.bringToFront();
      });
    });
  }

  function clearRoutes() {
    groupsRef.current.forEach((group) => {
      [...group.casing, ...group.lines, ...group.markers].forEach((layer) => layer.remove());
    });
    groupsRef.current.clear();
    endsRef.current.forEach((marker) => marker.remove());
    endsRef.current = [];
  }

  useImperativeHandle(ref, () => ({
    emphasize,
    focusRoute(id) {
      const group = groupsRef.current.get(id);
      const map = mapRef.current;
      if (!group || !map) return;
      const bounds = L.latLngBounds([]);
      group.lines.forEach((line) => bounds.extend(line.getBounds()));
      if (bounds.isValid()) {
        map.fitBounds(bounds, { paddingTopLeft: [28, 28], paddingBottomRight: [28, 108] });
      }
    },
  }));

  useEffect(() => {
    const host = hostRef.current;
    const map = L.map(host, { zoomControl: true, minZoom: 3, maxZoom: 16 });
    L.tileLayer(TILES, { attribution: ATTRIBUTION, maxZoom: 19 }).addTo(map);
    L.control.scale({ imperial: true, metric: false }).addTo(map);
    map.setView([39.5, -96.5], 4);
    const canvas = document.createElement("canvas");
    canvas.className = "corridor-heat";
    canvas._sprites = RISKS.map((item) => makeSprite(item.color));
    host.appendChild(canvas);
    mapRef.current = map;
    canvasRef.current = canvas;

    function sizeCanvas() {
      const rect = host.getBoundingClientRect();
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.round(rect.width * ratio));
      canvas.height = Math.max(1, Math.round(rect.height * ratio));
      canvas.style.width = `${rect.width}px`;
      canvas.style.height = `${rect.height}px`;
      scheduleHeat();
    }
    map.on("move zoom resize", scheduleHeat);
    const observer = new ResizeObserver(() => {
      map.invalidateSize();
      sizeCanvas();
    });
    observer.observe(host);
    sizeCanvas();

    return () => {
      observer.disconnect();
      if (frameRef.current) cancelAnimationFrame(frameRef.current);
      canvas.remove();
      map.remove();
      mapRef.current = null;
    };
    // Map setup runs once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    clearRoutes();
    heatRef.current = indexHeat(result?.heatmap?.points);
    hourRef.current = 0;
    if (sliderRef.current) sliderRef.current.value = "0";
    paintLabel(0);
    if (!result) {
      drawHeat();
      return;
    }

    const renderer = L.canvas({ padding: 0.5 });
    const bounds = L.latLngBounds([]);
    result.routes.forEach((route) => {
      const group = { casing: [], lines: [], markers: [] };
      route.segments.forEach((segment) => {
        const color = riskMeta(segment.risk).color;
        const casing = L.polyline(segment.coordinates, {
          renderer,
          color: "#1c1915",
          weight: 8,
          opacity: 0.3,
          interactive: false,
        }).addTo(map);
        const line = L.polyline(segment.coordinates, {
          renderer,
          color,
          weight: 4,
          opacity: 0.5,
        }).addTo(map);
        line.on("click", () => onSelectRef.current(route.id));
        bounds.extend(line.getBounds());
        group.casing.push(casing);
        group.lines.push(line);
      });
      route.checkpoints.forEach((checkpoint) => {
        const marker = L.circleMarker([checkpoint.lat, checkpoint.lon], {
          renderer,
          radius: 4,
          color: "#fffdf8",
          weight: 2,
          fillColor: riskMeta(checkpoint.risk).color,
          fillOpacity: 0.5,
        }).addTo(map);
        marker.bindTooltip(
          `${route.label} · ${checkpoint.risk ? riskLabel(checkpoint.risk) : "No forecast"} · mile ${checkpoint.miles_along.toFixed(0)}`,
          { direction: "top", opacity: 0.96 }
        );
        marker.bindPopup(popupHtml(route.label, checkpoint));
        marker.on("click", () => onSelectRef.current(route.id));
        group.markers.push(marker);
      });
      groupsRef.current.set(route.id, group);
    });

    const pin = (place, letter) => {
      const marker = L.marker([place.lat, place.lon], {
        icon: L.divIcon({
          className: "end-pin",
          html: `<span>${letter}</span>`,
          iconSize: [28, 28],
          iconAnchor: [14, 14],
        }),
        zIndexOffset: 800,
      }).addTo(map);
      marker.bindTooltip(place.label, { direction: "top" });
      endsRef.current.push(marker);
      bounds.extend([place.lat, place.lon]);
    };
    pin(result.origin, "A");
    pin(result.destination, "B");
    if (bounds.isValid()) {
      map.fitBounds(bounds, { paddingTopLeft: [36, 36], paddingBottomRight: [36, 120] });
    }
    emphasize(selectedRef.current);
    drawHeat();
  }, [result]);

  useEffect(() => {
    emphasize(selectedId);
  }, [selectedId]);

  return (
    <div className="stage">
      <div ref={hostRef} className="map" />
      <ul className="legend">
        {RISKS.map((item) => (
          <li key={item.id}>
            <i style={{ background: item.color }} />
            {item.label}
          </li>
        ))}
      </ul>
      <div className="forecast">
        <div className="forecast-top">
          <strong>Corridor forecast</strong>
          <span ref={labelRef}>Plan a trip to load the corridor</span>
        </div>
        <input
          ref={sliderRef}
          type="range"
          min="0"
          max="48"
          step="1"
          defaultValue="0"
          disabled={!result}
          aria-label="Forecast hour after departure"
          onInput={(event) => {
            const hour = Number(event.target.value);
            hourRef.current = hour;
            paintLabel(hour);
            drawHeat();
          }}
        />
        <div className="forecast-scale">
          <span>+0 h</span>
          <span>+24 h</span>
          <span>+48 h</span>
        </div>
        <p>Shading uses this load’s wind, rain, and snow rules. Checkpoint colors stay tied to arrival time.</p>
      </div>
    </div>
  );
});

export default MapView;
