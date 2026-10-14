export const RISKS = [
  { id: "low", label: "Low", color: "#0f7a4d", score: 1 },
  { id: "moderate", label: "Moderate", color: "#a67908", score: 2 },
  { id: "high", label: "High", color: "#c65312", score: 3 },
  { id: "severe", label: "Severe", color: "#b42318", score: 4 },
  { id: "no_travel", label: "No travel", color: "#6d214f", score: 5 },
];

export const UNKNOWN = { id: "unknown", label: "No forecast", color: "#8d877c" };

const BY_ID = Object.fromEntries([...RISKS, UNKNOWN].map((item) => [item.id, item]));

export function riskMeta(id) {
  return BY_ID[id] || UNKNOWN;
}

export function riskLabel(id) {
  return riskMeta(id).label;
}
