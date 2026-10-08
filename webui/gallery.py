"""The gallery: listing photos under the views and filters, the facets, positions and one photo's details."""

import json
import re
import posixpath
from pathlib import Path
from typing import Optional

from engine import ns_db, review
from engine.ns_similarity_cache import (matched_ids, match_counts_cte, match_distance, comparison_state)
from engine.ns_db import PhotoStatus, IN_REJECTS_STATUSES
from . import catalog


def _date_warning_sql():
    # Inspect only the recorded gallery date. Do not reinterpret timezones or
    # mutate EXIF. SQL keeps membership, counts and pagination in agreement.
    value = "json_extract(p.metadata_json, '$.date_taken')"
    year = f"CAST(substr({value},1,4) AS INTEGER)"
    latest = "(CAST(strftime('%Y','now') AS INTEGER) + 1)"
    return (f"CASE WHEN p.status!='Failed' AND {value} GLOB '[0-9][0-9][0-9][0-9]-*' THEN CASE "
            f"WHEN {year}<1800 THEN 'Recorded year is before 1800.' "
            f"WHEN {year}>{latest} THEN 'Recorded year is more than one year ahead of the current year.' END END")


_LIST_COLUMNS = f"""
    p.id, p.status, p.file_size, p.sha1_hash,
    json_extract(p.metadata_json, '$.date_taken') AS date_taken,
    json_extract(p.metadata_json, '$.date_source') AS date_source,
    {_date_warning_sql()} AS date_warning,
    basename(COALESCE(CASE WHEN p.status IN ({ns_db.sql_values(catalog.AT_DESTINATION)}) THEN p.dest_path END,
                      p.source_path)) AS filename
"""


def _search_clause(q: Optional[str]):
    """Filename search: current and original names, including names of removed
    duplicates of the same content, never folder names (webui-spec 2)."""
    if not q:
        return "", ()
    like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    return (" AND (basename(p.source_path) LIKE ? ESCAPE '\\' OR basename(p.dest_path) LIKE ? ESCAPE '\\'"
            " OR EXISTS (SELECT 1 FROM photos d WHERE d.sha1_hash = p.sha1_hash AND d.id != p.id"
            "            AND basename(d.source_path) LIKE ? ESCAPE '\\'))", (like, like, like))


# No capture date in the photo's EXIF: dated by its file's modification time instead
# (date_source 'file_mtime'), or not dated at all. These are the photos filed under
# Undated (webui-spec 3.1).
_UNDATED = ("(p.status!='Failed' AND (json_extract(p.metadata_json, '$.date_source') = 'file_mtime' "
            "OR json_extract(p.metadata_json, '$.date_taken') IS NULL))")


_DATE_TAKEN = "json_extract(p.metadata_json, '$.date_taken')"


def _dates_clause(dates):
    """The date tree's "Show only" filter: years ("2023"), months ("2023-06") and
    "none" for photos with no date at all, as the timeline groups them. The dates
    are the gallery's own (a file date for an undated photo). None or empty: no filter."""
    if not dates:
        return "", ()
    years = [d for d in dates if len(d) == 4 and d.isdigit()]
    months = [d for d in dates if len(d) == 7 and d[:4].isdigit() and d[4] == "-" and d[5:].isdigit()]
    none = "none" in dates
    if len(years) + len(months) + none != len(dates):
        raise ValueError("dates must be years (2023), months (2023-06) or none")
    parts, params = [], []
    if years:
        parts.append(f"substr({_DATE_TAKEN}, 1, 4) IN ({','.join('?' * len(years))})")
        params += years
    if months:
        parts.append(f"substr({_DATE_TAKEN}, 1, 7) IN ({','.join('?' * len(months))})")
        params += months
    if none:
        parts.append(f"{_DATE_TAKEN} IS NULL")
    return " AND (" + " OR ".join(parts) + ")", tuple(params)


# A photo's file type, from the name it was indexed under: a copy keeps its extension.
_TYPE_OF = "extension(COALESCE(p.source_path, p.dest_path))"


def _types_clause(types):
    """The Types filter's "Show only": file extensions, lower case, no dot ("jpg",
    "heic"). None or empty: every type."""
    if not types:
        return "", ()
    if any(not isinstance(t, str) or not re.fullmatch(r"[a-z0-9]{1,10}", t) for t in types):
        raise ValueError("type must be a file extension, e.g. jpg or heic")
    return f" AND {_TYPE_OF} IN ({','.join('?' * len(types))})", tuple(types)


# The folder tree's "files directly in the source folder", which no subfolder holds.
TOP_FILES = "."


def _folder(root: Path, folder: str) -> str:
    """A folder named relative to the source, checked as the job request checks it
    (jobs.validate_request): normalize path steps without trimming filename
    whitespace, and reject absolute paths or parent steps escaping the source."""
    if not isinstance(folder, str) or not folder or "\0" in folder:
        raise ValueError("folder must be a folder inside the source")
    if folder == TOP_FILES:
        return folder
    normal = posixpath.normpath(folder)
    if posixpath.isabs(normal) or normal in (".", "..") or normal.startswith("../"):
        raise ValueError("folder must be a folder inside the source")
    return normal


