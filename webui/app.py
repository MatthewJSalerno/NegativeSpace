"""The NegativeSpace HTTP API. The screens are served by the web container, which
passes /api here (docker/compose.yml, docker/nginx.conf).

Run with: uvicorn webui.app:app --host 0.0.0.0 --port 8000 (from the repository root).
"""
import asyncio
import contextlib
import csv
import io
import json
import sqlite3
from typing import List, Optional

from fastapi import Body, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from engine import ns_db, review
from engine import ns_similarity
from engine import ns_similarity_recovery
from . import catalog, catalog_backups, gallery, lineage, oplog, outcomes, stats
from . import access, matching, security
from . import config, jobs as job_commands
from .config import Config
from .jobs import JobRefused, JobRunner

# The drawer refreshes about once a second (webui-spec 4.1); the engine writes its
# progress snapshot at the same cadence.
PUSH_INTERVAL_SECONDS = 1.0


class PhotoPositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    photo_id: int = Field(ge=1)
    view: str = "all"
    sort: str = "newest"
    match_min: int = Field(default=75, ge=75, le=100)
    group_sets: bool = False
    set_reference: Optional[int] = Field(default=None, ge=1, le=2**63-1)
    page_size: int = Field(default=60, ge=1, le=240)
    q: Optional[str] = None
    similar: bool = False
    suspicious: bool = False
    reason: str = "all"
    undated: bool = False
    dates: Optional[List[str]] = None
    types: Optional[List[str]] = None
    folders: Optional[List[str]] = None
    ids: Optional[List[StrictInt]] = None
    run: Optional[int] = Field(default=None, ge=1, le=2**63-1)


