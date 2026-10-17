export const LABELS: Record<string, string> = { date_taken: "Date taken", orientation: "Orientation", camera_make: "Camera make", camera_model: "Camera model", title: "Title", caption: "Caption", keywords: "Keywords", rating: "Rating", creators: "Creators", rights: "Copyright", gps: "Location" };
export const own = (values: Record<string, unknown>, key: string) => Object.prototype.hasOwnProperty.call(values, key);
export function stable(value: unknown): string {
  if (Array.isArray(value)) return JSON.stringify(value.map(stable));
  if (value !== null && typeof value === "object") return JSON.stringify(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => [k, stable(v)]));
  return JSON.stringify(value);
}
// Plain default-language text and its XMP language wrapper mean the same value.
// Keep additional languages, missing fields, arrays and date precision distinct.
export function comparable(value: unknown, key: string) {
  return ["title", "caption", "rights"].includes(key) && typeof value === "string"
    ? { "x-default": value } : value;
}
export function display(values: Record<string, unknown>, key: string) {
  if (!own(values, key)) return "Not recorded";
  const value = values[key];
  if (value === null || value === "" || (typeof value === "object" && Object.keys(value).length === 0)) return "Empty";
  return typeof value === "string" ? (key === "date_taken" ? value.replace("T", " ") : value) : JSON.stringify(value);
}