def _folders_clause(folders, root):
    """The folder tree's "Show only": photos whose source path is under any of these
    folders, recursively, named relative to the source; "." is the files directly in the
    source folder. A literal range comparison, not LIKE, whose wildcards and letter case
    would take the wrong folders (the engine's --source-subdir does the same)."""
    if not folders:
        return "", ()
    base = str(root).rstrip("/") + "/"
    parts, params = [], []
    for f in (_folder(root, f) for f in folders):
        if f == TOP_FILES:
            parts.append("(p.source_path >= ? AND p.source_path < ? AND instr(substr(p.source_path, ?), '/') = 0)")
            params += [base, base[:-1] + "0", len(base) + 1]
        else:
            prefix = base + f + "/"
            parts.append("(p.source_path >= ? AND p.source_path < ?)")   # "0" is the character after "/"
            params += [prefix, prefix[:-1] + "0"]
    return " AND (" + " OR ".join(parts) + ")", tuple(params)


def _run_clause(run):
    """The photos a job recorded an outcome for: the gallery's "job" view (webui-spec 2,
    after a job). Copies a Move removed are left out, as every view leaves them out."""
    if run is None:
        return "", ()
    if type(run) is not int or not 1 <= run <= 2**63-1:
        raise ValueError("run must be a positive job id")
    return " AND p.id IN (SELECT o.photo_id FROM operations o WHERE o.run_id = ? AND o.photo_id IS NOT NULL)", (run,)


def _filters(q, undated, dates, types=None, folders=None, root=None, *, group_sets=False, group_view=None, match_min=75, set_reference=None, run=None, similar=False, suspicious=False, reason="all"):
    """Search, no-capture-date, date-tree, type and folder filters, and a job's photos,
    shared by the list, its ids and its counts, so Select all takes exactly what the
    gallery shows."""
    search, search_params = _search_clause(q)
    date_sql, date_params = _dates_clause(dates)
    type_sql, type_params = _types_clause(types)
    folder_sql, folder_params = _folders_clause(folders, root) if folders else ("", ())
    run_sql, run_params = _run_clause(run)
    filtered = run_sql + search + (f" AND {_UNDATED}" if undated else "") + date_sql + type_sql + folder_sql
    params = run_params + tuple(search_params) + date_params + type_params + folder_params
    if similar:
        filtered += f" AND p.id IN ({matched_ids(match_min)})"
    if suspicious:
        filtered += f" AND ({_date_warning_sql()}) IS NOT NULL"
    if reason != 'all':
        filtered += f" AND ({review.predicate(reason)})"
    if set_reference is not None:
        if type(set_reference) is not int or not 1 <= set_reference <= 2**63-1:
            raise ValueError("set_reference must be a positive photo ID")
        from .reference_sets import _membership
        distance = match_distance(match_min)
        filtered += " AND p.id IN (" + _membership([set_reference]) + "SELECT id FROM members)"
        params += (set_reference, distance, distance)
    if group_sets:
        from .equivalent_sets import representatives
        # Choose a representative inside the current place/inbox before collapsing.
        # Membership still comes from all active Library photos. Filtering the
        # chosen representative afterward can otherwise hide an entire review set.
        if group_view is not None:
            filtered += f" AND ({_view_clause(group_view, match_min)})"
        return " AND p.id IN (" + representatives(match_min, filtered) + ")", params
    return filtered, params


def _view_clause(view, match_min=75):
    match_distance(match_min)
    if view == "review":
        return review.predicate()
    if view == "job":
        # A job's photos wherever they are now, library or Rejects; `run` names the job.
        return f"p.status NOT IN ({ns_db.sql_values(catalog.COPIES)})"
    if view == "suspicious":
        return f"p.status IN ({ns_db.sql_values(catalog.VIEWS[view])}) AND ({_date_warning_sql()}) IS NOT NULL"
    if view == "similar":
        return f"p.id IN ({matched_ids(match_min)})"
    if view == "rejects":
        return f"p.status IN ({ns_db.sql_values(catalog.VIEWS[view])}) AND in_rejects(p.dest_path)"
    return f"p.status IN ({ns_db.sql_values(catalog.VIEWS[view])})"


def _check_view(view, sort=None, page=None, page_size=None):
    if view not in catalog.VIEWS and view != "job":
        raise ValueError(f"unknown view: {view}")
    if sort is not None and sort not in catalog.SORTS:
        raise ValueError(f"unknown sort: {sort}")
    if sort == "matches" and view != "similar":
        raise ValueError("matches sort requires similar photos or an explicit selection")
    if page is not None and (page < 1 or not 1 <= page_size <= 240):
        raise ValueError("page must be at least 1 and page_size between 1 and 240")


