"""Catalog-only review decisions. No photo, transfer status or metadata is changed."""
import contextlib
import json
import re
from engine import ns_db

REASONS = ('small', 'later')
DELIVERED = "'Completed','Copied','Found_At_Destination'"
LIMIT_SQL = "(SELECT CAST(value_json AS INTEGER) FROM settings WHERE key='small_image_min' AND value_json!='null')"


def predicate(reason='all'):
    if reason not in ('all', *REASONS):
        raise ValueError('Unknown review reason')
    small = (f"p.status IN ({DELIVERED}) AND EXISTS (SELECT 1 FROM contents c WHERE c.hash_algorithm='sha1' "
             f"AND c.digest=p.sha1_hash AND c.width>0 AND c.height>0 AND min(c.width,c.height)<{LIMIT_SQL}) "
             "AND NOT EXISTS (SELECT 1 FROM review_events e WHERE e.photo_id=p.id AND e.reason='small' "
             "AND e.sha1=p.sha1_hash AND e.action='reviewed')")
    later = ("p.status NOT IN ('Duplicate','Removed_Duplicate','Rejected_Emptied') AND "
             "(SELECT e.action FROM review_events e WHERE e.photo_id=p.id AND e.reason='later' ORDER BY e.id DESC LIMIT 1)='later'")
    return {'small': small, 'later': later, 'all': f'(({small}) OR ({later}))'}[reason]


def details(conn, photo_id):
    row = conn.execute("SELECT id,status,sha1_hash FROM photos WHERE id=?", (photo_id,)).fetchone()
    if row is None:
        return None
    history = [dict(zip(('id','reason','action','note','created_at'), e)) for e in conn.execute(
        'SELECT id,reason,action,note,created_at FROM review_events WHERE photo_id=? ORDER BY id DESC', (photo_id,))]
    reasons = []
    for reason in REASONS:
        if conn.execute(f'SELECT 1 FROM photos p WHERE p.id=? AND ({predicate(reason)})', (photo_id,)).fetchone():
            if reason == 'small':
                dims = conn.execute("SELECT width,height FROM contents WHERE hash_algorithm='sha1' AND digest=?", (row[2],)).fetchone()
                limit = conn.execute(f'SELECT {LIMIT_SQL}').fetchone()[0]
                reasons.append({'reason': reason, 'label': 'Small image',
                    'message': f'{dims[0]} × {dims[1]} — below your {limit}-pixel minimum on the shorter side.'})
            else:
                note = next((e['note'] for e in history if e['reason']=='later'), '')
                reasons.append({'reason': reason, 'label': 'Review later', 'message': note or 'You asked to come back to this photo.'})
    return {'reasons': reasons, 'history': history, 'revision': history[0]['id'] if history else 0,
            'sha1': row[2], 'location': 'Library' if row[1] in ('Completed','Copied','Found_At_Destination') else
            'Rejects' if row[1] in ns_db.REJECTED_STATUSES else 'Not organized'}


def decide(db_path, body):
    if not isinstance(body, dict) or set(body) != {'photo_id','sha1','revision','reason','action','note','request_id'}:
        raise ValueError('Send the photo, content, revision, reason, action, note and request ID.')
    pid, reason, action = body['photo_id'], body['reason'], body['action']
    if type(pid) is not int or not 1 <= pid <= 2**63-1 or type(body['revision']) is not int or body['revision'] < 0:
        raise ValueError('Invalid photo or revision')
    if not isinstance(reason, str) or not isinstance(action, str) or reason not in REASONS or action not in ({'small': ('reviewed',), 'later': ('later','done')}[reason]):
        raise ValueError('Unknown review action')
    if not isinstance(body['note'], str) or len(body['note']) > 500 or (reason != 'later' and body['note']):
        raise ValueError('The optional Review later note must be at most 500 characters.')
    if not isinstance(body['request_id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', body['request_id']):
        raise ValueError('Invalid request ID')
    if body['sha1'] is not None and (not isinstance(body['sha1'], str) or not re.fullmatch(r'[0-9a-fA-F]{40}', body['sha1'])):
        raise ValueError('Invalid content hash')
    payload = json.dumps(body, sort_keys=True)
    with contextlib.closing(ns_db.connect(db_path, synchronous='FULL')) as conn:
        ns_db.require_schema(conn)
        with ns_db.transaction(conn):
            prior = conn.execute('SELECT payload FROM review_events WHERE request_id=?', (body['request_id'],)).fetchone()
            if prior:
                if prior[0] != payload:
                    raise ns_db.RevisionConflict('Request ID already used for another decision')
                return details(conn, pid)
            current = details(conn, pid)
            if current is None or current['sha1'] != body['sha1'] or current['revision'] != body['revision']:
                raise ns_db.RevisionConflict('The photo or review changed. Reload before deciding.')
            if action == 'later' and conn.execute("SELECT status FROM photos WHERE id=?", (pid,)).fetchone()[0] in ('Duplicate','Removed_Duplicate','Rejected_Emptied'):
                raise ns_db.RevisionConflict('This photo is no longer available for review.')
            if action != 'later' and reason not in [n['reason'] for n in current['reasons']]:
                raise ns_db.RevisionConflict('This reminder is no longer current. Reload the photo.')
            conn.execute('INSERT INTO review_events(photo_id,sha1,reason,action,note,created_at,request_id,payload) VALUES(?,?,?,?,?,?,?,?)',
                         (pid, body['sha1'], reason, action, body['note'], ns_db.utc_now(), body['request_id'], payload))
        return details(conn, pid)
