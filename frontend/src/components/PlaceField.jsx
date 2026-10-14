import { useEffect, useId, useRef, useState } from "react";
import { geocode } from "../api";

export default function PlaceField({ label, value, place, onText, onPlace }) {
  const listId = useId();
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [hint, setHint] = useState("");
  const boxRef = useRef(null);

  useEffect(() => {
    if (place || value.trim().length < 2) {
      setResults([]);
      setHint("");
      return undefined;
    }
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setBusy(true);
      try {
        const found = await geocode(value.trim(), controller.signal);
        setResults(found);
        setHint(found.length ? "" : "No matching places.");
        setOpen(true);
      } catch (error) {
        if (error.name !== "AbortError") setHint(error.message);
      } finally {
        if (!controller.signal.aborted) setBusy(false);
      }
    }, 320);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [value, place]);

  useEffect(() => {
    function onPointer(event) {
      if (!boxRef.current?.contains(event.target)) setOpen(false);
    }
    document.addEventListener("pointerdown", onPointer);
    return () => document.removeEventListener("pointerdown", onPointer);
  }, []);

  return (
    <label className="field" ref={boxRef}>
      <span>{label}</span>
      <input
        value={value}
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        autoComplete="off"
        placeholder="City, address, or place"
        onChange={(event) => {
          onText(event.target.value);
          onPlace(null);
          setOpen(true);
        }}
        onFocus={() => results.length && setOpen(true)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
        }}
      />
      {place && (
        <small className="locked">
          {place.lat.toFixed(3)}, {place.lon.toFixed(3)}
        </small>
      )}
      {!place && (busy || hint) && <small className="hint">{busy ? "Searching…" : hint}</small>}
      {open && results.length > 0 && (
        <ul className="suggestions" id={listId} role="listbox">
          {results.map((item) => (
            <li key={`${item.lat},${item.lon},${item.label}`}>
              <button
                type="button"
                role="option"
                onClick={() => {
                  onText(item.label);
                  onPlace(item);
                  setOpen(false);
                }}
              >
                {item.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </label>
  );
}
