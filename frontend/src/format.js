export function formatWhen(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function formatMiles(value) {
  if (value == null || Number.isNaN(value)) return "—";
  return `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 })} mi`;
}

export function formatLoad(value) {
  return `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 0 })} lb`;
}

export function defaultDepartureValue() {
  const date = new Date();
  date.setMinutes(0, 0, 0);
  date.setHours(date.getHours() + 1);
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
