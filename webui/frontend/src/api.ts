// The API's shapes (webui/app.py, webui/catalog.py) and a small fetch wrapper.

export type CatalogState = "missing" | "ok" | "incompatible" | "error";

export interface Status {
  state: CatalogState;
  detail: string | null;
  photos: number;
  indexed: boolean;
  // What a Copy all and a Move all would take, across the whole catalog.
  eligible: { copy: number; move: number };
  copied: number;
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

// What narrows the gallery: the view, the search, No capture date, and the date tree's
// "Show only" years and months ("2023", "2023-06", "none").
export interface BrowseFilters {
  view: View;
  q: string;
  undated: boolean;
  dates?: string[];
}

function browseQuery(f: BrowseFilters): URLSearchParams {
  const query = new URLSearchParams({ view: f.view });
  if (f.q) query.set("q", f.q);
  if (f.undated) query.set("undated", "true");
  (f.dates ?? []).forEach((d) => query.append("date", d));
  return query;
}

export interface SelectionPage {
  items: PhotoItem[];
  page: number;
  page_size: number;
  total: number;
  missing: number[];
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
  // Every tag the Index recorded, [name, value], sorted by name.
  metadata: [string, unknown][];
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
  run_counts: Record<string, number>;
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

export interface BackupAttempt {
  attempt_id: number;
  trigger_kind: "manual" | "post_job" | "pre_action";
  related_run_id: number | null;
  started_at: string;
  ended_at: string | null;
  outcome: "succeeded" | "failed" | "interrupted" | null;
  error_category: string | null;
  error_detail: string | null;
  relative_filename: string | null;
  size: number | null;
  compression_format: string | null;
  availability: "present" | "missing" | "unknown" | "pruned" | null;
}

export interface Backups {
  items: BackupAttempt[];
  storage: { ok: boolean; error_category: string | null; error_detail: string | null };
  retention: number;
  automatic_retained: number;
  present_count: number;
  present_bytes: number;
  last_success: string | null;
  unbacked: { count: number; since: string | null; runs: number[] };
  job_active: boolean;
}

export interface LineageFile {
  file_id: number;
  origin_file_id: number | null;
  origin_kind: "indexed" | "copy" | "observed_destination" | null;
  path: string | null;
  role: "source" | "destination" | null;
  presence: "present" | "removed" | "missing" | null;
  sha1_hash: string | null;
  matches: boolean;
  file_size: number | null;
  indexed_path: string | null;
  created_at: string | null;
  photo_id: number | null;
  photo_status: string | null;
}

export interface LineageOperation {
  id: number;
  run_id: number;
  mode: string | null;
  status: string;
  timestamp: string;
  error_message: string | null;
  photo_id: number | null;
  source_path: string | null;
  dest_path: string | null;
  recovery: boolean;
  files: { file_id: number; role: "source" | "destination" | "retained_copy" }[];
}

export interface Lineage {
  photo_id: number;
  sha1: string | null;
  photos: number[];
  files: LineageFile[];
  operations: LineageOperation[];
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
  photos: (params: BrowseFilters & { sort: Sort; page: number; page_size: number }) => {
    const query = browseQuery(params);
    query.set("sort", params.sort);
    query.set("page", String(params.page));
    query.set("page_size", String(params.page_size));
    return request<PhotoPage>("GET", `/api/v1/photos?${query}`);
  },
  // Without `dates` for the date tree's counts; with them for the page a jump lands on.
  timeline: (params: BrowseFilters) => request<Timeline>("GET", `/api/v1/photos/timeline?${browseQuery(params)}`),
  photoIds: (params: BrowseFilters) =>
    request<{ ids: number[]; total: number; limit: number; over_limit: boolean }>("GET", `/api/v1/photos/ids?${browseQuery(params)}`),
  selection: (ids: number[], sort: Sort, page: number, page_size: number) =>
    request<SelectionPage>("POST", "/api/v1/photos/selection", { ids, sort, page, page_size }),
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
  backups: () => request<Backups>("GET", "/api/v1/backups"),
  backupNow: () => request<BackupAttempt>("POST", "/api/v1/backups"),
  backupDownloadUrl: (id: number) => `/api/v1/backups/${id}/download`,
  uiState: () => request<{ dismissed_run: number | null }>("GET", "/api/v1/ui-state"),
  saveUiState: (values: { dismissed_run: number }) => request<{ dismissed_run: number | null }>("PUT", "/api/v1/ui-state", values),
  runs: (limit = 100) => request<{ runs: Run[] }>("GET", `/api/v1/runs?limit=${limit}`),
  lineage: (id: number) => request<Lineage>("GET", `/api/v1/photos/${id}/lineage`),
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
