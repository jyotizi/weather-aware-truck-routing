async function readError(response) {
  try {
    const body = await response.json();
    if (body && body.detail) return body.detail;
  } catch {
    /* The server didn't return JSON. */
  }
  return "The request failed. Try again.";
}

export async function geocode(query, signal) {
  const response = await fetch(`/api/geocode/?q=${encodeURIComponent(query)}`, { signal });
  if (!response.ok) throw new Error(await readError(response));
  const body = await response.json();
  return body.results || [];
}

export async function planTrip(payload, signal) {
  const response = await fetch("/api/plan/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}
