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
from pathlib import Path
from typing import List, Optional

from fastapi import Body, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

import ns_db
from . import catalog
from .config import Config, build_version
from .jobs import JobRefused, JobRunner

# The drawer refreshes about once a second (webui-spec 4.1); the engine writes its
# progress snapshot at the same cadence.
PUSH_INTERVAL_SECONDS = 1.0


def create_app(cfg: Optional[Config] = None) -> FastAPI:
    cfg = cfg or Config.from_env()
    jobs = JobRunner(cfg)

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        yield
        await run_in_threadpool(jobs.shutdown)

    app = FastAPI(title="NegativeSpace", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.cfg, app.state.jobs = cfg, jobs

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

    # -- Catalog --------------------------------------------------------------

    @app.get("/api/v1/status")
    def get_status():
        """First-screen state, and the container paths to name in guidance (webui-spec 3)."""
        return dict(catalog.status(cfg.db_path), application_data=str(cfg.base), catalog_backups=str(cfg.backups),
                    version=build_version(),
                    active_job=jobs.active())

    @app.post("/api/v1/catalog", status_code=201)
    def create_catalog():
        try:
            return catalog.create(cfg.db_path)
        except FileExistsError as exc:
            raise HTTPException(409, {"error": "catalog_exists", "message": str(exc)})
        except PermissionError as exc:
            raise HTTPException(409, {"error": "appdata_not_writable", "message": str(exc)})

    # -- Settings (the API's only catalog write, through ns_db) ---------------

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

    # -- Stats (webui-spec 5.9) -------------------------------------------------

    @app.get("/api/v1/stats")
    def get_stats():
        return catalog.library_stats(cfg.db_path, cfg.backups, cfg.base, cfg.source)

    # -- Catalog backups (webui-spec 9) ----------------------------------------

    @app.get("/api/v1/backups")
    def get_backups():
        return dict(catalog.backups(cfg.db_path, cfg.backups, cfg.base), job_active=jobs.active() is not None)

    @app.post("/api/v1/backups")
    def post_backup():
        """Back up now. Waits for the engine; a failed backup is a recorded attempt,
        returned with 200 and its outcome, not an HTTP error."""
        return jobs.backup_now()

    @app.get("/api/v1/backups/{attempt_id}/download")
    def download_backup(attempt_id: int):
        path = catalog.backup_download(cfg.db_path, cfg.backups, attempt_id)
        if path is None:
            raise HTTPException(404, {"error": "backup_unavailable", "message": "Backup file no longer available."})
        return FileResponse(path, filename=path.name, media_type="application/octet-stream")

    # -- Photos ---------------------------------------------------------------

    def _bad_request(exc: ValueError) -> HTTPException:
        return HTTPException(400, {"error": "invalid_request", "message": str(exc)})

    @app.get("/api/v1/photos")
    def get_photos(view: str = "all", sort: str = "newest", q: Optional[str] = None,
                   page: int = Query(1, ge=1), page_size: int = Query(60, ge=1, le=240), undated: bool = False,
                   date: Optional[List[str]] = Query(None), type: Optional[List[str]] = Query(None)):
        try:
            return catalog.list_photos(cfg.db_path, view=view, sort=sort, q=q, page=page, page_size=page_size,
                                       undated=undated, dates=date, types=type)
        except ValueError as exc:
            raise _bad_request(exc)

    @app.get("/api/v1/photos/timeline")
    def get_timeline(view: str = "all", q: Optional[str] = None, undated: bool = False,
                     date: Optional[List[str]] = Query(None), type: Optional[List[str]] = Query(None)):
        try:
            return catalog.timeline(cfg.db_path, view=view, q=q, undated=undated, dates=date, types=type)
        except ValueError as exc:
            raise _bad_request(exc)

    @app.get("/api/v1/photos/types")
    def get_types(view: str = "all", q: Optional[str] = None, undated: bool = False,
                  date: Optional[List[str]] = Query(None)):
        try:
            return {"types": catalog.file_types(cfg.db_path, view=view, q=q, undated=undated, dates=date)}
        except ValueError as exc:
            raise _bad_request(exc)

    @app.get("/api/v1/photos/ids")
    def get_photo_ids(view: str = "all", q: Optional[str] = None, undated: bool = False,
                      date: Optional[List[str]] = Query(None), type: Optional[List[str]] = Query(None)):
        try:
            return catalog.photo_ids(cfg.db_path, view=view, q=q, undated=undated, dates=date, types=type)
        except ValueError as exc:
            raise _bad_request(exc)

    @app.post("/api/v1/photos/selection")
    def get_selection(body: dict = Body(...)):
        """A POST only because a selection of 1,000 ids is too long for a URL; it reads."""
        try:
            return catalog.photos_by_ids(cfg.db_path, body.get("ids"), sort=body.get("sort", "newest"),
                                         page=body.get("page", 1), page_size=body.get("page_size", 60))
        except (ValueError, TypeError) as exc:
            raise _bad_request(ValueError(str(exc)))

    @app.get("/api/v1/photos/{photo_id}/inspect")
    def inspect(photo_id: int):
        found = catalog.inspect_photo(cfg.db_path, photo_id)
        if found is None:
            raise HTTPException(404, {"error": "unknown_photo", "message": "No catalogued photo has this id."})
        return found

    @app.get("/api/v1/photos/{photo_id}/lineage")
    def lineage(photo_id: int):
        found = catalog.photo_lineage(cfg.db_path, photo_id)
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
            if not catalog.photo_exists(conn, photo_id):
                raise HTTPException(404, {"error": "unknown_photo", "message": "No catalogued photo has this id."})
            record = catalog.thumbnail_record(conn, photo_id, catalog.GRID_SIZE)
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
                       page_size: int = Query(100, ge=1, le=catalog.LOG_PAGE_MAX)):
        return catalog.list_operations(cfg.db_path, page=page, page_size=page_size,
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
            for item in catalog.iter_operations(cfg.db_path, **filters):
                writer.writerow(item)
                if out.tell() > 64_000:
                    yield out.getvalue()
                    out.seek(0)
                    out.truncate()
            yield out.getvalue()

        def rows_json():
            yield "["
            for n, item in enumerate(catalog.iter_operations(cfg.db_path, **filters)):
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
        """The distinct photos behind the filtered operations, for Retry. More than the
        job limit is reported, never cut silently."""
        from .jobs import MAX_FILE_IDS
        ids = catalog.operation_photo_ids(cfg.db_path, MAX_FILE_IDS, requested_only,
                                          **_log_filters(run, status, photo, q, since, until))
        return {"photo_ids": ids[:MAX_FILE_IDS], "more_than_limit": len(ids) > MAX_FILE_IDS, "limit": MAX_FILE_IDS}

    @app.get("/api/v1/runs")
    def get_runs(limit: int = Query(100, ge=1, le=500)):
        return {"runs": catalog.list_runs(cfg.db_path, limit=limit)}

    # -- Jobs -----------------------------------------------------------------

    @app.post("/api/v1/jobs/start", status_code=202)
    def start_job(body: dict = Body(...)):
        """{"mode": "index"|"copy"|"move", "file_ids": [...]} or {"source_subdir": "..."}
        or neither for the whole source. 409 while another job runs (webui-spec 5.7)."""
        run_id = jobs.start(body.get("mode"), body.get("file_ids"), body.get("source_subdir"))
        return catalog.get_run(cfg.db_path, run_id)

    @app.post("/api/v1/jobs/{run_id}/cancel", status_code=202)
    def cancel_job(run_id: int):
        jobs.cancel(run_id)
        return {"id": run_id, "cancel_requested": True}

    @app.get("/api/v1/jobs/active")
    def active_job():
        return {"active": jobs.active(), "last": catalog.last_run(cfg.db_path)}

    @app.get("/api/v1/runs/{run_id}")
    def get_run(run_id: int):
        run = catalog.get_run(cfg.db_path, run_id)
        if run is None:
            raise HTTPException(404, {"error": "unknown_run", "message": "No such job."})
        return run

    @app.websocket("/api/v1/ws/jobs")
    async def job_stream(ws: WebSocket):
        """The drawer's feed: the active job (or none) and the last finished one, sent
        on connect and whenever either changes, checked about once a second. A new
        connection gets the current state at once, so a refresh or reconnect never
        restarts anything or loses the elapsed time (webui-spec 4.1)."""
        await ws.accept()
        previous = None
        try:
            while True:
                state = await run_in_threadpool(lambda: {"active": jobs.active(),
                                                         "last": catalog.last_run(cfg.db_path)})
                encoded = json.dumps(state, sort_keys=True, default=str)
                if encoded != previous:
                    await ws.send_text(encoded)
                    previous = encoded
                await asyncio.sleep(PUSH_INTERVAL_SECONDS)
        except (WebSocketDisconnect, RuntimeError):
            return

    return app


app = create_app()