def _review_cards(conn, rows):
    """Current reasons for one bounded gallery page, without loading event history."""
    if not rows:
        return {}
    found = conn.execute(f"""SELECT p.id, p.status, c.width, c.height,
        {review.LIMIT_SQL} AS minimum,
        ({review.predicate('small')}) AS small,
        ({review.predicate('later')}) AS later,
        (SELECT e.note FROM review_events e WHERE e.photo_id=p.id AND e.reason='later'
         ORDER BY e.id DESC LIMIT 1) AS note
        FROM photos p LEFT JOIN contents c ON c.hash_algorithm='sha1' AND c.digest=p.sha1_hash
        WHERE p.id IN (SELECT value FROM json_each(?))""",
        (json.dumps([r['id'] for r in rows]),)).fetchall()
    cards = {}
    for row in found:
        reasons = []
        if row['small']:
            reasons.append({'reason': 'small', 'label': 'Small image',
                'message': f"{row['width']} × {row['height']} — below your {row['minimum']}-pixel minimum on the shorter side."})
        if row['later']:
            reasons.append({'reason': 'later', 'label': 'Review later',
                'message': row['note'] or 'You asked to come back to this photo.'})
        cards[row['id']] = {'reasons': reasons, 'location':
            'Library' if row['status'] in catalog.DELIVERED else
            'Rejects' if row['status'] in IN_REJECTS_STATUSES else 'Not organized'}
    return cards


