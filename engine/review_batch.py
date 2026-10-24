"""Bounded catalog-only review batches; no photo files are read or changed."""
import contextlib
import json
from pathlib import Path
from engine import ns_db, review

MAX_BYTES = 16 * 1024 * 1024
MAX_ITEMS = 50000
ACTIONS = {'small': ('small', 'reviewed'), 'date': ('date', 'correct'),
           'done': ('later', 'done'), 'keep': ('later', 'keep')}


def _ids(ids):
    if not isinstance(ids, list) or len(ids) > MAX_ITEMS:
        raise ValueError('Choose at most 50,000 photos for one review answer.')
    return ns_db.normalize_selection(ids)


def _predicate(action):
    reason, _ = ACTIONS[action]
    result = review.predicate(reason)
    if action == 'keep':
        result += " AND (SELECT json_extract(payload,'$.bookmark_reason') FROM review_events WHERE photo_id=p.id AND reason='later' ORDER BY id DESC LIMIT 1)='keep'"
    return result


def counts(conn, ids):
    if not ids or len(ids) > MAX_ITEMS:
        return dict.fromkeys(ACTIONS, 0)
    wanted = _ids(ids)
    fields = ','.join(f'COALESCE(SUM(({_predicate(action)})),0)' for action in ACTIONS)
    row = conn.execute(f'SELECT {fields} FROM photos p JOIN json_each(?) w ON w.value=p.id',
                       (json.dumps(wanted),)).fetchone()
    return dict(zip(ACTIONS, row))


def preview(conn, ids, action):
    wanted = _ids(ids)
    if action not in ACTIONS:
        raise ValueError('Choose a supported review answer.')
    reason, answer = ACTIONS[action]
    rows = conn.execute("SELECT p.id,p.sha1_hash,COALESCE((SELECT MAX(id) FROM review_events WHERE photo_id=p.id),0),"
        "json_extract(p.metadata_json,'$.date_taken'),COALESCE(p.dest_path,p.source_path),"
        f"({_predicate(action)}) FROM photos p JOIN json_each(?) w ON w.value=p.id ORDER BY p.id",
        (json.dumps(wanted),)).fetchall()
    items, skipped = [], []
    found = set()
    for pid, sha, revision, date, path, eligible in rows:
        found.add(pid)
        name = Path(path).name
        if not eligible:
            skipped.append(dict(photo_id=pid, filename=name, message='This answer no longer applies to this photo.'))
            continue
        decision = dict(photo_id=pid, sha1=sha, revision=revision, reason=reason, action=answer, note='')
        if reason == 'date':
            decision['date_taken'] = date
        items.append(dict(filename=name, decision=decision))
    skipped.extend(dict(photo_id=pid, filename=None, message='This photo is no longer in the catalog.') for pid in wanted if pid not in found)
    return dict(action=action, items=items, skipped=skipped, total=len(wanted))


def decide(db_path, body):
    if not isinstance(body, dict) or set(body) != {'items'} or not isinstance(body['items'], list) or not 1 <= len(body['items']) <= MAX_ITEMS:
        raise ValueError('Send one nonempty batch of review answers.')
    if len(json.dumps(body).encode()) > MAX_BYTES:
        raise ValueError('The review batch is too large.')
    ids, requests, actions = set(), set(), set()
    for item in body['items']:
        review.validate_decision(item)
        if item['photo_id'] in ids or item['request_id'] in requests:
            raise ValueError('Each photo and request must appear only once.')
        ids.add(item['photo_id']); requests.add(item['request_id'])
        actions.add((item['reason'], item['action']))
    if len(actions) != 1 or next(iter(actions)) not in ACTIONS.values():
        raise ValueError('A batch must use one shared review answer.')
    saved, skipped = [], []
    with contextlib.closing(ns_db.connect(db_path, synchronous='FULL')) as conn:
        ns_db.require_schema(conn)
        with ns_db.transaction(conn):
            for item in body['items']:
                try:
                    review._decide(conn, item)
                except ns_db.RevisionConflict as exc:
                    skipped.append(dict(photo_id=item['photo_id'], message=str(exc)))
                else:
                    saved.append(item['photo_id'])
    return dict(saved=saved, skipped=skipped)
