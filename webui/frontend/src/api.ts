// The API's shapes (webui/app.py, webui/catalog.py) and a small fetch wrapper.

export type CatalogState = "missing" | "ok" | "incompatible" | "error";

export interface Status {
  state: CatalogState;
  detail: string | null;
  photos: number;
  indexed: boolean;
  application_data: string;
  catalog_backups: string;
  active_job: Run | null;
}

export type View = "all" | "unorganized" | "organized";
export type Sort = "newest" | "oldest" | "largest" | "smallest" | "name";

export interface PhotoItem {
  id: number;
  status: string;
  file_size: number | null;
  date_taken: string | null;
  date_source: string | null;
  filename: string;
  duplicates: number;
}

export interface PhotoPage {
  items: PhotoItem[];
  page: number;
  page_size: number;
  total: number;
  counts: Record<View | "undated", number>;
}

export interface Timeline {
  months: { month: string; count: number }[];
  undated: number;
}

export interface Copy {
  id: number;
  status: string;
  source_path: string | null;
  dest_path: string | null;
  file_size: number | null;
}

export interface PhotoDetail {
  id: number;
  status: string;
  filename: string;
  source_path: string | null;
  dest_path: string | null;
  dest_path_is_projection: boolean;
  has_collision_rename: boolean;
  file_size: number | null;
  file_modified: number | null;
  date_taken: string | null;
  date_source: string | null;
  date_offset: string | null;
  exif_dates: { field: "taken" | "digitized" | "modified"; value: string; offset: string | null }[];
  camera: string | null;
  iso: number | string | null;
  aperture: number | string | null;
  shutter: number | string | null;
  width: number | null;
  height: number | null;
  sha1: string | null;
  phash: string | null;
  duplicates: Copy[];
  thumbnail: { availability: string; failure_category: string | null; failure_detail: string | null };
}

export interface Phase {
  phase: string;
  total: number | null;
  done: number;
  counts: Record<string, number>;
  started_at: string;
  updated_at: string;
}

export type Verdict = "success" | "partial" | "failed" | "no_change" | "cancelled" | "interrupted" | "running";

export interface Outcome {
  verdict: Verdict;
  succeeded: number;
  failed: number;
  skipped: number;
  cancelled: number;
  run_level_issues: number;
  recovered_earlier_work: number;
  skip_reasons: Record<string, number>;
  total: number | null;
  counts: Record<string, number>;
}

export interface Run {
  id: number | null;
  mode: string | null;
  status: string;
  started_at?: string;
  ended_at?: string | null;
  targeting?: Record<string, unknown> | null;
  progress?: Phase[];
  outcome?: Outcome;
  presented_status?: string;
  awaiting_reconciliation?: boolean;
  cancellable?: boolean;
  unrecorded?: boolean;
}

export interface JobState {
  active: Run | null;
  last: Run | null;
}

export interface Setting<T> {
  value: T;
  revision: number;
  default: T;
}

export interface ExtensionSupport {
  extension: string;
  supported: boolean;
  warning: string | null;
}

export interface Settings {
  workers: Setting<number> & { detected: number; host: number; limited_by: "cpu_quota" | "cpu_set" | null };
  exts: Setting<string[]> & { support: ExtensionSupport[] };
  backup_retention: Setting<number>;
  job_active: boolean;
}

export interface Operation {
  id: number;
  run_id: number;
  mode: string | null;
  photo_id: number | null;
  timestamp: string;
  source_path: string | null;
  dest_path: string | null;
  status: string;
  error_message: string | null;
  photo_status: string | null;
  recovery: boolean;
  run_level: boolean;
}

export interface OperationPage {
  items: Operation[];
  page: number;
  page_size: number;
  total: number;
  status_counts: Record<string, number>;
}

export interface LogFilters {
  run: number[];
  status: string[];
  photo: number | null;
  q: string;
  since: string;
  until: string;
}

export function logQuery(f: LogFilters): URLSearchParams {
  const p = new URLSearchParams();
  f.run.forEach((r) => p.append("run", String(r)));
  f.status.forEach((s) => p.append("status", s));
  if (f.photo != null) p.set("photo", String(f.photo));
  if (f.q) p.set("q", f.q);
  if (f.since) p.set("since", f.since);
  if (f.until) p.set("until", f.until);
  return p;
}

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public body: Record<string, unknown>) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    const code = (data && (data.error as string)) || `http_${response.status}`;
    const message = (data && (data.message as string)) || `The server answered ${response.status}.`;
    throw new ApiError(response.status, code, message, data ?? {});
  }
  return data as T;
}

export const api = {
  status: () => request<Status>("GET", "/api/v1/status"),
  createCatalog: () => request<Status>("POST", "/api/v1/catalog"),
  settings: () => request<Settings>("GET", "/api/v1/settings"),
  saveSettings: (values: Record<string, unknown>, revisions: Record<string, number>) =>
    request<Settings>("PUT", "/api/v1/settings", { values, revisions }),
  validateExtension: (extension: string) =>
    request<ExtensionSupport>("POST", "/api/v1/settings/validate-extension", { extension }),
  photos: (params: { view: View; sort: Sort; q: string; page: number; page_size: number; undated: boolean }) => {
    const query = new URLSearchParams({
      view: params.view, sort: params.sort, page: String(params.page), page_size: String(params.page_size),
    });
    if (params.q) query.set("q", params.q);
    if (params.undated) query.set("undated", "true");
    return request<PhotoPage>("GET", `/api/v1/photos?${query}`);
  },
  timeline: (params: { view: View; q: string; undated: boolean }) => {
    const query = new URLSearchParams({ view: params.view });
    if (params.q) query.set("q", params.q);
    if (params.undated) query.set("undated", "true");
    return request<Timeline>("GET", `/api/v1/photos/timeline?${query}`);
  },
  operations: (f: LogFilters, page: number, pageSize: number) => {
    const p = logQuery(f);
    p.set("page", String(page));
    p.set("page_size", String(pageSize));
    return request<OperationPage>("GET", `/api/v1/operations?${p}`);
  },
  exportUrl: (f: LogFilters, format: "csv" | "json") => {
    const p = logQuery(f);
    p.set("format", format);
    return `/api/v1/operations/export?${p}`;
  },
  retryIds: (f: LogFilters) =>
    request<{ photo_ids: number[]; more_than_limit: boolean; limit: number }>("GET", `/api/v1/operations/photo-ids?${logQuery(f)}`),
  runs: () => request<{ runs: Run[] }>("GET", "/api/v1/runs"),
  inspect: (id: number) => request<PhotoDetail>("GET", `/api/v1/photos/${id}/inspect`),
  startJob: (body: { mode: "index" | "copy" | "move"; file_ids?: number[]; source_subdir?: string }) =>
    request<Run>("POST", "/api/v1/jobs/start", body),
  cancelJob: (id: number) => request<{ id: number }>("POST", `/api/v1/jobs/${id}/cancel`),
  thumbnailUrl: (id: number, size: "grid" | "preview" = "grid") =>
    `/api/v1/photos/${id}/thumbnail${size === "preview" ? "?size=preview" : ""}`,
  // Why a thumbnail is missing: the 404 body carries the recorded reason.
  thumbnailReason: async (id: number, size: "grid" | "preview" = "grid") => {
    const response = await fetch(api.thumbnailUrl(id, size));
    if (response.ok) return null;
    try {
      return (await response.json()) as { availability: string; failure_category: string | null; failure_detail: string | null };
    } catch {
      return { availability: "unavailable", failure_category: null, failure_detail: null };
    }
  },
};
