"""The command line: arguments, the single-instance lock and the job each mode runs."""

import argparse
import contextlib
import json
import signal
import sqlite3
import sys
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import List

from engine.ns_db import PhotoStatus, RunStatus, SUPPORTED_EXTENSIONS
from engine import (
    backups, constants, deps, destinations, fileinfo, maintenance, ns_db, ns_similarity, reconcile,
    relocate, runtime, scan, store, targeting, thumbnails, transfer)


def positive_int(value: str) -> int:
    """argparse type for --workers: zero or a negative count is an error, not the default."""
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"must be a whole number, got: {value}")
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got: {value}")
    return number


def request_id_arg(value: str) -> str:
    """argparse type for --request-id: the same bounds ns_db.create_run enforces,
    reported as a usage error instead of a traceback after the lock is taken."""
    if not value or len(value) > 256:
        raise argparse.ArgumentTypeError("must be 1 to 256 characters")
    return value


def main():
    parser = argparse.ArgumentParser(
        prog="engine", description="NegativeSpace - Photo Collection Organizer (Engine)",
        epilog="WARNING: Source and destination must map to separate, non-overlapping underlying "
               "folders, including on network shares. Never mount the same folder at both paths "
               "or nest one inside the other. Different container paths do not ensure separate "
               "storage. Overlapping mounts can cause unintended file deletion and are not "
               "reliably detected by the engine."
    )
    parser.add_argument("--source", default="/data/source", help="Path to source directory (default: /data/source).")
    parser.add_argument("--dest", default="/data/dest", help="Path to destination directory (default: /data/dest).")
    parser.add_argument("--base", default="/appdata", help="Base directory for DB and logs (default: /appdata).")
    parser.add_argument(
        "--workers", type=positive_int, default=None,
        help=f"Worker process count for hashing/date resolution (default: {constants.MAX_WORKER_PROCESSES}, the CPUs this container may use)."
    )
    parser.add_argument(
        "--exts", type=str, default=None,
        help="Comma-separated list of extensions to scan (e.g. '.jpg,.png'), replacing the built-in default set. "
             "Only affects directory scanning, not --file-ids targeting."
    )
    parser.add_argument(
        "--cache", default="/cache",
        help="Directory holding generated thumbnails and previews (default: /cache). Written "
             "during scans and cache-generation commands; the transfer phase — copy, verify, "
             "delete — never touches it. Everything under it is reproducible from the photo "
             "it came from, so it is safe to delete and should be excluded from backups."
    )
    parser.add_argument(
        "--backups", default="/backups",
        help="Directory holding catalog backups (default: /backups). Must be separate storage "
             "from --base: a backup inside the thing it backs up dies with it. Never created "
             "or substituted: missing or unwritable storage is recorded as a failed backup."
    )
    parser.add_argument(
        "--no-thumbnails", action="store_true",
        help="Skip thumbnail generation during the scan. Indexing is otherwise unchanged; "
             "the gallery shows placeholders until a later run generates them."
    )
    parser.add_argument(
        "--force-rehash", action="store_true",
        help="Re-read every file even if its size and modification time are unchanged since the "
             "last Index. Normally unchanged files are skipped without being read at all, which "
             "is what makes re-indexing fast; use this to verify content that changed without "
             "size or mtime moving."
    )
    parser.add_argument(
        "--confirm-network-destination", action="store_true",
        help="Move to a network-share destination anyway. Without it a Move there stops before "
             "copying or deleting anything and asks, because a share can report a copy saved "
             "before it is on the server's disk. Confirm only for a share exported 'sync'; "
             "otherwise use --copy, which never deletes a source."
    )
    parser.add_argument(
        "--confirm-source-empty", action="store_true",
        help="Answer the needs-attention question an empty --source raises: the folder really "
             "is empty, not unplugged. Photos whose exact content is on the destination are "
             "then recorded as found there, and the rest as missing."
    )
    parser.add_argument(
        "--request-id", type=request_id_arg, default=None,
        help="Caller-chosen ID for this submission, stored with the run before any file work. "
             "Repeating it with identical arguments starts nothing and exits "
             f"{constants.EXIT_REQUEST_ALREADY_ACCEPTED}, logging the run it already created; repeating it "
             f"with different arguments starts nothing and exits {constants.EXIT_REQUEST_CONFLICT}. "
             "A deliberate new attempt needs a new ID."
    )
    targeting_group = parser.add_mutually_exclusive_group()
    targeting_group.add_argument(
        "--file-ids", type=targeting.parse_file_ids, default=None,
        help="Comma-separated list of existing photo IDs (from a prior Index) to target. "
             "Bypasses the full directory scan — processes exactly these already-cataloged files."
    )
    targeting_group.add_argument(
        "--file-ids-from", type=str, default=None, metavar="PATH",
        help="Photo IDs to target, read from a selection file (ns_db.write_selection_file): how the "
             "web interface passes a selection of any size, which the command line's length limit "
             "would not allow as --file-ids. Needs --request-id, which the file must name. The job is "
             "refused whole, touching nothing, if the file is damaged or any photo is no longer "
             "catalogued in this source. The selection is recorded with the run; the file is not kept."
    )
    targeting_group.add_argument(
        "--source-subdir", type=str, default=None,
        help="Path, relative to --source, to scope this run to. Queries already-cataloged rows whose "
             "source_path falls under <source>/<subdir> instead of walking the filesystem or enumerating "
             "photo IDs. Only reflects files known as of the last Index over that path. "
             "Mutually exclusive with --file-ids and --file-ids-from."
    )

    # Only one mode may be active per run — default (no flag) is the existing
    # Index: full scan + hash + date/dest-path resolution, no physical
    # action. The flags below are mutually exclusive with each other.
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--move", action="store_true",
        help="Execute physical migration (Copy-Verify-Delete, source files are moved/deleted)."
    )
    mode_group.add_argument(
        "--copy", action="store_true",
        help="Non-destructive: copy source files to destination, verified, but never delete or modify the source."
    )
    mode_group.add_argument(
        "--preview", type=int, metavar="PHOTO_ID", default=None,
        help="Print, as one line of JSON, the 1024px detail preview for this catalogued photo, "
             "generating it on first request. Takes no engine lock and changes no photo file, "
             "so it works while a job runs. The preview path in the JSON is relative to --cache."
    )
    mode_group.add_argument(
        "--clear-previews", action="store_true",
        help="Remove every cached 1024px detail preview and print what was freed as one line of "
             "JSON. Grid thumbnails are kept. Takes no engine lock, like --preview."
    )
    mode_group.add_argument(
        "--rebuild-thumbnails", choices=("missing", "all"), default=None, metavar="{missing,all}",
        help="Run a job that makes grid thumbnails from any catalogued copy: 'missing' only those "
             "not on disk, 'all' every one. Takes the engine lock; needs no --source."
    )
    mode_group.add_argument(
        "--check-destination", choices=("quick", "full"), default=None, metavar="{quick,full}",
        help="Run a read-only job that checks every catalogued copy under --dest (ok, missing, "
             "changed, unreadable) and lists files the catalog did not put there. 'quick' trusts an "
             "unchanged size and date; 'full' reads every file. Takes the engine lock."
    )
    mode_group.add_argument(
        "--rename", type=int, metavar="PHOTO_ID", default=None,
        help="Give a delivered photo's destination file a new name (--name), keeping its date "
             "folder and real extension; a taken name gets a _N suffix. Backs up the catalog first. "
             "Takes the engine lock. With --dry-run, prints the resulting path as JSON instead."
    )
    mode_group.add_argument(
        "--rename-candidates", type=int, metavar="PHOTO_ID", default=None,
        help="Print, as one line of JSON, the filenames this photo's content has carried across "
             "its duplicate group. Read only; takes no lock."
    )
    mode_group.add_argument(
        "--backup-now", action="store_true",
        help="Write one manual catalog backup to --backups and exit. Takes the engine lock, so it "
             "is refused while a job runs. Touches no photo and needs no --source."
    )
    mode_group.add_argument(
        "--reject", action="store_true",
        help="Move the selected organized photos (--file-ids, --file-ids-from or --source-subdir) from dest/library "
             "to the same folders under dest/rejects, and mark them Rejected. Nothing is deleted: "
             "the user empties dest/rejects. Backs up the catalog first. Takes the engine lock."
    )
    mode_group.add_argument(
        "--return-to-library", action="store_true",
        help="Move the selected rejected photos (--file-ids, --file-ids-from or --source-subdir) from dest/rejects "
             "back to their date folder in dest/library. Backs up the catalog first. Takes the "
             "engine lock."
    )
    parser.add_argument("--name", default=None, help="The new name for --rename.")
    parser.add_argument("--dry-run", action="store_true",
                        help="With --rename: print where the file would go, and change nothing.")
    mode_group.add_argument('--repair-similarity', choices=('missing','comparisons'),
                            help='Recover missing visual hashes from destination files or resume stored-hash comparisons; never edits photos.')
    parser.add_argument('--repair-photo', type=int, default=None, help='Limit missing-hash recovery to one destination photo identity.')
    mode_group.add_argument('--review-decision', action='store_true',
                            help='Record a catalog-only review decision supplied as JSON on standard input; changes no photo files.')
    args = parser.parse_args()
    if args.repair_photo is not None and (args.repair_photo < 1 or args.repair_photo > 2**63-1 or args.repair_similarity != 'missing'):
        parser.error('--repair-photo requires --repair-similarity missing and a positive photo ID.')
    if args.rename is not None and not args.name:
        parser.error("--rename needs --name.")
    if (args.name is not None or args.dry_run) and args.rename is None:
        parser.error("--name and --dry-run go with --rename.")
    if args.file_ids_from is not None:
        if not args.request_id:
            parser.error("--file-ids-from needs --request-id, which the selection file names.")
        try:
            args.file_ids = ns_db.read_selection_file(args.file_ids_from, args.request_id)
        except ns_db.SelectionRefused as exc:
            parser.error(f"--file-ids-from: {exc}. Nothing was started.")
        finally:
            targeting._release_selection_lease()
    if (args.reject or args.return_to_library) and not (args.file_ids or args.source_subdir):
        parser.error("--reject and --return-to-library need --file-ids, --file-ids-from or --source-subdir.")
    if args.rebuild_thumbnails and args.no_thumbnails:
        parser.error("--rebuild-thumbnails makes thumbnails; it cannot be combined with --no-thumbnails.")

    start_method = deps.configure_multiprocessing_start_method()
    worker_count = args.workers if args.workers else constants.MAX_WORKER_PROCESSES
    active_extensions = scan.normalize_extensions(args.exts) if args.exts else SUPPORTED_EXTENSIONS

    # 1. Resolve Base Path & Setup Subdirectories
    base_dir = Path(args.base).resolve()
    db_dir = base_dir / "db"
    log_dir = base_dir / "logs"
    db_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / constants.DB_FILENAME

    # 2. Configure Logging
    # --preview answers on stdout in JSON for the API, so its log goes to the file only.
    answers_in_json = (args.review_decision or args.preview is not None or args.clear_previews or args.rename_candidates is not None
                       or (args.rename is not None and args.dry_run))
    runtime.configure_logging(log_dir, console=not answers_in_json)
    if args.preview is not None:
        # Before the lock on purpose: a preview changes no photo file (see preview_for_photo).
        result = thumbnails.preview_for_photo(db_path, Path(args.cache).resolve(), args.preview)
        print(json.dumps(result, sort_keys=True))
        sys.exit(0 if result["availability"] == "present" else 1)
    if args.clear_previews:
        result = thumbnails.clear_previews(db_path, Path(args.cache).resolve())
        print(json.dumps(result, sort_keys=True))
        sys.exit(1 if result["not_removed"] else 0)
    if args.rename_candidates is not None:
        result = relocate.rename_candidates(db_path, args.rename_candidates)
        print(json.dumps(result, sort_keys=True))
        sys.exit(1 if result["error"] else 0)
    if args.rename is not None and args.dry_run:
        result = relocate.preview_rename(db_path, Path(args.dest).resolve(), args.rename, args.name)
        print(json.dumps(result, sort_keys=True))
        sys.exit(1 if result["error"] else 0)

    # 2a. Single-instance enforcement (docs/engine-spec.md 4.1/7) — before
    # touching the database or source/dest paths at all. Applies to every
    # mode, including Index, not just --move/--copy.
    lock_fd = runtime.acquire_single_instance_lock(base_dir)
    if lock_fd is not None:
        # Only the lock holder rotates: a rejected second instance must not
        # rename the running engine's log out from under it.
        runtime.rotate_log_if_large()
    if lock_fd is None:
        runtime.logger.error(
            f"FATAL: another NegativeSpace engine process is already running against --base {base_dir} "
            f"(lock file: {base_dir / constants.LOCK_FILENAME}). Only one operation may run at a time. "
            f"Wait for it to finish, or cancel it, then retry."
        )
        sys.exit(1)

    if args.review_decision:
        from engine import review
        try:
            body = json.loads(sys.stdin.read(8193))
            print(json.dumps(review.decide(db_path, body)))
            code = 0
        except ns_db.RevisionConflict as exc:
            print(json.dumps({'error': 'review_changed', 'message': str(exc)}))
            code = 3
        except (ValueError, ns_db.SchemaError) as exc:
            print(json.dumps({'error': 'invalid_request', 'message': str(exc)}))
            code = 2
        finally:
            runtime.release_single_instance_lock(lock_fd)
        sys.exit(code)

    if args.backup_now:
        sys.exit(backups.run_manual_backup(db_path, Path(args.backups), base_dir, lock_fd))
    if args.repair_similarity:
        sys.exit(maintenance.run_similarity_repair(args, db_path, lock_fd))
    if args.rebuild_thumbnails:
        sys.exit(maintenance.run_thumbnail_rebuild(args, db_path, log_dir, lock_fd))
    if args.check_destination:
        sys.exit(maintenance.run_destination_check(args, db_path, log_dir, lock_fd))
    if args.rename is not None:
        sys.exit(relocate.run_rename(args, db_path, base_dir, lock_fd))
    if args.reject or args.return_to_library:
        sys.exit(relocate.run_relocation(args, db_path, base_dir, lock_fd))

    # 2b. ExifTool is a hard requirement (the package docstring) — fail fast and
    # clearly, before touching source/dest/the database at all, rather than
    # limping along in a degraded PIL-only mode.
    if not deps.EXIFTOOL_SUPPORTED:
        missing = []
        if not deps.PYEXIFTOOL_PACKAGE_AVAILABLE:
            missing.append("the 'PyExifTool' Python package (pip install pyexiftool)")
        if not deps.EXIFTOOL_BINARY_AVAILABLE:
            missing.append("the 'exiftool' system binary (apt install libimage-exiftool-perl)")
        runtime.logger.error(
            "FATAL: ExifTool is a hard requirement for NegativeSpace and is not available. "
            f"Missing: {' and '.join(missing)}."
        )
        sys.exit(1)

    source_path = Path(args.source).resolve()
    dest_path = Path(args.dest).resolve()

    # Invalid input is an error, not an empty success: the caller (the web UI,
    # a script) reads the exit code, and exit 0 said "nothing to do".
    if not source_path.exists():
        runtime.logger.error(f"FATAL: source path does not exist: {source_path}")
        runtime.release_single_instance_lock(lock_fd)
        sys.exit(1)
    if not source_path.is_dir():
        runtime.logger.error(f"FATAL: source path is not a folder: {source_path}")
        runtime.release_single_instance_lock(lock_fd)
        sys.exit(1)

    # Source and destination must be separate storage. When they are one
    # folder, or one contains the other, a file already in its date folder has
    # its own path as its computed destination: the already-present check
    # hashes the file against itself, matches, and --move deletes the only
    # copy while reporting success. Refused for every mode — overlapping roots
    # are unsupported whatever the run would have done.
    overlap = scan.describe_root_overlap(source_path, dest_path)
    if overlap:
        runtime.logger.error(
            f"FATAL: source and destination overlap — {overlap}. They must be separate, "
            f"non-overlapping folders; check the host folders behind the container mounts. "
            f"Nothing was changed."
        )
        runtime.release_single_instance_lock(lock_fd)
        sys.exit(1)

    # --source-subdir scopes targeting to already-indexed rows under this
    # path, rather than re-walking the filesystem or enumerating IDs. Resolve
    # it now and confirm it doesn't escape --source (e.g. via `..` segments)
    # before it's ever used in a query.
    subdir_filter_path = None
    if args.source_subdir:
        subdir_filter_path = (source_path / args.source_subdir).resolve()
        try:
            subdir_filter_path.relative_to(source_path)
        except ValueError:
            runtime.logger.error(
                f"--source-subdir must resolve to a path under --source ({source_path}); "
                f"got: {subdir_filter_path}"
            )
            runtime.release_single_instance_lock(lock_fd)
            sys.exit(1)

    mode_label = "COPY" if args.copy else ("MOVE" if args.move else "INDEX")
    runtime.logger.info(f"Initializing NegativeSpace Engine. Mode: {mode_label}")
    runtime.logger.info(f"Base Directory: {base_dir}")
    runtime.logger.info(f"Source Directory: {source_path}")
    runtime.logger.info(f"Destination Directory: {dest_path}")
    runtime.logger.info(f"Database Path: {db_path}")

    # Log the resolved timezone explicitly: it silently decides which
    # YYYY/MM/DD folder a file lands in, and a container defaults to UTC
    # regardless of the host's zone unless TZ is passed in. EXIF dates are
    # used exactly as the camera recorded them (they carry no zone, so no
    # conversion happens), but the file-mtime fallback — every file without a
    # usable EXIF date — is interpreted in this zone. A photo taken at 21:00
    # local buckets into the NEXT day under UTC.
    runtime.logger.info(f"Worker start method: {start_method} (avoids unsafe fork with rawpy/OpenMP).")
    _local_now = datetime.now().astimezone()
    runtime.logger.info(
        f"Timezone: {_local_now.tzname()} (UTC{_local_now.strftime('%z')}) — "
        f"used for date bucketing when a file has no EXIF date. Pass -e TZ=<zone> to change it."
    )
    if args.file_ids:
        targeting._log_selection(args)
    if subdir_filter_path is not None:
        runtime.logger.info(f"Targeted source subdirectory: {subdir_filter_path}")

    # 3. Schema + Startup Recovery
    try:
        store.init_database(str(db_path))
    except (ns_db.SchemaError, sqlite3.DatabaseError) as exc:
        runtime.logger.error(f"FATAL: catalog initialization failed: {exc}. No files were processed.")
        runtime.release_single_instance_lock(lock_fd)
        sys.exit(1)

    # 4. Register cancellation handlers and open the run record. Everything
    # from here down is wrapped in try/except/finally so the `runs` row is
    # always finalized — Completed on normal exit, Cancelled if a signal
    # arrived, Failed if anything unexpected blew up — never left "Running"
    # forever from a crash.
    signal.signal(signal.SIGTERM, runtime._handle_cancel_signal)
    signal.signal(signal.SIGINT, runtime._handle_cancel_signal)
    # The flags that change what a run does but are not settings. Part of the
    # request's identity so that repeating an ID with, say, --force-rehash added
    # is a conflict rather than a silent replay of the run without it.
    submitted = {"force_rehash": args.force_rehash,
                 "confirm_source_empty": args.confirm_source_empty,
                 "confirm_network_destination": args.confirm_network_destination,
                 "thumbnails": not args.no_thumbnails,
                 "cache": str(Path(args.cache).resolve())}
    try:
        run_id, created = store.start_run(
            str(db_path), mode_label, str(source_path), str(dest_path), args.file_ids, args.source_subdir,
            defaults={"workers": constants.MAX_WORKER_PROCESSES, "exts": sorted(SUPPORTED_EXTENSIONS)},
            overrides={**({"workers": args.workers} if args.workers is not None else {}),
                       **({"exts": sorted(scan.normalize_extensions(args.exts))} if args.exts is not None else {})},
            request_id=args.request_id, submitted=submitted, strict_selection=bool(args.file_ids_from),
        )
    except ns_db.SelectionRefused as exc:
        runtime.logger.error(f"FATAL: {exc}")
        runtime.release_single_instance_lock(lock_fd)
        sys.exit(1)
    except ns_db.RequestConflict:
        runtime.logger.error(
            f"FATAL: request ID {args.request_id!r} was already used for a different submission. "
            f"Nothing was started. A new attempt needs a new request ID."
        )
        runtime.release_single_instance_lock(lock_fd)
        sys.exit(constants.EXIT_REQUEST_CONFLICT)
    if not created:
        # Duplicate delivery of an accepted request: report, never re-execute.
        # A run still recorded Running cannot be alive — this process holds the
        # lock — but settling it is reconciliation, which the next run that does
        # real work performs and records under itself.
        with contextlib.closing(store.get_db_connection(str(db_path))) as conn:
            status = conn.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()[0]
        note = (" It did not finish; the next run will reconcile it."
                if status in ns_db.ACTIVE_RUN_STATUSES else "")
        runtime.logger.warning(
            f"Request ID {args.request_id!r} was already accepted as run #{run_id} "
            f"(recorded status: {status}). Nothing was started.{note}"
        )
        runtime.release_single_instance_lock(lock_fd)
        sys.exit(constants.EXIT_REQUEST_ALREADY_ACCEPTED)
    args.run_id = run_id
    with contextlib.closing(store.get_db_connection(str(db_path))) as config_conn:
        config = json.loads(config_conn.execute(
            "SELECT effective_config_json FROM run_configs WHERE run_id=?", (run_id,)
        ).fetchone()[0])
    worker_count, active_extensions = config["workers"], set(config["exts"])
    unreadable_exts = sorted(e for e in active_extensions if not ns_db.extension_support(e)["supported"])
    if unreadable_exts:
        # Informative, never blocking: selecting an extension is the user's call.
        runtime.logger.warning(
            f"Selected extension(s) NegativeSpace cannot read as photos: {', '.join(unreadable_exts)}. "
            f"Those files are still catalogued, and Copy and Move carry them into the "
            f"destination, usually under Undated/<year> by modification time, with no "
            f"thumbnail and no similarity matching.")
    runtime.run_progress.bind(str(db_path), run_id)
    cancel_watcher = threading.Thread(target=runtime.watch_for_cancellation,
                                      args=(str(db_path), run_id), daemon=True)
    cancel_watcher.start()
    # Reconciled AFTER the run exists, so what it concludes is recorded as
    # operations of this run rather than as silently rewritten statuses.
    # Outside the try/finally below, so a raised failure would otherwise leave
    # the run Preparing forever. Settle it here instead of swallowing the error.
    try:
        reconcile.reconcile_interrupted_state(db_path, run_id)
    except Exception as exc:
        runtime.logger.error(f"FATAL: could not reconcile interrupted work: {exc}")
        runtime.await_cancelling_record(cancel_watcher)
        store.finish_run(str(db_path), run_id, RunStatus.FAILED)
        runtime.release_single_instance_lock(lock_fd)
        sys.exit(1)
    # Preparing ends here: earlier work is settled and the requested work starts.
    # A no-op if a cancel already moved the run to Cancelling.
    with contextlib.closing(store.get_db_connection(str(db_path))) as conn:
        settled = ns_db.settle_interrupted_backups(conn, args.backups)
        if settled:
            runtime.logger.warning(f"{settled} catalog backup attempt(s) were interrupted before finishing; "
                           f"recorded as interrupted. Nothing retries them automatically.")
        # After reconciliation, before this run's work: what an interrupted run or a
        # failed backup left outside every backup. Reported, never backed up here.
        unbacked, since, runs = ns_db.unbacked_changes(conn, exclude_run_id=run_id)
        if unbacked:
            last = (f"the last successful backup was taken {since}" if since
                    else "there is no successful backup yet")
            runtime.logger.warning(
                f"{unbacked:,} catalog change(s) from run(s) "
                f"{', '.join('#' + str(r) for r in runs)} are not in any backup ({last}). "
                f"Run --backup-now to back them up now. Nothing is backed up automatically "
                f"at startup; this run takes a backup when it finishes if it records changes.")
        ns_db.transition_run(conn, run_id, RunStatus.RUNNING)
    run_outcome = RunStatus.FAILED

    try:
        # 5. Start DB Writer Thread
        db_thread = threading.Thread(target=store.db_writer_worker, args=(str(db_path),), daemon=True)
        db_thread.start()

        if args.file_ids:
            # Targeted mode: look up already-cataloged paths by ID instead of
            # scanning the filesystem. A file must have gone through at least
            # one prior Index for its ID to exist at all.
            conn = store.get_db_connection(str(db_path))
            rows = conn.execute(
                "SELECT id, source_path, status FROM photos WHERE id IN "
                "(SELECT photo_id FROM run_selections WHERE run_id = ?)", (run_id,)
            ).fetchall()
            conn.close()
            found_ids = {r[0] for r in rows}
            missing = sorted(set(args.file_ids) - found_ids)
            if missing:
                runtime.logger.warning(f"{len(missing):,} file id(s) not found in the catalog (never indexed?): "
                               f"{missing[:20]}{' …' if len(missing) > 20 else ''}")
            # Bounded by this run's --source like every other targeting mode:
            # an ID recorded under another source root is not this run's to act on.
            outside = [r for r in rows if not destinations._is_under(r[1], source_path)]
            if outside:
                outside_ids = sorted(r[0] for r in outside)
                runtime.logger.warning(
                    f"{len(outside)} requested file ID(s) belong to a different source root than "
                    f"{source_path} and are left out of this run: "
                    f"{outside_ids[:20]}{' …' if len(outside_ids) > 20 else ''}"
                )
                rows = [r for r in rows if destinations._is_under(r[1], source_path)]
            already_done = [r for r in rows if r[2] in constants.SOURCE_CONSUMED_STATUSES]
            if already_done:
                runtime.logger.info(
                    f"Skipping {len(already_done)} targeted file(s) already completed by a prior run — "
                    f"their source was removed on purpose."
                )
            # Files missing for any OTHER reason are deliberately NOT filtered
            # out: they flow through to process_file_task, which records each
            # one as Failed with a specific reason. Dropping them here would
            # make a stale selection silently shrink, with nothing in the audit
            # log explaining where those files went.
            candidates = [r[1] for r in rows if r[2] not in constants.SOURCE_CONSUMED_STATUSES]
            runtime.logger.info(f"Targeting {len(candidates)} of {len(args.file_ids)} requested file IDs.")
        elif subdir_filter_path is not None:
            # Same idea as --file-ids: query already-cataloged rows instead of
            # walking the filesystem. Only rows from a prior Index over this
            # path are visible — a fresh subtree needs a full scan first.
            candidates = targeting._query_source_subdir(str(db_path), subdir_filter_path)
            runtime.logger.info(f"Targeting {len(candidates)} already-indexed file(s) under source subdirectory.")
        else:
            discovery_errors: List[tuple] = []
            excluded_by_ext: dict = {}
            runtime.run_progress.start("discovering", None)

            def discovered(eligible, excluded):
                runtime.run_progress.set_count("eligible", eligible)
                runtime.run_progress.set_count("excluded", excluded)
                runtime.run_progress.maybe_write_now()
            candidates = scan.discover_source_files(source_path, active_extensions, errors=discovery_errors,
                                               excluded=excluded_by_ext, on_directory=discovered)
            runtime.run_progress.write_now()
            with contextlib.closing(store.get_db_connection(str(db_path))) as conn:
                ns_db.record_discovery(conn, run_id, eligible=len(candidates),
                                       excluded_by_extension=excluded_by_ext,
                                       unreadable=len(discovery_errors))
            excluded_total = sum(excluded_by_ext.values())
            top = sorted(excluded_by_ext.items(), key=lambda kv: -kv[1])[:8]
            breakdown = ", ".join(f"{ext or 'no extension'} {n:,}" for ext, n in top)
            more = f", {len(excluded_by_ext) - len(top)} more type(s)" if len(excluded_by_ext) > len(top) else ""
            runtime.logger.info(
                f"Discovered {len(candidates) + excluded_total:,} file(s): {len(candidates):,} eligible "
                f"by file type, {excluded_total:,} excluded by file type"
                + (f" ({breakdown}{more})" if excluded_total else "")
                + (". Counts are PARTIAL: some folders could not be read." if discovery_errors else ".")
                + f" Eligible extensions: {', '.join(sorted(active_extensions))}."
            )
            if discovery_errors:
                record_run_failures(str(db_path), run_id, discovery_errors)
                runtime.logger.warning(
                    f"{len(discovery_errors)} folder(s) or file(s) could not be read during the scan; "
                    f"each is recorded as a failure of this run."
                )
            # Only a full walk can say what is no longer there.
            vanished = scan.mark_vanished_sources(str(db_path), run_id, source_path, candidates,
                                             dest_root=dest_path,
                                             confirm_empty=args.confirm_source_empty)
            if vanished:
                runtime.logger.warning(
                    f"{vanished:,} catalogued file(s) under {source_path} no longer exist; recorded as "
                    f"Failed so any duplicates of them can stand in as the original."
                )

        # A targeting mode that matches nothing is a user-visible mistake, not
        # a successful no-op. Both targeted modes read the CATALOG rather than
        # the filesystem, so against a database that has never been indexed
        # they match zero rows and the run "completes successfully (0 files)"
        # — indistinguishable from a run that genuinely had nothing to do.
        # The web UI derives job outcome from recorded operations, so such a job
        # would show green having done nothing at all. Say what happened and
        # what to do about it.
        if not candidates:
            if args.file_ids:
                runtime.logger.warning(
                    f"None of the {len(args.file_ids)} requested file ID(s) resolved to work for this "
                    f"run. IDs exist only for files a previous Index recorded, and IDs whose source a "
                    f"prior --move already consumed are skipped on purpose. Nothing will be "
                    f"{'copied' if args.copy else 'moved' if args.move else 'scanned'}."
                )
            elif subdir_filter_path is not None:
                runtime.logger.warning(
                    f"No indexed files found under {subdir_filter_path}. --source-subdir targets rows "
                    f"the catalog already holds; it does not walk the filesystem. Run an Index over "
                    f"this source first (no --file-ids/--source-subdir), then re-run this command. "
                    f"Nothing will be {'copied' if args.copy else 'moved' if args.move else 'scanned'}."
                )
            else:
                runtime.logger.warning(
                    f"No supported files found under {source_path} "
                    f"(extensions: {', '.join(sorted(active_extensions))}). Check the source mount "
                    f"and --exts."
                )

        # Applies to ALL THREE targeting modes, not just the full scan.
        #
        # Re-reading an unchanged file costs a full SHA-1, a pixel decode for
        # the perceptual hash, and an ExifTool pass; over a network share, a
        # scoped run of ~9,500 files spends minutes on that before the first
        # byte is copied. Scoped runs are exactly what the web UI issues.
        # Skipping is safe because an unchanged file's row already holds its
        # hashes and date, which is all the Move/Copy phase reads.
        files_to_process, unchanged = scan.partition_unchanged(
            str(db_path), candidates, force=args.force_rehash
        )
        if unchanged:
            runtime.logger.info(
                f"Skipping {len(unchanged):,} unchanged file(s) — size and modification time "
                f"still match the catalog, so they are not re-read. "
                f"{len(files_to_process):,} file(s) to scan. Pass --force-rehash to re-read everything."
            )
        elif args.force_rehash:
            runtime.logger.info("--force-rehash: re-reading every file regardless of the catalog.")
        # The scan's denominator is the whole scope: unchanged files are done the
        # moment they are skipped, which is why raw operation counts cannot supply it.
        runtime.run_progress.start("scanning", len(files_to_process) + len(unchanged))
        runtime.run_progress.add("unchanged", len(unchanged))
        runtime.run_progress.write_now()

        # One bulk read rather than a query per file: an undated photo is filed
        # by the mtime captured at its original Index, which only the catalog
        # knows and which the worker processes cannot reach.
        original_mtimes = scan.original_source_mtimes(str(db_path), files_to_process)

        # Submitted in bounded batches rather than all at once. Every
        # completed future holds its ProcessingResult — including the FULL
        # ExifTool tag set for that file — until it is drained, so submitting
        # an entire library up front would make peak memory scale with the
        # number of photos (hundreds of MB to GBs on a large collection)
        # however small the queue's maxsize. Batching also gives cancellation a
        # checkpoint between batches; without one, Cancel Job (and `docker
        # stop`, which escalates to SIGKILL after ~10s) could not stop a long
        # Index.
        # Thumbnails are written by the scan phase only — the Move/Copy phase
        # never touches the cache. A cache root that cannot be created disables
        # generation for this run rather than failing an Index that is otherwise
        # fine: everything under it is reproducible from the photos themselves.
        cache_root = None if args.no_thumbnails else Path(args.cache)
        if cache_root is not None:
            try:
                (cache_root / constants.THUMBNAIL_DIR_NAME).mkdir(parents=True, exist_ok=True)
            except OSError as e:
                runtime.logger.warning(
                    f"Thumbnail cache at {cache_root} is not writable ({e}) — continuing without "
                    f"thumbnails. Indexing is unaffected; the gallery will show placeholders "
                    f"until a run with a writable cache generates them."
                )
                cache_root = None
        elif args.no_thumbnails:
            runtime.logger.info("--no-thumbnails: skipping thumbnail generation for this run.")

        scan_batch_size = max(worker_count * 4, 16)
        scanned = 0
        scan_started_at = time.monotonic()
        last_progress_at = scan_started_at
        last_progress_scanned = 0
        bytes_done = 0
        last_progress_bytes = 0
        with ProcessPoolExecutor(
            max_workers=worker_count,
            initializer=fileinfo._init_worker_process,
            initargs=(deps.EXIFTOOL_SUPPORTED, str(log_dir))
        ) as executor:
            for batch_start in range(0, len(files_to_process), scan_batch_size):
                if runtime.cancel_requested.is_set():
                    runtime.logger.warning(
                        f"Cancellation requested — stopping scan after {scanned} of "
                        f"{len(files_to_process)} file(s). Nothing already written to the "
                        f"database is lost; re-run to continue."
                    )
                    break
                batch = files_to_process[batch_start:batch_start + scan_batch_size]
                futures = [executor.submit(scan.process_file_task, f, str(dest_path), run_id,
                                           str(cache_root) if cache_root else None,
                                           original_mtimes.get(f))
                           for f in batch]
                for future in futures:
                    result = future.result()
                    bytes_done += result.file_size or 0
                    store.put_result(result, db_thread)
                scanned += len(batch)

                now = time.monotonic()
                if now - last_progress_at >= constants.PROGRESS_INTERVAL_SECONDS:
                    runtime.log_scan_progress(
                        scanned, len(files_to_process), scan_started_at,
                        window_files=scanned - last_progress_scanned,
                        window_bytes=bytes_done - last_progress_bytes,
                        window_seconds=now - last_progress_at,
                    )
                    last_progress_at = now
                    last_progress_scanned = scanned
                    last_progress_bytes = bytes_done

        store.drain_result_queue(db_thread)
        runtime.result_queue.put(None)
        db_thread.join(timeout=60)
        if db_thread.is_alive():
            runtime.logger.error("Database writer did not shut down within 60s — continuing without it.")
            store.writer_failures.append(("(database writer)", "did not shut down within 60s"))
        runtime.run_progress.write_now()

        if runtime.cancel_requested.is_set():
            runtime.logger.info(
                f"Scan cancelled after {scanned} file(s) — skipping the move/copy phase. "
                f"Everything already indexed is saved; re-run to continue."
            )
            run_outcome = RunStatus.CANCELLED
        elif store.writer_failures:
            first_path, first_reason = store.writer_failures[0]
            runtime.logger.error(
                f"{len(store.writer_failures):,} scan result(s) could not be recorded in the catalog "
                f"(first: {first_path} — {first_reason}). The catalog does not reflect this scan, "
                f"so no files will be moved or copied. Nothing was changed on disk."
            )
            run_outcome = RunStatus.FAILED
        else:
            gb = bytes_done / 1e9
            elapsed = time.monotonic() - scan_started_at
            runtime.logger.info(
                f"Scan and indexing completed successfully ({scanned:,} file(s), {gb:.1f} GB "
                f"in {runtime.format_duration(elapsed)} — {bytes_done/elapsed/1e6:.0f} MB/s average). "
                f"Database updated."
            )
            if cache_root is not None:
                thumbnails.sweep_orphan_thumbnails(str(db_path), cache_root)
            promoted, demoted = transfer.normalize_duplicate_groups(str(db_path))
            if promoted or demoted:
                runtime.logger.info(
                    f"Reclassified duplicates against the current catalog: {promoted} promoted to "
                    f"Pending (their original changed, failed or disappeared), {demoted} marked "
                    f"Duplicate (their content is already delivered or queued)."
                )
            runtime.run_progress.start("matching", None)
            def matching_progress(done, total):
                runtime.run_progress.set_total(total)
                runtime.run_progress.set_count("Compared", done)
                if runtime.run_progress.due():
                    runtime.run_progress.write_now()
            with contextlib.closing(store.get_db_connection(str(db_path))) as matching_conn:
                matching_complete = ns_similarity.refresh(matching_conn, cancelled=runtime.cancel_requested.is_set,
                                                          progress=matching_progress)
            runtime.run_progress.write_now()
            if not matching_complete:
                run_outcome = RunStatus.CANCELLED
                runtime.logger.info("Similarity comparison cancelled; the next Index will resume it.")
            elif args.move or args.copy:
                run_outcome = transfer._run_move_or_copy(args, db_path, dest_path, run_id)
            else:
                run_outcome = RunStatus.COMPLETED
                runtime.logger.info(
                    "Index finished. Pass `--move` to move files, or `--copy` to copy them non-destructively."
                )

    finally:
        # No relabelling on cancel_requested here. Each phase already returns
        # Cancelled when a cancel stopped work it had left; a cancel landing
        # after the work finished leaves the real outcome, so a job that
        # completed reads Completed and a job-level failure still exits 1.
        runtime.run_progress.write_now()
        runtime.await_cancelling_record(cancel_watcher)
        store.finish_run(str(db_path), run_id, run_outcome)
        runtime.logger.info(f"Run #{run_id} finished with status: {run_outcome}")
        # After the run settles, so the backup holds its final status, and
        # before the lock is released, so nothing can start in between.
        backups.backup_after_job(db_path, Path(args.backups), base_dir, run_id)
        runtime.release_single_instance_lock(lock_fd)

    # A failed run is an error to whatever invoked the engine, not a success
    # with a sad log line. The web UI reads the exit code as well as the record.
    if run_outcome == RunStatus.FAILED:
        sys.exit(1)


def record_run_failures(db_path: str, run_id: int, failures: List[tuple]):
    """Records (path, reason) failures that belong to the run rather than to any catalogued photo."""
    conn = store.get_db_connection(db_path)
    try:
        for path, reason in failures:
            store.log_operation(conn, run_id, None, path, None, PhotoStatus.FAILED, reason, commit=False)
        conn.commit()
    finally:
        conn.close()
