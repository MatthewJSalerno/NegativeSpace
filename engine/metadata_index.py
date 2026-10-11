"""Provenance observations for Index and transfer preflight; no new metadata activation.

A capture stores proposed values separately from filing. Reindex restores an established
import projection from its verified receipt; it never applies a newly observed source.
Sidecar originals use the existing immutable BLOB/arrival store. Complete same-folder
photo inventories precede selections and extension filters when planning ownership.
"""
import contextlib
import dataclasses
import itertools
import hashlib
import json
import os
from pathlib import Path

from engine import constants, deps, metadata_adapter, metadata_capture, metadata_decisions, metadata_import, ns_db, runtime, workers, xmp, xmp_association, xmp_store


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _folder(root, relative_parent):
    photos, sidecars = [], {}
    with metadata_capture.open_source(root, relative_parent, directory=True) as (fd, _):
        with os.scandir(fd) as entries:
            for entry in entries:
                if entry.name.startswith('.'):
                    continue
                path = Path(relative_parent) / entry.name
                if path.suffix.lower() == '.xmp':
                    # Unsafe/nonregular sidecars must be reported, not treated as
                    # absent. The descriptor reader refuses them without following.
                    sidecars.setdefault(path.stem, []).append(path.as_posix())
                elif path.suffix.lower() in ns_db.SUPPORTED_EXTENSIONS and entry.is_file(follow_symlinks=False):
                    photos.append(path.as_posix())
    return xmp_association.PhotoInventory(photos), sidecars


def _sidecars(root, relative_photo, inventory, by_name, *, policy="ask", conn=None, source_ids=None, highwater=0):
    photo = Path(relative_photo)
    names = sorted(set(by_name.get(photo.name, []) + by_name.get(photo.stem, [])))
    result = []
    for name in names:
        capture = xmp.read_sidecar(root, name, source_id='sidecar:' + name)
        association = inventory.associate(name, capture, policy=policy)
        if conn is not None:
            association = metadata_decisions.saved_association(conn, str(root), name, association,
                source_ids, highwater=highwater)
        association = dataclasses.replace(association, candidates=inventory.associate(name, capture, policy='ask').photos)
        result.append((name, capture, association))
    return result


def build_report(relative_photo, embedded, sidecars, *, policy="ask"):
    sources = dict(embedded['sources'])
    issues = list(embedded['issues'])
    observations, active = [], []
    for name, captured, association in sidecars:
        source_id = 'sidecar:' + name
        observation = {'path': name, 'state': association.state, 'code': association.reason,
                       'candidates': list(association.photos), 'all_candidates': list(association.candidates or association.photos),
                       'basis': association.basis}
        if captured.original_bytes is not None:
            observation['sha256'] = hashlib.sha256(captured.original_bytes).hexdigest()
        if captured.source is not None:
            normalized = metadata_adapter.for_comparison(captured.source)
            sources[source_id] = {'kind': 'sidecar_xmp', 'fields': normalized.fields}
        if captured.detail:
            observation['detail'] = captured.detail
        observations.append(observation)
        if association.state in ('needs_choice', 'needs_attention'):
            issue = {'source': source_id, 'code': association.reason}
            if captured.detail:
                issue['detail'] = captured.detail
            issues.append(issue)
        if association.state == 'associated' and relative_photo in association.photos:
            active.append((name, observation.get('sha256'), association.basis))
    full = [item for item in active if Path(item[0]).stem == Path(relative_photo).name]
    candidates = full or active
    chosen = None
    if candidates:
        if len({item[1] for item in candidates}) == 1:
            chosen = 'sidecar:' + sorted(candidates)[0][0]
        else:
            issues.append({'source': 'sidecars', 'code': 'metadata_choice_needed'})
    report = {'version': 1, 'mode': 'capture_only', 'applied': False, 'association_policy': policy,
              'sources': sources, 'sidecars': observations, 'issues': issues}
    if issues:
        report['state'] = 'needs_attention'
    else:
        report['state'] = 'captured'
        order = ([chosen] if chosen else []) + [key for key in ('embedded_xmp', 'exif') if key in sources]
        report['resolution'] = metadata_capture.resolve(sources, order)
    return report


