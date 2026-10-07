// The API's shapes (webui/app.py, webui/catalog.py) and a small fetch wrapper.

export type CatalogState = "missing" | "ok" | "incompatible" | "error";

// What Rejects holds now, and what has been emptied from it so far (webui-spec 7.8).
export interface RejectsSummary {
  photos: number;
  bytes: number;
  oldest_rejected_at: string | null;
  emptied: { photos: number; bytes: number };
}

export interface Status {
  state: CatalogState;
  detail: string | null;
  photos: number;
  indexed: boolean;
  library_photos?: number;
  // What a Copy all and a Move all would take, across the whole catalog.
  eligible: { copy: number; move: number };
  copied: number;
  // Rejected after a Copy, their source still in place: a Move removes it (engine-spec 9.5).
  rejected_with_source: number;
  // Null when the catalog cannot be read. `reminder`: past a size or age limit (Settings).
  rejects: (RejectsSummary & {
    reminder: { over_size: boolean; over_age: boolean; bytes_limit: number | null; days_limit: number | null };
  }) | null;
  application_data: string;
  catalog_backups: string;
  // Which build is running: the release, and the branch and commit it was built from.
  version?: { release: string | null; branch: string | null; commit: string | null };
  active_job: Run | null;
}

export type View = "review" | "all" | "unorganized" | "organized" | "similar" | "suspicious" | "rejects";
// A job acting on photos; Reject and Return to library need a selection or a folder.
export type ActionMode = "copy" | "move" | "reject" | "return";
// Where a photo is, for selecting: a selection holds library photos or photos in Rejects,
// never both (webui-spec 2), so each action on it has one meaning.
export type Place = "library" | "rejects";
export const placeOf = (status: string): Place =>
  status === "Rejected" || status === "Rejected_Copied" ? "rejects" : "library";
export type Sort = "newest" | "oldest" | "largest" | "smallest" | "name" | "matches";

export interface PhotoItem {
  id: number;
  status: string;
  file_size: number | null;
  date_taken: string | null;
  date_source: string | null;
  date_warning: string | null;
  filename: string;
  duplicates: number;
  similar_count?: number | null;
  // A Failed photo's latest failure reason, for its badge's hover.
  failure?: string | null;
  // Why a Move kept this Copied photo's original in the source, when one did.
  kept?: string | null;
  // When a photo in Rejects was rejected.
  rejected_at?: string | null;
  review?: Pick<ReviewDetail, "reasons" | "location">;
}

export interface ReviewDetail {
  reasons: { reason: string; label: string; message: string }[];
  history: { id: number; reason: string; action: string; note: string; created_at: string }[];
  revision: number; sha1: string | null; location: string;
}
export interface PhotoPage {
  index_summary?: { last_index: { id: number; started_at: string } | null; photos: number; duplicates: number; small: number; minimum: number | null; unknown_dimensions: number; suspicious: number; undated: number; failed: number; similar: null } | null;
  elsewhere?: Record<string, number>;
  chips?: Record<string, number>;
  reasons?: Record<string, number>;
  items: PhotoItem[];
  page: number;
  page_size: number;
  total: number;
  // The whole library per view (and No capture date within this view), for the buttons.
  counts: Record<View | "undated", number>;
  similarity: { threshold: number; pending: number; unavailable: number } | null;
  // Each view under every filter now on, for the view buttons and for suggesting another
  // view; `undated` is No capture date within this view under the other filters.
  matches: Record<View | "undated", number>;
  // What Rejects holds now, with the Rejects view.
  rejects?: RejectsSummary | null;
}

export interface PhotoPosition {
  position: number | null;
  page: number | null;
  previous_id: number | null;
  next_id: number | null;
}

// What narrows the gallery: the view, the search, No capture date, and the date tree's
// "Show only" years and months ("2023", "2023-06", "none").
export interface BrowseFilters {
  similar?: boolean; suspicious?: boolean; reason?: string;
  set_reference?: number;
  group_sets?: boolean;
  match_min?: number;
  // "job" with `run`: the photos a job recorded, wherever they are now (webui-spec 2).
  view: View | "job";
  run?: number;
  q: string;
  undated: boolean;
  dates?: string[];
  types?: string[];
  folders?: string[];
}