def _index_summary(conn):
    """Facts about remaining indexed source photos; no destination review eligibility."""
    where = _view_clause('unorganized')
    row = conn.execute(f"""SELECT COUNT(*) AS photos,
        COALESCE(SUM(p.status='Pending'),0) AS ready,
        COALESCE(SUM(p.status='Processing'),0) AS unfinished,
        COALESCE(SUM(p.status='Pending' AND ({_date_warning_sql()}) IS NOT NULL),0) AS suspicious,
        COALESCE(SUM(p.status='Pending' AND {_UNDATED}),0) AS undated,
        COALESCE(SUM(p.status='Pending' AND c.width>0 AND c.height>0 AND min(c.width,c.height)<{review.LIMIT_SQL}),0) AS small,
        COALESCE(SUM(p.status='Pending' AND (c.width IS NULL OR c.height IS NULL OR c.width<=0 OR c.height<=0)),0) AS unknown_dimensions,
        COALESCE(SUM(p.status='Failed'),0) AS failed
        FROM photos p LEFT JOIN contents c ON c.hash_algorithm='sha1' AND c.digest=p.sha1_hash
        WHERE {where}""").fetchone()
    result = dict(row)
    result['minimum'] = conn.execute(f'SELECT {review.LIMIT_SQL}').fetchone()[0]
    result['duplicates'] = conn.execute(f"""SELECT COUNT(*) FROM photos d WHERE d.status='Duplicate'
        AND EXISTS (SELECT 1 FROM photos p WHERE {where} AND p.sha1_hash=d.sha1_hash)""").fetchone()[0]
    result['similar'] = None  # Source-only visual comparisons are not calculated.
    last_index = conn.execute("SELECT id, started_at FROM runs WHERE mode='INDEX' AND ended_at IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
    result['last_index'] = dict(last_index) if last_index else None
    return result


def _items(conn, rows, *, include_review=False) -> list:
    items = []
    review_cards = _review_cards(conn, rows) if include_review else {}
    for r in rows:
        item = dict(r)
        sha1 = item.pop("sha1_hash")
        item["duplicates"] = conn.execute(
            "SELECT COUNT(*) FROM photos WHERE sha1_hash = ? AND id != ?", (sha1, r["id"])
        ).fetchone()[0] if sha1 else 0
        # Why a Failed photo failed, for the badge's hover: its latest failed attempt.
        item["failure"] = None
        if r["status"] == PhotoStatus.FAILED:
            last = conn.execute("SELECT error_message FROM operations WHERE photo_id = ? AND status = ? "
                                "ORDER BY id DESC LIMIT 1", (r["id"], PhotoStatus.FAILED)).fetchone()
            item["failure"] = catalog.failure_reason(last[0]) if last else None
        # A Copied photo a Move could not finish: why its original is still in the source.
        # When a rejected photo was rejected, for its card in the Rejects view.
        item["rejected_at"] = None
        if r["status"] in IN_REJECTS_STATUSES:
            item["rejected_at"] = _rejected_at(conn, r["id"])
        item["kept"] = None
        if r["status"] == PhotoStatus.COPIED:
            last = conn.execute("SELECT error_message FROM operations WHERE photo_id = ? AND status IN (?, ?) "
                                "ORDER BY id DESC LIMIT 1",
                                (r["id"], PhotoStatus.COPIED, PhotoStatus.COMPLETED)).fetchone()
            item["kept"] = catalog.kept_reason(last[0]) if last else None
        if include_review:
            item["review"] = review_cards.get(r["id"])
        items.append(item)
    return items


def _rejected_at(conn, photo_id):
    """When the photo last went to Rejects: its reject, or its Move there."""
    row = conn.execute("SELECT MAX(timestamp) FROM operations WHERE photo_id = ? AND status IN (?, ?)",
                       (photo_id, PhotoStatus.REJECTED, PhotoStatus.REJECTED_COPIED)).fetchone()
    return row[0] if row else None


def _counted_list(sort, match_min, *, include=False, ids=None):
    match_distance(match_min)
    if sort == "matches" or include:
        # Drive similarity pages from counts. A LEFT JOIN combined with the
        # membership IN query can make SQLite rescan every count per photo.
        # Explicit selections keep the outer join, bounded to their own IDs.
        return ("WITH " + match_counts_cte(match_min, ids) + " ",
                _LIST_COLUMNS + ", mc.similar_count",
                "FROM match_counts mc JOIN photos p ON p.id=mc.id" if include else
                "FROM photos p LEFT JOIN match_counts mc ON mc.id=p.id")
    return "", _LIST_COLUMNS, "FROM photos p"


def list_photos(db_path: Path, *, view="all", sort="newest", q=None, page=1, page_size=60, undated=False,
                dates=None, types=None, folders=None, root=None, match_min=75, group_sets=False, set_reference=None,
                run=None, similar=False, suspicious=False, reason="all") -> dict:
    _check_view("similar" if (similar or set_reference is not None) and sort == "matches" else view, sort, page, page_size)
    filtered, filtered_params = _filters(q, undated, dates, types, folders, root, group_sets=group_sets and (view == "similar" or similar), group_view=view, match_min=match_min, set_reference=set_reference, run=run, similar=similar, suspicious=suspicious, reason=reason)
    run_sql, run_params = _run_clause(run)
    with catalog.connect(db_path) as conn:
        conn.execute('BEGIN')
        # Location counts cover all photos there; total covers this filtered page.
        # Legacy clients also receive filtered matches for each location.
        raw_filtered, raw_params = _filters(q, undated, dates, types, folders, root,
            match_min=match_min, set_reference=set_reference, similar=similar, suspicious=suspicious, reason=reason)
        place_filtered, place_params = _filters(q, undated, dates, types, folders, root,
            match_min=match_min, set_reference=set_reference, similar=similar, suspicious=suspicious)
        counts, matches = {}, {}
        for name in catalog.VIEWS:
            base = f"SELECT COUNT(*) FROM photos p WHERE {_view_clause(name, match_min)}"
            counts[name] = conn.execute(base).fetchone()[0]
            extra, values = (raw_filtered, raw_params) if name == "review" else (place_filtered, place_params)
            matches[name] = conn.execute(base + extra, values).fetchone()[0] if extra else counts[name]
        total = conn.execute(f"SELECT COUNT(*) FROM photos p WHERE {_view_clause(view, match_min)}" + filtered,
                             filtered_params).fetchone()[0]
        if view not in catalog.VIEWS:
            counts[view] = conn.execute(f"SELECT COUNT(*) FROM photos p WHERE {_view_clause(view, match_min)}" + run_sql, run_params).fetchone()[0]
        # Chip counts omit their own restriction, but retain the other restrictions.
        elsewhere = {}
        if q:
            search_sql, search_params = _search_clause(q)
            for place in ('organized', 'unorganized', 'rejects'):
                elsewhere[place] = conn.execute(f"SELECT COUNT(*) FROM photos p WHERE {_view_clause(place, match_min)}"+search_sql, search_params).fetchone()[0]
        chips = {}
        for chip in ('similar', 'suspicious', 'undated', 'small'):
            extra, values = _filters(q, True if chip=='undated' else undated, dates, types, folders, root,
                match_min=match_min, similar=True if chip=='similar' else similar,
                suspicious=True if chip=='suspicious' else suspicious, reason='small' if chip=='small' else reason, run=run)
            chips[chip] = conn.execute(f"SELECT COUNT(*) FROM photos p WHERE {_view_clause(view, match_min)}"+extra, values).fetchone()[0]
        reasons = {}
        # Reason chips exist only in the inbox; other galleries need its total, not
        # three additional counts over the same photo set.
        for key in ('all', *review.REASONS) if view == 'review' else ():
            extra, values = _filters(q, undated, dates, types, folders, root, match_min=match_min,
                                    similar=similar, suspicious=suspicious, reason=key, run=run)
            reasons[key] = conn.execute(f"SELECT COUNT(*) FROM photos p WHERE ({review.predicate()})"+extra, values).fetchone()[0]
        # No capture date under every other filter, for its button, as the views are counted.
        no_date, no_date_params = _filters(q, True, dates, types, folders, root, match_min=match_min, set_reference=set_reference, run=run, similar=similar, suspicious=suspicious, reason=reason)
        matches["undated"] = conn.execute(
            f"SELECT COUNT(*) FROM photos p WHERE {_view_clause(view, match_min)}" + no_date,
            no_date_params).fetchone()[0]
        # How many photos in this view have no capture date, whatever else is on, for its label.
        counts["undated"] = conn.execute(
            f"SELECT COUNT(*) FROM photos p WHERE {_view_clause(view, match_min)} AND {_UNDATED}" + run_sql, run_params
        ).fetchone()[0]
        prefix, columns, source = _counted_list(sort, match_min, include=view == "similar" or similar)
        where = _view_clause(view, match_min)
        rows = conn.execute(
            prefix + f"SELECT {columns} {source} WHERE {where}"
            + filtered + f" ORDER BY {catalog.SORTS[sort]} LIMIT ? OFFSET ?",
            filtered_params + (page_size, (page - 1) * page_size)).fetchall()
        items = _items(conn, rows, include_review=view in ("review", "organized", "similar"))
        state = comparison_state(conn) if view == "similar" or similar else None
        rejects = catalog.rejects_summary(conn) if view == "rejects" else None
        index_summary = _index_summary(conn) if view == "unorganized" else None
    return {"items": items, "page": page, "page_size": page_size, "total": total, "counts": counts,
            "matches": matches, "similarity": {"threshold": match_min, **state} if state is not None else None,
            "rejects": rejects, "chips": chips, "reasons": reasons, "elsewhere": elsewhere, "index_summary": index_summary}


def photo_position(db_path: Path, photo_id: int, *, view="all", sort="newest", page_size=60,
                   q=None, undated=False, dates=None, types=None, folders=None, root=None, ids=None, match_min=75, group_sets=False, set_reference=None,
                   run=None, similar=False, suspicious=False, reason="all") -> dict:
    """Locate one photo and its neighbors without transferring preceding gallery pages."""
    _check_view(view)
    _check_view("similar" if (similar or ids is not None or set_reference is not None) and sort == "matches" else view, sort, 1, page_size)
    filtered, params = _filters(q, undated, dates, types, folders, root, group_sets=group_sets and (view == "similar" or similar), group_view=view, match_min=match_min, set_reference=set_reference, run=run, similar=similar, suspicious=suspicious, reason=reason)
    where = _view_clause(view, match_min) + filtered
    if ids is not None:
        if any(type(i) is not int or i < 1 for i in ids):
            raise ValueError("ids must be positive photo ids")
        where, params = "p.id IN (SELECT value FROM json_each(?))", (json.dumps(ids),)
    include_counts = (view == "similar" or similar) and ids is None and sort == "matches"
    prefix, columns, source = _counted_list(sort, match_min, include=include_counts, ids=ids)
    if include_counts:
        where = _view_clause(view, match_min) + filtered
    prefix = prefix.removesuffix(" ")
    with catalog.connect(db_path) as conn:
        row = conn.execute(
            (prefix + ", " if prefix else "WITH ") + f"candidates AS (SELECT {columns} {source} WHERE {where}), "
            f"ranked AS (SELECT p.id, ROW_NUMBER() OVER (ORDER BY {catalog.SORTS[sort]}) - 1 AS position, "
            f"LAG(p.id) OVER (ORDER BY {catalog.SORTS[sort]}) AS previous_id, "
            f"LEAD(p.id) OVER (ORDER BY {catalog.SORTS[sort]}) AS next_id FROM candidates p) "
            "SELECT * FROM ranked WHERE id = ?", tuple(params) + (photo_id,)).fetchone()
    return ({"position": row["position"], "page": row["position"] // page_size + 1,
             "previous_id": row["previous_id"], "next_id": row["next_id"]} if row else
            {"position": None, "page": None, "previous_id": None, "next_id": None})


def photo_ids(db_path: Path, *, view="all", q=None, undated=False, dates=None, types=None,
              folders=None, root=None, match_min=75, group_sets=False, set_reference=None, run=None, similar=False, suspicious=False, reason="all") -> dict:
    """Every photo id the gallery would show for these filters, across all pages, for
    Select all: all of them, never cut short. `in_rejects` names those in Rejects, since a
    selection holds library photos or photos in Rejects, never both (webui-spec 2)."""
    _check_view(view)
    filtered, params = _filters(q, undated, dates, types, folders, root, group_sets=group_sets and (view == "similar" or similar), group_view=view, match_min=match_min, set_reference=set_reference, run=run, similar=similar, suspicious=suspicious, reason=reason)
    base = f"FROM photos p WHERE {_view_clause(view, match_min)}" + filtered
    with catalog.connect(db_path) as conn:
        rows = conn.execute(f"SELECT p.id, p.status IN ({ns_db.sql_values(IN_REJECTS_STATUSES)}) {base} ORDER BY p.id",
                            params).fetchall()
    ids = [r[0] for r in rows]
    return {"ids": ids, "total": len(ids), "in_rejects": [r[0] for r in rows if r[1]]}


# What each action on a selection takes (the selection bar's counts and a review's photos):
# Copy and Move by the engine's own rule (ns_db.TRANSFER_ELIGIBLE), Reject photos in the
# library, Return to library photos in Rejects (engine-spec 9.5).
ACTION_STATUSES = {"copy": ns_db.TRANSFER_ELIGIBLE["copy"], "move": ns_db.TRANSFER_ELIGIBLE["move"],
                   "reject": catalog.DELIVERED, "return": IN_REJECTS_STATUSES}


def photos_by_ids(db_path: Path, ids, *, sort="newest", page=1, page_size=60, match_min=75, action=None) -> dict:
    """The selected photos, whatever view, search or dates would hide them, one page at a
    time (webui-spec 2, Show only selected and the review before Copy/Move). `missing` names ids no longer in the catalog,
    so a selection is never silently shortened."""
    _check_view("similar" if sort == "matches" else "all", sort, page, page_size)
    if not isinstance(ids, list) or any(type(i) is not int or i < 1 for i in ids):
        raise ValueError("ids must be a list of photo ids")
    wanted = sorted(set(ids))
    # json_each reads the list as a table, with no write to the catalog.
    join = "FROM photos p JOIN json_each(?) w ON w.value = p.id"
    with catalog.connect(db_path) as conn:
        places = conn.execute(f"SELECT p.id, p.status IN ({ns_db.sql_values(IN_REJECTS_STATUSES)}) {join}",
                              (json.dumps(wanted),)).fetchall()
        found = {r[0] for r in places}
        prefix, columns, source = _counted_list(sort, match_min, ids=wanted)
        rows = conn.execute(prefix + f"SELECT {columns} {source} JOIN json_each(?) w ON w.value=p.id "
                            f"ORDER BY {catalog.SORTS[sort]} LIMIT ? OFFSET ?",
                            (json.dumps(wanted), page_size, (page - 1) * page_size)).fetchall()
        items = _items(conn, rows)
        # What each action would take of them, for the selection bar.
        counts = conn.execute(
            "SELECT " + ", ".join(f"COALESCE(SUM(p.status IN ({ns_db.sql_values(v)})), 0)" for v in ACTION_STATUSES.values())
            + f" {join}", (json.dumps(wanted),)).fetchone()
        # The photos one action takes, for its review: never the ones it would skip.
        takes = None
        if action is not None:
            if action not in ACTION_STATUSES:
                raise ValueError(f"unknown action: {action}")
            takes = [r[0] for r in conn.execute(
                f"SELECT p.id {join} WHERE p.status IN ({ns_db.sql_values(ACTION_STATUSES[action])}) ORDER BY p.id",
                (json.dumps(wanted),))]
    return {"items": items, "page": page, "page_size": page_size, "total": len(found),
            "missing": [i for i in wanted if i not in found],
            "in_rejects": sorted(r[0] for r in places if r[1]),
            "actions": dict(zip(ACTION_STATUSES, counts)),
            **({"takes": takes} if takes is not None else {})}


def timeline(db_path: Path, *, view="all", q=None, undated=False, dates=None, types=None,
             folders=None, root=None, match_min=75, group_sets=False, run=None, similar=False, suspicious=False, reason="all") -> dict:
    """Photos per month for a view and search, newest month first: the date tree's counts
    and the page each month starts on. Months are the recorded date's calendar month (a
    file date for an undated photo, as the gallery shows it); `undated` counts rows with
    no date at all, which every date sort places last. The tree asks without `dates`, so
    an unticked month keeps its count; jumping asks with them, to land on the right page."""
    _check_view(view)
    filtered, params = _filters(q, undated, dates, types, folders, root, group_sets=group_sets and (view == "similar" or similar), group_view=view, match_min=match_min, run=run, similar=similar, suspicious=suspicious, reason=reason)
    base = f"FROM photos p WHERE {_view_clause(view, match_min)}" + filtered
    with catalog.connect(db_path) as conn:
        months = [{"month": r[0], "count": r[1]} for r in conn.execute(
            f"SELECT substr(json_extract(p.metadata_json, '$.date_taken'), 1, 7) AS month, COUNT(*) {base} "
            "AND json_extract(p.metadata_json, '$.date_taken') IS NOT NULL GROUP BY month ORDER BY month DESC",
            params)]
        undated = conn.execute(
            f"SELECT COUNT(*) {base} AND json_extract(p.metadata_json, '$.date_taken') IS NULL", params).fetchone()[0]
    return {"months": months, "undated": undated}


def file_types(db_path: Path, *, view="all", q=None, undated=False, dates=None, folders=None, root=None, match_min=75, group_sets=False, run=None, similar=False, suspicious=False, reason="all") -> list:
    """Photos per file type for the Types section: the view, search, dates and folders
    apply, the Types filter itself does not, so an unchecked type keeps its count. Most first."""
    _check_view(view)
    filtered, params = _filters(q, undated, dates, None, folders, root, group_sets=group_sets and (view == "similar" or similar), group_view=view, match_min=match_min, run=run, similar=similar, suspicious=suspicious, reason=reason)
    with catalog.connect(db_path) as conn:
        return [{"type": r[0], "photos": r[1]} for r in conn.execute(
            f"SELECT {_TYPE_OF} AS t, COUNT(*) AS n FROM photos p WHERE {_view_clause(view, match_min)}"
            + filtered + " GROUP BY t ORDER BY n DESC, t", params)]


def folder_tree(db_path: Path, root: Path, *, view="all", q=None, undated=False, dates=None, types=None,
                keep=None, match_min=75, group_sets=False, run=None, similar=False, suspicious=False, reason="all") -> dict:
    """The source's folders for the Folders tree (webui-spec 2): built from catalogued
    source paths, never a disk listing, so every folder offered holds photos a job can
    act on. Each folder counts its photos recursively under the view, search, dates and
    types (the folder filter itself does not apply, so an unticked folder keeps its
    number), and, whatever the filters, the photos a Copy or a Move of it would take
    (ns_db.TRANSFER_ELIGIBLE), for the Jobs menu. A chain of folders each holding only one
    folder and no photos is one row ("Camera / Nikon D750"). A folder in `keep` stays
    listed at 0, so a ticked folder can be unticked. Photos outside the source folder
    (a catalog shared with another source) are counted in `outside`, not placed."""
    _check_view(view)
    filtered, params = _filters(q, undated, dates, types, group_sets=group_sets and (view == "similar" or similar), group_view=view, match_min=match_min, run=run, similar=similar, suspicious=suspicious, reason=reason)
    base = str(root).rstrip("/") + "/"
    # COALESCE: a filter can be NULL rather than false (a search against a photo with no
    # destination path yet), and NULL is not a count. An unclassified photo's NULL
    # status also makes eligibility NULL: it is neither shown nor transferable yet.
    shown = f"COALESCE(({_view_clause(view, match_min)}{filtered}), 0)"
    acts = {"copy": ns_db.TRANSFER_ELIGIBLE["copy"], "move": ns_db.TRANSFER_ELIGIBLE["move"]}
    eligible_sql = ", ".join(f"COALESCE(p.status IN ({ns_db.sql_values(v)}), 0)" for v in acts.values())
    tree = {"all": 0, "photos": 0, **{k: 0 for k in acts}, "sub": {}}
    top = {"photos": 0, **{k: 0 for k in acts}}
    with catalog.connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT p.source_path, {shown}, {eligible_sql} FROM photos p "
            "WHERE p.source_path >= ? AND p.source_path < ?", params + (base, base[:-1] + "0"))
        for path, is_shown, *can in rows:
            parts = path[len(base):].split("/")[:-1]
            node = tree
            if not parts:
                node = top
            for name in parts:
                node = node["sub"].setdefault(name, {"all": 0, "photos": 0, **{k: 0 for k in acts}, "sub": {}})
                node["all"] += 1
                node["photos"] += is_shown
                for key, n in zip(acts, can):
                    node[key] += n
            if not parts:
                top["photos"] += is_shown
                for key, n in zip(acts, can):
                    top[key] += n
        outside = conn.execute(
            f"SELECT COUNT(*) FROM photos p WHERE {shown} AND NOT (p.source_path >= ? AND p.source_path < ?)",
            params + (base, base[:-1] + "0")).fetchone()[0]
    kept = {_folder(root, k) for k in keep or []}

    def listed(path, node):
        return node["photos"] > 0 or path in kept or any(k.startswith(path + "/") for k in kept)

    def build(prefix, sub):
        out = []
        for name in sorted(sub, key=lambda n: (n.casefold(), n)):
            node, path, label = sub[name], f"{prefix}{name}", name
            # One folder holding only one folder and no photos of its own: one row.
            while len(node["sub"]) == 1 and path not in kept:
                (child_name, child), = node["sub"].items()
                if child["all"] != node["all"]:          # it holds files of its own
                    break
                node, path, label = child, f"{path}/{child_name}", f"{label} / {child_name}"
            if listed(path, node):
                out.append({"path": path, "name": label, "photos": node["photos"],
                            "eligible": {k: node[k] for k in acts},
                            "folders": build(path + "/", node["sub"])})
        return out

    return {"folders": build("", tree["sub"]),
            "top_files": {"photos": top["photos"], "eligible": {k: top[k] for k in acts}},
            "outside": outside}