def retain(conn, *, run_id, row, relative_photo, embedded, report, sidecars, source_ids):
    """Atomic final observation and BLOB arrivals. Identical re-index is a no-op."""
    photo_id, source_path, file_id, sha1, size, mtime, old_embedded, old_report = row
    embedded_json, report_json = _json(embedded), _json(report)
    if old_embedded == embedded_json and old_report == report_json:
        return False
    with ns_db.transaction(conn):
        for name, captured, association in sidecars:
            if captured.original_bytes is None or captured.state == 'not_xmp':
                continue
            participants = sorted({source_ids[p] for p in association.photos if p in source_ids})
            if not participants:
                continue  # Unindexed candidates remain named in the observation.
            # Ownership is tentative until the choice workflow is integrated. Preserve
            # all known candidate identities, never activate a version during capture.
            xmp_store.retain_capture(conn, data=captured.original_bytes, run_id=run_id,
                source_relative_path=name, file_ids=participants, role='candidate', basis='unresolved')
        conn.execute('INSERT INTO metadata_captures(run_id,file_id,source_relative_path,catalog_sha1,'
            'embedded_json,report_json,observed_at) VALUES(?,?,?,?,?,?,?)',
            (run_id, file_id, relative_photo, sha1, embedded_json, report_json, ns_db.utc_now()))
    return True