// A source folder in the Folders tree (GET /photos/folders): its path relative to the
// source, the name shown (a folded chain reads "Camera / Nikon D750"), its photos under
// the filters, and what a Copy or Move of it would take, whatever the filters.
export interface FolderNode {
  path: string;
  name: string;
  photos: number;
  eligible: { copy: number; move: number };
  folders: FolderNode[];
}
export interface FolderTree {
  folders: FolderNode[];
  top_files: { photos: number; eligible: { copy: number; move: number } };
  outside: number;
}

function browseQuery(f: BrowseFilters): URLSearchParams {
  const query = new URLSearchParams({ view: f.view });
  if (f.set_reference != null) query.set("set_reference", String(f.set_reference));
  if (f.group_sets) query.set("group_sets", "true");
  if (f.match_min != null) query.set("match_min", String(f.match_min));
  if (f.run != null) query.set("run", String(f.run));
  if (f.similar) query.set("similar", "true");
  if (f.suspicious) query.set("suspicious", "true");
  if (f.reason) query.set("reason", f.reason);
  if (f.q) query.set("q", f.q);
  if (f.undated) query.set("undated", "true");
  (f.dates ?? []).forEach((d) => query.append("date", d));
  (f.types ?? []).forEach((t) => query.append("type", t));
  (f.folders ?? []).forEach((d) => query.append("folder", d));
  return query;
}