def thumbnail_record(conn, photo_id: int, size: int):
    """The cache record for a photo's content at `size`: (cache_filename, availability,
    failure_category, failure_detail), or None when nothing was recorded (pending)."""
    row = conn.execute(
        "SELECT t.cache_filename, t.availability, t.failure_category, t.failure_detail FROM photos p "
        "JOIN contents c ON c.hash_algorithm='sha1' AND c.digest = p.sha1_hash "
        "JOIN thumbnail_cache t ON t.content_id = c.content_id AND t.size = ? WHERE p.id = ?",
        (size, photo_id)).fetchone()
    return tuple(row) if row else None


def photo_exists(conn, photo_id: int) -> bool:
    return conn.execute("SELECT 1 FROM photos WHERE id = ?", (photo_id,)).fetchone() is not None


# The EXIF date fields and the offset tag each one pairs with (EXIF 2.31).
_EXIF_DATES = (("taken", "DateTimeOriginal", "OffsetTimeOriginal"),
               ("digitized", "CreateDate", "OffsetTimeDigitized"),
               ("modified", "ModifyDate", "OffsetTime"))


# Keys the engine adds to a photo's metadata beside ExifTool's tags: its own reading of
# the date, and where that reading came from.
_ENGINE_KEYS = {"date_taken", "date_source"}