def capture_index(db_path, run_id, root, candidates, *, worker_count, log_dir, force=False):
    """Capture the completed Index scope, including sidecar-only changes on re-index.

    Copy/Move also capture before preflight so direct transfers cannot bypass metadata
    holds. No observation authorizes filing or source cleanup. Existing primary decisions
    remain separate immutable records and are never overwritten by a new observation.
    """
    root = Path(root)
    if not candidates:
        return True
    with contextlib.closing(ns_db.connect(db_path, synchronous='FULL')) as conn:
        config = json.loads(conn.execute('SELECT effective_config_json FROM run_configs WHERE run_id=?', (run_id,)).fetchone()[0])
        policy = config.get('xmp_association', 'ask')
        highwater = config.get('metadata_decision_highwater', 0)
        conn.execute('CREATE TEMP TABLE metadata_scope(path TEXT PRIMARY KEY)')
        conn.executemany('INSERT OR IGNORE INTO metadata_scope VALUES(?)', ((p,) for p in candidates))
        conn.commit()
        consumed = constants.sql_values(constants.SOURCE_CONSUMED_STATUSES)
        # This identity map includes catalogued siblings outside the selection;
        # on-disk inventory below also includes supported siblings never indexed.
        ids_by_folder = {}
        for path, file_id in conn.execute('SELECT p.source_path,pf.file_id FROM photos p JOIN photo_files pf ON pf.photo_id=p.id ORDER BY p.id'):
            try:
                relative = Path(path).relative_to(root)
                ids_by_folder.setdefault(relative.parent.as_posix(),{})[relative.as_posix()] = file_id
            except ValueError:
                pass
        query = ('SELECT p.id,p.source_path,pf.file_id,fo.sha1_hash,fo.file_size,fo.file_mtime,'
            'mc.embedded_json,mc.report_json FROM metadata_scope s JOIN photos p ON p.source_path=s.path '
            'JOIN photo_files pf ON pf.photo_id=p.id JOIN file_observations fo ON fo.observation_id='
            '(SELECT observation_id FROM file_observations WHERE file_id=pf.file_id ORDER BY observation_id DESC LIMIT 1) '
            'LEFT JOIN metadata_captures mc ON mc.capture_id='
            '(SELECT capture_id FROM metadata_captures WHERE file_id=pf.file_id ORDER BY capture_id DESC LIMIT 1) '
            f'WHERE p.status NOT IN ({consumed},?) AND p.file_size IS NOT NULL AND p.file_mtime IS NOT NULL '
            'AND (p.source_path,p.id)>(?,?) ORDER BY p.source_path,p.id LIMIT ?')
        eligible = conn.execute('SELECT COUNT(*) FROM metadata_scope s JOIN photos p ON p.source_path=s.path '
            'JOIN photo_files pf ON pf.photo_id=p.id '
            f'WHERE p.status NOT IN ({consumed},?) AND p.file_size IS NOT NULL AND p.file_mtime IS NOT NULL',
            (ns_db.PhotoStatus.FAILED,)).fetchone()[0]
        runtime.run_progress.start('metadata', eligible)
        done = changed = attention = 0
        batch_size = max(worker_count * 4, 16)
        def rows():
            # Exhaust each bounded read before writes through this connection or
            # the separate progress connection. An open cursor pins an old WAL
            # snapshot, which cannot be upgraded after progress commits elsewhere.
            last_path,last_id='',0
            while True:
                batch=conn.execute(query,(ns_db.PhotoStatus.FAILED,last_path,last_id,batch_size)).fetchall()
                if not batch:return
                last_id,last_path=batch[-1][:2]
                yield from batch

        with workers.pool(worker_count, deps.EXIFTOOL_SUPPORTED, log_dir) as executor:
            for folder, group in itertools.groupby(rows(), key=lambda row: str(Path(row[1]).parent)):
                if runtime.cancel_requested.is_set():
                    return False
                relative_parent = Path(folder).relative_to(root).as_posix()
                try:
                    inventory, sidecar_names = _folder(root, relative_parent)
                    folder_error = None
                except (OSError, ValueError) as exc:
                    inventory, sidecar_names = None, {}
                    folder_error = str(exc)
                # Recorded owners survive a partial Move. A new identity at the same
                # source path still replaces the map entry and invalidates old ownership.
                folder_ids = ids_by_folder.get(relative_parent,{}) if inventory else {}
                while batch := list(itertools.islice(group, batch_size)):
                    futures = [executor.submit(metadata_capture.capture_photo, str(root),
                        Path(row[1]).relative_to(root).as_posix(), row[4], row[5],
                        json.loads(row[6]) if row[6] else None, force) for row in batch]
                    for row, embedded in zip(batch, workers.results(futures)):
                        relative_photo = Path(row[1]).relative_to(root).as_posix()
                        if folder_error:
                            embedded['issues'].append({'source':'folder','code':'source_directory_unreadable_or_changed','detail':folder_error})
                        sidecars = _sidecars(root, relative_photo, inventory, sidecar_names, policy=policy, conn=conn,
                            source_ids=folder_ids, highwater=highwater) if inventory else []
                        report = build_report(relative_photo, embedded, sidecars, policy=policy)
                        if retain(conn, run_id=run_id, row=row, relative_photo=relative_photo,
                                  embedded=embedded, report=report, sidecars=sidecars, source_ids=folder_ids):
                            changed += 1
                        metadata_import.restore_delivered(conn,row[0])
                        if report['issues']:
                            attention += 1
                            codes = ', '.join(sorted({item['code'] + (': ' + item['detail'] if item.get('detail') else '')
                                                     for item in report['issues']}))
                            runtime.logger.warning(f'Metadata capture needs attention for {relative_photo}: {codes}. '
                                'Review the source metadata or sidecar association, correct it externally, then run Index again. '
                                'No new metadata choice or file edit was applied.')
                        done += 1
                        runtime.run_progress.set_count('Captured', done)
                        runtime.run_progress.maybe_write_now()
                    if runtime.cancel_requested.is_set():
                        return False
        runtime.run_progress.write_now()
        runtime.logger.info(f'Metadata capture: {done} photos inspected, {changed} new observations, '
                            f'{attention} needing attention. Priority results are recorded only; filing metadata is unchanged.')
    return True