export interface SelectionPage {
  items: PhotoItem[];
  page: number;
  page_size: number;
  total: number;
  missing: number[];
  // Those in Rejects: a selection holds one place (Place, below).
  in_rejects?: number[];
  // What each action would take of the selection, for the selection bar.
  actions?: { copy: number; move: number; reject: number; return: number };
  // With `action`: the selected photos that action takes, for its review.
  takes?: number[];
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
  visual_issue: string | null;
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
  date_warning: string | null;
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

export type Verdict = "success" | "partial" | "originals_kept" | "none_succeeded" | "stopped" | "no_change" | "cancelled" | "interrupted" | "running";

export interface Outcome {
  verdict: Verdict;
  succeeded: number;
  failed: number;
  skipped: number;
  cancelled: number;
  run_level_issues: number;
  recovered_earlier_work: number;
  skip_reasons: Record<string, number>;
  // Why the requested work failed, by reason (paths removed), for the hover.
  failure_reasons?: Record<string, number>;
  // A Move's photos copied but not moved, because the original could not be deleted.
  copied_only?: number;
  kept_reasons?: Record<string, number>;
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
  questions?: SafetyQuestion[];
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

export type SafetyQuestion = "source_empty" | "network_destination";
export type SafetyAnswer = "confirm_empty" | "retry" | "copy" | "confirm_move";

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
  small_image_min: Setting<number | null>;
  workers: Setting<number> & { detected: number; host: number; limited_by: "cpu_quota" | "cpu_set" | null };
  exts: Setting<string[]> & { support: ExtensionSupport[] };
  backup_retention: Setting<number>;
  // Null is off.
  rejects_reminder_bytes: Setting<number | null>;
  rejects_reminder_days: Setting<number | null>;
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
  // The jobs this photo was chosen for by hand (a selection), whatever each did with it.
  selected_by: { run_id: number; mode: string; status: string; started_at: string }[];
}

export interface Stats {
  library: {
    photos: number; bytes: number; organized: number; organized_bytes: number; not_organized: number;
    formats: { format: string; photos: number; bytes: number }[];
    cameras: { name: string; photos: number }[];
    lenses: { name: string; photos: number }[];
    megapixels: { band: string; photos: number }[];
    under_1mp: number;
    orientation: { landscape: number; portrait: number; square: number };
    with_location: number;
  };
  dates: {
    per_year: { year: string; photos: number }[];
    oldest: string | null; newest: string | null;
    busiest_day: { day: string; photos: number } | null;
    undated: number; undated_no_date: number; undated_unusable: number; with_time_zone: number;
  };
  duplicates: {
    groups: number; extra_copies: number; bytes: number; saved_at_destination: number;
    move_would_free: number; freed_by_moves: number; near_duplicates: number | null; copies_not_written: number;
    coverage: { last_complete_scan: string | null; established_by_run: number | null;
                scans_with_issues_since: number; run_ids_since: number[] };
    by_folder: { folder: string; files: number; duplicates: number; duplicate_bytes: number }[];
  };
  activity: {
    jobs: Record<string, number>; last_index: string | null; copied: number; moved: number;
    bytes_transferred: number; bytes_per_second: number | null; failures: Record<string, number>;
    renames: number; exif_edits: number | null;
  };
  health: {
    last_backup: string | null; backup_bytes: number; backups: number; unbacked_changes: number;
    catalog_bytes: number; thumbnail_cache: { size: number; photos: number; bytes: number }[];
    destination_check: { at: string; findings: Record<string, number> } | null;
  };
  rejects: RejectsSummary;
}

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public body: Record<string, unknown>) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, {
    method,
    signal,
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

type Submission = { id: string; path: string; body: Record<string, unknown> };
const SUBMISSION_KEY = "ns.pendingSubmission";
let savedSubmission: Submission | null = null;
try {
  const saved = JSON.parse(sessionStorage.getItem(SUBMISSION_KEY) || "null");
  if (saved && /^[a-f0-9]{32}$/.test(saved.id) &&
      (saved.path === "/api/v1/jobs/start" || /^\/api\/v1\/runs\/\d+\/answer$/.test(saved.path)) &&
      saved.body && typeof saved.body === "object" && !Array.isArray(saved.body)) savedSubmission = saved;
} catch { /* No valid saved submission. New submissions still require persistence. */ }
let submissionState = { pending: savedSubmission, checking: !!savedSubmission, resolved: null as Run | null, error: null as string | null };
const submissionListeners = new Set<() => void>();
let submissionPromise: Promise<Run> | null = null;
let resolveSubmission: ((run: Run) => void) | null = null;
let rejectSubmission: ((error: ApiError) => void) | null = null;
let checkingRequest: string | null = null;
let sendingRequest: string | null = null;
let lookupTimer: ReturnType<typeof setTimeout> | null = null;
function notifySubmission() {
  submissionState = { ...submissionState };
  submissionListeners.forEach((listener) => listener());
}
export const submissionSnapshot = () => submissionState;
export const subscribeSubmission = (listener: () => void) => {
  submissionListeners.add(listener);
  return () => { submissionListeners.delete(listener); };
};
function settleSubmission(run: Run | null, error?: ApiError) {
  const wasUncertain = submissionState.checking;
  if (lookupTimer) clearTimeout(lookupTimer);
  lookupTimer = null;
  try { sessionStorage.removeItem(SUBMISSION_KEY); } catch { /* already settled in memory */ }
  const resolve = resolveSubmission, reject = rejectSubmission;
  resolveSubmission = null; rejectSubmission = null; submissionPromise = null;
  submissionState = { pending: null, checking: false, resolved: wasUncertain ? run : null, error: error?.message ?? null };
  notifySubmission();
  if (run) resolve?.(run); else if (error) reject?.(error);
}
export async function checkSubmission() {
  const pending = submissionState.pending;
  if (!pending || checkingRequest === pending.id) return;
  checkingRequest = pending.id;
  try {
    const result = await request<{ state: string; run: Run | null }>("GET", `/api/v1/job-requests/${pending.id}`,
      undefined, AbortSignal.timeout(5000));
    if (submissionState.pending?.id === pending.id && result.state === "accepted" && result.run?.id != null) {
      settleSubmission(result.run);
    }
  } catch { /* An unavailable lookup leaves acceptance unknown. */ }
  finally {
    if (checkingRequest === pending.id) checkingRequest = null;
    if (submissionState.pending?.id === pending.id) {
      submissionState.checking = true;
      notifySubmission();
      if (lookupTimer) clearTimeout(lookupTimer);
      lookupTimer = setTimeout(() => void checkSubmission(), 2000);
    }
  }
}
export async function retrySubmission() {
  const pending = submissionState.pending;
  if (!pending || sendingRequest === pending.id) return;
  sendingRequest = pending.id;
  try {
    const run = await request<Run>("POST", pending.path, { ...pending.body, request_id: pending.id }, AbortSignal.timeout(10000));
    if (run?.id == null) throw new Error("Unrecognized acceptance response");
    if (submissionState.pending?.id === pending.id) settleSubmission(run);
  } catch (error) {
    if (submissionState.pending?.id !== pending.id) return;
    if (error instanceof ApiError && error.status >= 400 && error.status < 500 &&
        !(submissionState.checking && error.code === "job_already_running")) {
      settleSubmission(null, error);
    } else {
      submissionState.checking = true;
      notifySubmission();
      void checkSubmission();
    }
  } finally { if (sendingRequest === pending.id) sendingRequest = null; }
}
function submitJob(path: string, body: Record<string, unknown>): Promise<Run> {
  if (submissionState.pending) {
    if (submissionPromise && submissionState.pending.path === path && JSON.stringify(submissionState.pending.body) === JSON.stringify(body))
      return submissionPromise;
    return Promise.reject(new ApiError(409, "submission_pending", "A previous submission is still being checked. Resolve it before starting another job.", {}));
  }
  const id = Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, "0")).join("");
  const pending = { id, path, body };
  try { sessionStorage.setItem(SUBMISSION_KEY, JSON.stringify(pending)); }
  catch { return Promise.reject(new ApiError(409, "submission_storage", "Allow browser session storage so this job can be tracked before starting it.", {})); }
  submissionState = { pending, checking: false, resolved: null, error: null };
  const promise = new Promise<Run>((resolve, reject) => { resolveSubmission = resolve; rejectSubmission = reject; });
  submissionPromise = promise;
  notifySubmission();
  void retrySubmission();
  return promise;
}