def create_app(cfg: Optional[Config] = None) -> FastAPI:
    cfg = cfg or Config.from_env()
    jobs = JobRunner(cfg)

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        yield
        await run_in_threadpool(jobs.shutdown)

    app = FastAPI(title="NegativeSpace", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.cfg, app.state.jobs = cfg, jobs

    @app.middleware("http")
    async def browser_mutation_boundary(request, call_next):
        if not security.request_host_allowed(request.headers, access.effective(cfg)):
            return JSONResponse({"error": "untrusted_host",
                                 "message": "This address is not allowed. Open an allowed address and add this hostname or IP in Settings → Access, or set NS_ALLOWED_HOSTS in the deployment configuration and recreate the app container."}, status_code=400)
        if request.method not in ("GET", "HEAD", "OPTIONS") and not security.browser_origin_allowed(request.headers):
            return JSONResponse({"error": "cross_origin_request",
                                 "message": "Open NegativeSpace directly to perform this action."}, status_code=403)
        return await call_next(request)

    @app.exception_handler(JobRefused)
    async def job_refused(_request, exc: JobRefused):
        return JSONResponse(exc.body, status_code=exc.status)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc: HTTPException):
        """One error shape for every refusal: {"error": code, "message": text}."""
        if isinstance(exc.detail, dict):
            return JSONResponse(exc.detail, status_code=exc.status_code)
        return await http_exception_handler(request, exc)

    @app.exception_handler(catalog.CatalogUnavailable)
    async def catalog_unavailable(_request, exc: catalog.CatalogUnavailable):
        return JSONResponse({"error": f"catalog_{exc.state}", "message": exc.detail}, status_code=409)

    @app.exception_handler(access.AccessError)
    async def access_error(_request, exc):
        return JSONResponse({"error": exc.code, "message": exc.message}, status_code=exc.status)

    @app.get("/api/v1/access")
    def get_access(request: Request):
        return dict(access.read(cfg), current_host=security.host_name(request.headers["host"]))

    @app.put("/api/v1/access")
    def put_access(request: Request, body: dict = Body(...)):
        return access.save(cfg, body, security.host_name(request.headers["host"]))

    # -- Catalog --------------------------------------------------------------

    @app.get("/api/v1/status")
    def get_status():
        """First-screen state, and the container paths to name in guidance (webui-spec 3)."""
        return dict(catalog.status(cfg.db_path), application_data=str(cfg.base), catalog_backups=str(cfg.backups),
                    version=config.build_version(),
                    active_job=jobs.active())

    @app.post("/api/v1/catalog", status_code=201)
    def create_catalog():
        try:
            return catalog.create(cfg.db_path)
        except FileExistsError as exc:
            raise HTTPException(409, {"error": "catalog_exists", "message": str(exc)})
        except PermissionError as exc:
            raise HTTPException(409, {"error": "appdata_not_writable", "message": str(exc)})

    # -- Settings (revision-checked writes through ns_db) ---------------------

    def _settings():
        return catalog.settings(cfg.db_path, cpus=ns_db.available_cpus(),
                                supported_extensions=ns_db.SUPPORTED_EXTENSIONS)

    @app.get("/api/v1/settings")
    def get_settings():
        return dict(_settings(), job_active=jobs.active() is not None)

    @app.put("/api/v1/settings")
    def put_settings(body: dict = Body(...)):
        """{"values": {key: value}, "revisions": {key: revision}} for the keys changed.
        A revision that moved since it was read is a conflict, never a silent overwrite.
        Saved values apply to jobs started afterwards, never to a running one."""
        values, revisions = body.get("values"), body.get("revisions")
        if not isinstance(values, dict) or not isinstance(revisions, dict) or not values:
            raise HTTPException(400, {"error": "invalid_request", "message": "Send values and their revisions."})
        try:
            with catalog.connect(cfg.db_path) as conn:
                conn.row_factory = None
                ns_db.save_settings(conn, values, expected_revisions=revisions)
        except ns_db.RevisionConflict as exc:
            raise HTTPException(409, {"error": "settings_changed",
                                      "message": f"{exc}. Reload the settings and try again."})
        except ValueError as exc:
            raise HTTPException(400, {"error": "invalid_settings", "message": str(exc)})
        except sqlite3.OperationalError as exc:
            raise HTTPException(503, {"error": "catalog_busy", "message": f"Settings were not saved: {exc}."})
        return dict(_settings(), job_active=jobs.active() is not None)

    # -- What the interface remembers (webui-spec 4.1) ------------------------

    @app.get("/api/v1/ui-state")
    def get_ui_state():
        with catalog.connect(cfg.db_path) as conn:
            conn.row_factory = None
            return ns_db.read_ui_state(conn)

    @app.put("/api/v1/ui-state")
    def put_ui_state(body: dict = Body(...)):
        """{"dismissed_run": 12}: the finished-job banner the user dismissed, kept with the
        catalog so clearing a browser's data or opening another does not bring it back."""
        try:
            with catalog.connect(cfg.db_path) as conn:
                conn.row_factory = None
                return ns_db.save_ui_state(conn, body)
        except ValueError as exc:
            raise HTTPException(400, {"error": "invalid_request", "message": str(exc)})

    @app.post("/api/v1/settings/validate-extension")
    def validate_extension(body: dict = Body(...)):
        ext = body.get("extension")
        if not isinstance(ext, str) or not ext.strip():
            raise HTTPException(400, {"error": "invalid_request", "message": "Send an extension."})
        return ns_db.extension_support(ext.strip())

    @app.get("/api/v1/similar")
    def similar_queue(mode: str = "similar", threshold: float = Query(90, ge=ns_similarity.MIN_SCORE, le=100),
                      sort: str = "matches", q: str = "", page: int = Query(1, ge=1),
                      page_size: int = Query(30, ge=1, le=60)):
        try:
            return matching.queue(cfg.db_path, mode=mode, threshold=threshold, sort=sort, q=q, page=page, page_size=page_size)
        except ValueError as exc:
            raise HTTPException(400, {"error":"invalid_request", "message":str(exc)})

    @app.get("/api/v1/similar/diagnostics")
    def similarity_diagnostics():
        return matching.diagnostics(cfg.db_path)

    @app.get('/api/v1/similar/recovery')
    def similarity_recovery(page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=60),
                            photo_id: Optional[int] = Query(None, ge=1, le=2**63-1)):
        with catalog.connect(cfg.db_path) as conn:
            return ns_similarity_recovery.report(conn, page=page, page_size=page_size, photo_id=photo_id)

    @app.post('/api/v1/similar/recovery', status_code=202)
    def start_similarity_recovery(body: dict = Body(...)):
        if set(body) - {'scope','photo_id','request_id'}:
            raise HTTPException(400, {'error':'invalid_request', 'message':'Unknown recovery option.'})
        run_id = jobs.repair_similarity(body.get('scope'), body.get('photo_id'), body.get('request_id'))
        return outcomes.get_run(cfg.db_path, run_id)

    @app.get("/api/v1/similar/{photo_id}/sets")
    def reference_sets(photo_id: int, threshold: int = Query(90, ge=75, le=100),
                       include: list[int] = Query([]), page: int = Query(1, ge=1),
                       related_page: int = Query(1, ge=1), page_size: int = Query(12, ge=1, le=24)):
        from . import reference_sets
        try:
            return reference_sets.browse(cfg.db_path, photo_id, threshold=threshold, include=include,
                                         page=page, related_page=related_page, page_size=page_size)
        except ValueError as exc:
            raise HTTPException(400, {'error':'invalid_request', 'message':str(exc)})

    @app.get("/api/v1/similar/{photo_id}/counts")
    def similarity_counts(photo_id: int, scope: str = "library"):
        try:
            return matching.counts(cfg.db_path, photo_id, scope=scope)
        except ValueError as exc:
            raise HTTPException(400, {"error": "invalid_request", "message": str(exc)})

    @app.get("/api/v1/similar/{photo_id}/pair/{other_id}")
    def similarity_pair(photo_id: int, other_id: int):
        try:
            return matching.pair(cfg.db_path, photo_id, other_id)
        except matching.PairChanged as exc:
            raise HTTPException(409, {'error':'pair_changed', 'message':str(exc)})

    @app.get("/api/v1/similar/{photo_id}")
    def similar_matches(photo_id: int, mode: str = "similar", threshold: float = Query(90, ge=ns_similarity.MIN_SCORE, le=100),
                        page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=60), scope: str = "library"):
        try:
            return matching.matches(cfg.db_path, photo_id, mode=mode, threshold=threshold, page=page, page_size=page_size, scope=scope)
        except ValueError as exc:
            raise HTTPException(400, {"error":"invalid_request", "message":str(exc)})

    # -- Stats (webui-spec 5.9) -------------------------------------------------

    @app.get("/api/v1/stats")
    def get_stats():
        return stats.library_stats(cfg.db_path, cfg.backups, cfg.base, cfg.source)

    # -- Catalog backups (webui-spec 9) ----------------------------------------

    @app.get("/api/v1/backups")
    def get_backups():
        return dict(catalog_backups.backups(cfg.db_path, cfg.backups, cfg.base), job_active=jobs.active() is not None)

    @app.post("/api/v1/backups")
    def post_backup():
        """Back up now. Waits for the engine; a failed backup is a recorded attempt,
        returned with 200 and its outcome, not an HTTP error."""
        return jobs.backup_now()

    @app.get("/api/v1/backups/{attempt_id}/download")
    def download_backup(attempt_id: int):
        path = catalog_backups.backup_download(cfg.db_path, cfg.backups, attempt_id)
        if path is None:
            raise HTTPException(404, {"error": "backup_unavailable", "message": "Backup file no longer available."})
        return FileResponse(path, filename=path.name, media_type="application/octet-stream")

    # -- Photos ---------------------------------------------------------------

    def _bad_request(exc: ValueError) -> HTTPException:
        return HTTPException(400, {"error": "invalid_request", "message": str(exc)})

    @app.get("/api/v1/photos")
    def get_photos(view: str = "all", sort: str = "newest", q: Optional[str] = None,
                   page: int = Query(1, ge=1), page_size: int = Query(60, ge=1, le=240), undated: bool = False,
                   date: Optional[List[str]] = Query(None), type: Optional[List[str]] = Query(None),
                   folder: Optional[List[str]] = Query(None), match_min: int = Query(75, ge=75, le=100), group_sets: bool = False, set_reference: Optional[int] = Query(None, ge=1, le=2**63-1), run: Optional[int] = Query(None, ge=1, le=2**63-1), similar: bool = False, suspicious: bool = False, reason: str = "all"):
        try:
            return gallery.list_photos(cfg.db_path, view=view, sort=sort, q=q, page=page, page_size=page_size,
                                       undated=undated, dates=date, types=type, folders=folder, root=cfg.source, match_min=match_min, group_sets=group_sets, set_reference=set_reference, run=run, similar=similar, suspicious=suspicious, reason=reason)
        except ValueError as exc:
            raise _bad_request(exc)

    @app.get("/api/v1/photos/timeline")
    def get_timeline(view: str = "all", q: Optional[str] = None, undated: bool = False,
                     date: Optional[List[str]] = Query(None), type: Optional[List[str]] = Query(None),
                     folder: Optional[List[str]] = Query(None), match_min: int = Query(75, ge=75, le=100), group_sets: bool = False, run: Optional[int] = Query(None, ge=1, le=2**63-1), similar: bool = False, suspicious: bool = False, reason: str = "all"):
        try:
            return gallery.timeline(cfg.db_path, view=view, q=q, undated=undated, dates=date, types=type,
                                    folders=folder, root=cfg.source, match_min=match_min, group_sets=group_sets, run=run, similar=similar, suspicious=suspicious, reason=reason)
        except ValueError as exc:
            raise _bad_request(exc)

    @app.get("/api/v1/photos/types")
    def get_types(view: str = "all", q: Optional[str] = None, undated: bool = False,
                  date: Optional[List[str]] = Query(None), folder: Optional[List[str]] = Query(None), match_min: int = Query(75, ge=75, le=100), group_sets: bool = False, run: Optional[int] = Query(None, ge=1, le=2**63-1), similar: bool = False, suspicious: bool = False, reason: str = "all"):
        try:
            return {"types": gallery.file_types(cfg.db_path, view=view, q=q, undated=undated, dates=date,
                                                folders=folder, root=cfg.source, match_min=match_min, group_sets=group_sets, run=run, similar=similar, suspicious=suspicious, reason=reason)}
        except ValueError as exc:
            raise _bad_request(exc)

    @app.get("/api/v1/photos/folders")
    def get_folders(view: str = "all", q: Optional[str] = None, undated: bool = False,
                    date: Optional[List[str]] = Query(None), type: Optional[List[str]] = Query(None),
                    folder: Optional[List[str]] = Query(None), match_min: int = Query(75, ge=75, le=100), group_sets: bool = False, run: Optional[int] = Query(None, ge=1, le=2**63-1), similar: bool = False, suspicious: bool = False, reason: str = "all"):
        """The source's folders with their counts; `folder` names ticked folders, which stay
        listed at 0 but do not narrow the counts (the tree ignores its own filter)."""
        try:
            return gallery.folder_tree(cfg.db_path, cfg.source, view=view, q=q, undated=undated, dates=date,
                                       types=type, keep=folder, match_min=match_min, group_sets=group_sets, run=run, similar=similar, suspicious=suspicious, reason=reason)
        except ValueError as exc:
            raise _bad_request(exc)

    @app.get("/api/v1/photos/ids")
    def get_photo_ids(view: str = "all", q: Optional[str] = None, undated: bool = False,
                      date: Optional[List[str]] = Query(None), type: Optional[List[str]] = Query(None),
                      folder: Optional[List[str]] = Query(None), match_min: int = Query(75, ge=75, le=100), group_sets: bool = False, set_reference: Optional[int] = Query(None, ge=1, le=2**63-1), run: Optional[int] = Query(None, ge=1, le=2**63-1), similar: bool = False, suspicious: bool = False, reason: str = "all"):
        try:
            return gallery.photo_ids(cfg.db_path, view=view, q=q, undated=undated, dates=date, types=type,
                                     folders=folder, root=cfg.source, match_min=match_min, group_sets=group_sets, set_reference=set_reference, run=run, similar=similar, suspicious=suspicious, reason=reason)
        except ValueError as exc:
            raise _bad_request(exc)

    @app.post("/api/v1/photos/position")
    def get_photo_position(body: PhotoPositionRequest):
        try:
            return gallery.photo_position(cfg.db_path, root=cfg.source, **body.model_dump())
        except ValueError as exc:
            raise _bad_request(exc)

    @app.post("/api/v1/photos/selection")
    def get_selection(body: dict = Body(...)):
        """A POST only because a selection's ids are too long for a URL; it reads."""
        try:
            return gallery.photos_by_ids(cfg.db_path, body.get("ids"), sort=body.get("sort", "newest"),
                                         page=body.get("page", 1), page_size=body.get("page_size", 60), match_min=body.get("match_min", 75),
                                         action=body.get("action"))
        except (ValueError, TypeError) as exc:
            raise _bad_request(ValueError(str(exc)))

    @app.get("/api/v1/photos/{photo_id}/review")
    def photo_review(photo_id: int):
        if not 1 <= photo_id <= 2**63-1:
            raise HTTPException(404, {"error": "unknown_photo", "message": "No such photo."})
        with catalog.connect(cfg.db_path) as conn:
            conn.execute('BEGIN')
            found = review.details(conn, photo_id)
        if found is None:
            raise HTTPException(404, {"error": "unknown_photo", "message": "No such photo."})
        return found

    @app.post("/api/v1/photos/{photo_id}/review")
    def decide_review(photo_id: int, body: dict = Body(...)):
        if len(json.dumps(body)) > 8192:
            raise HTTPException(400, {'error': 'invalid_request', 'message': 'Review request is too large.'})
        if type(body.get('photo_id')) is not int or body.get('photo_id') != photo_id:
            raise HTTPException(400, {"error": "invalid_request", "message": "The photo must match the URL."})
        return jobs.review_decision(body)

    @app.get("/api/v1/photos/{photo_id}/inspect")
    def inspect(photo_id: int):
        found = gallery.inspect_photo(cfg.db_path, photo_id)
        if found is None:
            raise HTTPException(404, {"error": "unknown_photo", "message": "No catalogued photo has this id."})
        return found

    @app.get("/api/v1/photos/{photo_id}/lineage")
    def get_lineage(photo_id: int):
        found = lineage.photo_lineage(cfg.db_path, photo_id)
        if found is None:
            raise HTTPException(404, {"error": "unknown_photo", "message": "No such photo."})
        return found

    @app.get("/api/v1/photos/{photo_id}/thumbnail")
    def thumbnail(photo_id: int, size: str = "grid"):
        """The grid thumbnail from the cache, or the 1024px detail preview, which the
        engine makes on first view (--preview). Unavailable is a 404 carrying the
        recorded reason, for the placeholder (webui-spec 4.2.1)."""
        if size not in ("grid", "preview"):
            raise HTTPException(400, {"error": "invalid_request", "message": "size is grid or preview."})
        if size == "preview":
            answer = jobs.preview(photo_id)
            if answer.get("availability") == "present":
                path = catalog.cache_file(cfg.cache, answer["cache_filename"])
                if path:
                    return FileResponse(path, media_type="image/jpeg")
            return JSONResponse({"availability": answer.get("availability", "unavailable"),
                                 "failure_category": answer.get("failure_category"),
                                 "failure_detail": answer.get("failure_detail")}, status_code=404)
        with catalog.connect(cfg.db_path) as conn:
            if not gallery.photo_exists(conn, photo_id):
                raise HTTPException(404, {"error": "unknown_photo", "message": "No catalogued photo has this id."})
            record = gallery.thumbnail_record(conn, photo_id, catalog.GRID_SIZE)
        if record and record[1] == "present":
            path = catalog.cache_file(cfg.cache, record[0])
            if path:
                return FileResponse(path, media_type="image/jpeg")
        return JSONResponse({"availability": record[1] if record and record[1] != "present" else "pending",
                             "failure_category": record[2] if record else None,
                             "failure_detail": record[3] if record else None}, status_code=404)

    # -- The log and the Error Center (webui-spec 5.3, 5.4) ------------------

    def _log_filters(run: Optional[List[int]], status: Optional[List[str]], photo: Optional[int],
                     q: Optional[str], since: Optional[str], until: Optional[str]) -> dict:
        unknown = [s for s in status or [] if s not in catalog.LOG_STATUSES]
        if unknown:
            raise HTTPException(400, {"error": "invalid_request", "message": f"Unknown status: {', '.join(unknown)}."})
        return {"runs": run or None, "statuses": status or None, "photo": photo, "q": q or None,
                "since": since or None, "until": until or None}

    @app.get("/api/v1/operations")
    def get_operations(run: Optional[List[int]] = Query(None), status: Optional[List[str]] = Query(None),
                       photo: Optional[int] = None, q: Optional[str] = None, since: Optional[str] = None,
                       until: Optional[str] = None, page: int = Query(1, ge=1),
                       page_size: int = Query(100, ge=1, le=oplog.LOG_PAGE_MAX)):
        return oplog.list_operations(cfg.db_path, page=page, page_size=page_size,
                                       **_log_filters(run, status, photo, q, since, until))

    @app.get("/api/v1/operations/export")
    def export_operations(format: str = "csv", run: Optional[List[int]] = Query(None),
                          status: Optional[List[str]] = Query(None), photo: Optional[int] = None,
                          q: Optional[str] = None, since: Optional[str] = None, until: Optional[str] = None):
        """The whole filtered log as CSV or JSON, streamed, oldest first."""
        if format not in ("csv", "json"):
            raise HTTPException(400, {"error": "invalid_request", "message": "format is csv or json."})
        filters = _log_filters(run, status, photo, q, since, until)
        with catalog.connect(cfg.db_path):               # refuse with 409 before streaming, not midway
            pass
        columns = ["id", "timestamp", "run_id", "mode", "status", "source_path", "dest_path", "error_message",
                   "photo_id", "photo_status", "recovery", "run_level"]

        def rows_csv():
            out = io.StringIO()
            writer = csv.DictWriter(out, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            for item in oplog.iter_operations(cfg.db_path, **filters):
                writer.writerow(item)
                if out.tell() > 64_000:
                    yield out.getvalue()
                    out.seek(0)
                    out.truncate()
            yield out.getvalue()

        def rows_json():
            yield "["
            for n, item in enumerate(oplog.iter_operations(cfg.db_path, **filters)):
                yield ("," if n else "") + json.dumps({k: item[k] for k in columns})
            yield "]"

        name = f"negativespace-log.{format}"
        return StreamingResponse(rows_csv() if format == "csv" else rows_json(),
                                 media_type="text/csv" if format == "csv" else "application/json",
                                 headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/api/v1/operations/photo-ids")
    def operation_photo_ids(run: Optional[List[int]] = Query(None), status: Optional[List[str]] = Query(None),
                            photo: Optional[int] = None, q: Optional[str] = None, since: Optional[str] = None,
                            until: Optional[str] = None, requested_only: bool = False):
        """The distinct photos behind the filtered operations, for Retry: all of them."""
        return {"photo_ids": oplog.operation_photo_ids(cfg.db_path, requested_only,
                                                         **_log_filters(run, status, photo, q, since, until))}

    @app.get("/api/v1/runs")
    def get_runs(limit: int = Query(100, ge=1, le=500)):
        return {"runs": oplog.list_runs(cfg.db_path, limit=limit)}

    # -- Jobs -----------------------------------------------------------------

    @app.post("/api/v1/jobs/start", status_code=202)
    def start_job(body: dict = Body(...)):
        """{"mode": "index"|"copy"|"move", "file_ids": [...]} or {"source_subdir": "..."}
        or neither for the whole source. 409 while another job runs (webui-spec 5.7)."""
        if set(body) - {"mode", "file_ids", "source_subdir", "request_id"}:
            raise JobRefused(400, {"error": "invalid_request", "message": "Unsupported job fields. Answer safety questions through the original job."})
        run_id = jobs.start(body.get("mode"), body.get("file_ids"), body.get("source_subdir"), body.get("request_id"))
        return outcomes.get_run(cfg.db_path, run_id)

    @app.post("/api/v1/runs/{run_id}/answer", status_code=202)
    def answer_question(run_id: int, body: dict = Body(...)):
        if not {"question", "answer"} <= set(body) or set(body) - {"question", "answer", "request_id"}:
            raise JobRefused(400, {"error": "invalid_request", "message": "Provide question, answer and an optional request_id; the original job supplies the scope."})
        new_id = jobs.answer(run_id, body["question"], body["answer"], body.get("request_id"))
        return outcomes.get_run(cfg.db_path, new_id)

    @app.get("/api/v1/job-requests/{request_id}")
    def lookup_request(request_id: str):
        job_commands.validate_request_id(request_id)
        record = outcomes.request_record(cfg.db_path, request_id)
        return {"state": "accepted", "run": outcomes.get_run(cfg.db_path, record["run_id"])} if record else {"state": "unknown", "run": None}

    @app.post("/api/v1/jobs/{run_id}/cancel", status_code=202)
    def cancel_job(run_id: int):
        jobs.cancel(run_id)
        return {"id": run_id, "cancel_requested": True}

    @app.get("/api/v1/jobs/active")
    def active_job():
        return {"active": jobs.active(), "last": outcomes.last_run(cfg.db_path)}

    @app.get("/api/v1/runs/{run_id}")
    def get_run(run_id: int):
        run = outcomes.get_run(cfg.db_path, run_id)
        if run is None:
            raise HTTPException(404, {"error": "unknown_run", "message": "No such job."})
        return run

    @app.websocket("/api/v1/ws/jobs")
    async def job_stream(ws: WebSocket):
        """The drawer's feed: the active job (or none) and the last finished one, sent
        on connect and whenever either changes, checked about once a second. A new
        connection gets the current state at once, so a refresh or reconnect never
        restarts anything or loses the elapsed time (webui-spec 4.1)."""
        if (not security.request_host_allowed(ws.headers, access.effective(cfg)) or
                not security.browser_origin_allowed(ws.headers)):
            await ws.close(code=1008)
            return
        await ws.accept()
        # The page never sends; waiting on receive is how this loop learns the connection
        # closed, whether the browser left or the server is shutting down. Sending only on
        # a change never touches a closed socket, and uvicorn runs the app's shutdown,
        # which cancels a running job cleanly, only after every connection has ended: a
        # feed that did not notice held docker stop until the container was killed.
        closed = asyncio.ensure_future(ws.receive())
        previous = None
        try:
            while True:
                if not security.request_host_allowed(ws.headers, access.effective(cfg)):
                    await ws.close(code=1008)
                    return
                state = await run_in_threadpool(lambda: {"active": jobs.active(),
                                                         "last": outcomes.last_run(cfg.db_path)})
                encoded = json.dumps(state, sort_keys=True, default=str)
                if encoded != previous:
                    await ws.send_text(encoded)
                    previous = encoded
                await asyncio.wait({closed}, timeout=PUSH_INTERVAL_SECONDS)
                if closed.done():
                    if closed.result()["type"] == "websocket.disconnect":
                        return
                    closed = asyncio.ensure_future(ws.receive())   # a message: ignored
        except (WebSocketDisconnect, RuntimeError):
            return
        finally:
            closed.cancel()

    return app


app = create_app()
