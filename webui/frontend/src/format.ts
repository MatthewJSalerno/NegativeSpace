// Display rules for numbers, sizes and times (webui-spec 10).

export function count(n: number): string {
  return n.toLocaleString();
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${count(n)} ${n === 1 ? one : many}`;
}

export function bytes(n: number | null | undefined): string {
  if (n == null) return "unknown size";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = n;
  let unit = 0;
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000;
    unit += 1;
  }
  return `${value >= 10 || unit === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[unit]}`;
}

// A photo's recorded date is a wall-clock time. With no recorded offset its time
// zone is unknown: show it as written, never shifted to the browser's zone.
export function photoDate(iso: string | null, withTime = true): string {
  if (!iso) return "No date";
  const [date, time = ""] = iso.split("T");
  return withTime && time ? `${date} ${time.slice(0, 8)}` : date;
}

export function isFallbackDate(source: string | null): boolean {
  return source === "file_mtime";
}

// Application history (jobs, operations) is stored as UTC instants: show local
// time with the zone named.
export function instant(iso: string | null | undefined): string {
  if (!iso) return "unknown";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium", timeZoneName: "short" });
}

export function duration(ms: number): string {
  if (ms < 1000) return "under a second";
  const s = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const two = (v: number) => String(v).padStart(2, "0");
  return `${two(h)}:${two(m)}:${two(sec)}`;
}