def inspect_photo(db_path: Path, photo_id: int) -> Optional[dict]:
    """The Inspector's details (webui-spec 4.2, 6.2): paths, dates with their source,
    hashes, dimensions, camera, and every catalogued copy of the same content."""
    with catalog.connect(db_path) as conn:
        p = conn.execute(f"SELECT p.*, {_date_warning_sql()} AS date_warning FROM photos p WHERE id = ?", (photo_id,)).fetchone()
        if p is None:
            return None
        meta = json.loads(p["metadata_json"]) if p["metadata_json"] else {}
        content = conn.execute("SELECT width, height, phash, phash_state FROM contents WHERE digest = ?",
                               (p["sha1_hash"],)).fetchone() if p["sha1_hash"] else None
        copies = [dict(r) for r in conn.execute(
            "SELECT id, status, source_path, dest_path, file_size FROM photos "
            "WHERE sha1_hash = ? AND id != ? ORDER BY id", (p["sha1_hash"], photo_id))] if p["sha1_hash"] else []
        grid = thumbnail_record(conn, photo_id, catalog.GRID_SIZE)
        # The file's modification time as its first scan observed it (source_snapshots),
        # which later rescans, edits and transfers never overwrite (webui-spec 3.1).
        snapshot = conn.execute(
            "SELECT s.file_mtime FROM photo_files pf JOIN source_snapshots s USING(file_id) "
            "WHERE pf.photo_id = ?", (photo_id,)).fetchone()
    visual_issue = None
    if content is not None and (content['phash_state'] != 'ok' or not content['phash']):
        from engine import ns_similarity_recovery
        visual_issue = ns_similarity_recovery.describe({'kind':'missing_hash',
            'id':photo_id, 'dest_path':p['dest_path'] or p['source_path'] or '',
            'phash_state':content['phash_state']})['message']
    camera = " ".join(v for v in (meta.get("Make"), meta.get("Model")) if v) or None
    return {
        "id": p["id"], "status": p["status"],
        "filename": catalog._basename(p["dest_path"] if p["status"] in catalog.AT_DESTINATION else p["source_path"]),
        "source_path": p["source_path"], "dest_path": p["dest_path"],
        "dest_path_is_projection": p["status"] not in catalog.AT_DESTINATION,
        "has_collision_rename": bool(p["has_name_collision"]),
        "file_size": p["file_size"],
        "file_modified": snapshot["file_mtime"] if snapshot else p["file_mtime"],
        "date_taken": meta.get("date_taken"), "date_source": meta.get("date_source"),
        "date_warning": p["date_warning"],
        "camera": camera, "visual_issue": visual_issue,
        # A capture time's offset, when the camera recorded one; without it the
        # time zone is unknown and must not be shown as UTC (webui-spec 10).
        "date_offset": meta.get("OffsetTimeOriginal"),
        # Every EXIF date the photo carries, each with the offset recorded for it, if any.
        "exif_dates": [{"field": field, "value": meta[key], "offset": meta.get(offset_key)}
                       for field, key, offset_key in _EXIF_DATES if meta.get(key)],
        "iso": meta.get("ISO"), "aperture": meta.get("FNumber"), "shutter": meta.get("ExposureTime"),
        "width": content["width"] if content else None, "height": content["height"] if content else None,
        "sha1": p["sha1_hash"], "phash": p["phash"],
        "duplicates": copies,
        # Every tag the Index recorded (ExifTool's full set, not a curated subset), for
        # Show all metadata. The engine's own keys, which are not the photo's, are left out.
        "metadata": sorted(([k, v] for k, v in meta.items() if k not in _ENGINE_KEYS),
                           key=lambda kv: kv[0].lower()),
        "thumbnail": {"availability": grid[1] if grid else "pending",
                      "failure_category": grid[2] if grid else None,
                      "failure_detail": grid[3] if grid else None},
    }