export interface MatchPhoto {
  id: number; filename: string; file_size: number | null; date_taken: string | null;
  status: string; width: number | null; height: number | null; matches?: number; score?: number;
}
export interface MatchPage {
  items: MatchPhoto[]; total: number; page: number; page_size: number;
  state: { photos: number; unavailable: number; pending: number };
  reference?: MatchPhoto | null;
  availability?: "available" | "not_available" | "hash_unavailable";
  largest_pixels?: number | null;
  largest_match?: MatchPhoto | null;
  query_ms?: number;
}

export const MATCH_THRESHOLDS = [75, 80, 85, 90, 95, 100];
type SetPhoto = Pick<PhotoItem, "id" | "filename" | "file_size" | "date_taken" | "date_source" | "date_warning" | "status">;
export interface ReferenceSetsPage {
  reference: SetPhoto;
  references: (SetPhoto & { total: number })[];
  items: (SetPhoto & { references: number[]; direct: boolean; score: number | null })[];
  related: (SetPhoto & { total: number; additional: number })[];
  total: number; page: number; page_size: number; related_total: number; related_page: number;
  threshold: number; state: { pending: number; unavailable: number }; max_related: number;
}

export interface MatchCounts {
  availability: "available" | "not_available" | "hash_unavailable";
  counts: { threshold: number; count: number }[];
  pending: number;
}

// Two photos for side by side.
export interface MatchPair {
  reference: MatchPhoto & { sha1: string }; candidate: MatchPhoto & { sha1: string };
  exact: boolean; distance: number | null; score: number | null;
}
export interface MatchDiagnostics {
  state: MatchPage["state"]; distinct_hashes: number; stored_pairs: number; query_ms: number;
  last_comparison: { run_id: number; started_at: string; updated_at: string; elapsed_seconds: number } | null;
}

export type SimilarityRecoveryPage = {
  items: { id: number; filename: string; kind: string; reason: string; message: string; retryable: boolean; action: "generate" | "recheck" | null }[];
  total: number; retryable: number; generatable: number; state: { unavailable: number; pending: number }; page: number; page_size: number;
};

export const api = {
  review: (id: number) => request<ReviewDetail>("GET", `/api/v1/photos/${id}/review`),
  reviewDecision: (id: number, detail: ReviewDetail, reason: string, action: string, note: string, request_id: string) =>
    request<ReviewDetail>("POST", `/api/v1/photos/${id}/review`, {
      photo_id: id, sha1: detail.sha1, revision: detail.revision, reason, action, note, request_id,
    }),
  referenceSets: (reference: number, threshold: number, included: number[], page: number, relatedPage: number) => {
    const query = new URLSearchParams({ threshold: String(threshold), page: String(page), related_page: String(relatedPage) });
    included.forEach(id => query.append("include", String(id)));
    return request<ReferenceSetsPage>("GET", `/api/v1/similar/${reference}/sets?${query}`);
  },
  similarityRecovery: (page = 1, photoId?: number) => request<SimilarityRecoveryPage>("GET", `/api/v1/similar/recovery?page=${page}${photoId == null ? "" : `&photo_id=${photoId}`}`),
  repairSimilarity: (scope: "missing" | "comparisons", photo_id?: number) => submitJob("/api/v1/similar/recovery", { scope, ...(photo_id == null ? {} : { photo_id }) }),
  run: (id: number) => request<Run>("GET", `/api/v1/runs/${id}`),
  matchCounts: (photo: number) => request<MatchCounts>("GET", `/api/v1/similar/${photo}/counts`),
  matchDiagnostics: () => request<MatchDiagnostics>("GET", "/api/v1/similar/diagnostics"),
  matchPair: (reference: number, candidate: number) =>
    request<MatchPair>("GET", `/api/v1/similar/${reference}/pair/${candidate}`),
  matches: (query: URLSearchParams, photo: number | null = null) =>
    request<MatchPage>("GET", `/api/v1/similar${photo == null ? "" : `/${photo}`}?${query}`),
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
  photoPosition: (params: BrowseFilters & { photo_id: number; sort: Sort; page_size: number; ids?: number[] }) =>
    request<PhotoPosition>("POST", "/api/v1/photos/position", params),
  // Without `dates` for the date tree's counts; with them for the page a jump lands on.
  timeline: (params: BrowseFilters) => request<Timeline>("GET", `/api/v1/photos/timeline?${browseQuery(params)}`),
  types: (params: BrowseFilters) =>
    request<{ types: { type: string; photos: number }[] }>("GET", `/api/v1/photos/types?${browseQuery(params)}`),
  // `folders` here keeps ticked folders listed; the tree's counts ignore its own filter.
  folders: (params: BrowseFilters) => request<FolderTree>("GET", `/api/v1/photos/folders?${browseQuery(params)}`),
  photoIds: (params: BrowseFilters) =>
    request<{ ids: number[]; total: number; in_rejects: number[] }>("GET", `/api/v1/photos/ids?${browseQuery(params)}`),
  selection: (ids: number[], sort: Sort, page: number, page_size: number, match_min = 75, action?: ActionMode) =>
    request<SelectionPage>("POST", "/api/v1/photos/selection", { ids, sort, page, page_size, match_min, ...(action ? { action } : {}) }),
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
  retryIds: (f: LogFilters, requestedOnly = false) =>
    request<{ photo_ids: number[] }>(
      "GET", `/api/v1/operations/photo-ids?${logQuery(f)}${requestedOnly ? "&requested_only=true" : ""}`),
  backups: () => request<Backups>("GET", "/api/v1/backups"),
  backupNow: () => request<BackupAttempt>("POST", "/api/v1/backups"),
  backupDownloadUrl: (id: number) => `/api/v1/backups/${id}/download`,
  stats: () => request<Stats>("GET", "/api/v1/stats"),
  uiState: () => request<{ dismissed_run: number | null }>("GET", "/api/v1/ui-state"),
  saveUiState: (values: { dismissed_run: number }) => request<{ dismissed_run: number | null }>("PUT", "/api/v1/ui-state", values),
  runs: (limit = 100) => request<{ runs: Run[] }>("GET", `/api/v1/runs?limit=${limit}`),
  lineage: (id: number) => request<Lineage>("GET", `/api/v1/photos/${id}/lineage`),
  inspect: (id: number) => request<PhotoDetail>("GET", `/api/v1/photos/${id}/inspect`),
  answerQuestion: (id: number, question: SafetyQuestion, answer: SafetyAnswer) =>
    submitJob(`/api/v1/runs/${id}/answer`, { question, answer }),
  startJob: (body: { mode: "index" | ActionMode; file_ids?: number[]; source_subdir?: string }) =>
    submitJob("/api/v1/jobs/start", body),
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
