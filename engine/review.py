"""Catalog-only review decisions. No photo, transfer status or metadata is changed."""
import contextlib
import json
import re
from engine import ns_db, attention, review_history

# Internal event reason 'later' is the personal bookmark, separate from size review.
BOOKMARK_REASONS = {
    'date': 'Check the date', 'compare': 'Compare versions', 'rotation': 'Fix rotation',
    'details': 'Check the details', 'keep': 'Decide whether to keep it',
    'ask': 'Ask someone', 'other': 'Other',
}
REASONS = ('small', 'later', 'date')

DELIVERED = "'Completed','Copied','Found_At_Destination'"
LIMIT_SQL = "(SELECT CAST(value_json AS INTEGER) FROM settings WHERE key='small_image_min' AND value_json!='null')"


def predicate(reason='all'):
    if reason not in ('all', 'issues', *REASONS):
        raise ValueError('Unknown review reason')
    small = review_history.small_pending_sql()
    date = review_history.date_pending_sql()
    later = (f"p.status IN ({DELIVERED}) AND "
             "(SELECT e.action FROM review_events e WHERE e.photo_id=p.id AND e.reason='later' ORDER BY e.id DESC LIMIT 1)='later'")
    issues = f"p.status IN ({DELIVERED}) AND ({attention.predicate()})"
    return {'small': small, 'later': later, 'issues': issues, 'date': date, 'all': f'(({small}) OR ({later}) OR ({issues}) OR ({date}))'}[reason]


def details(conn, photo_id):
    row = conn.execute("SELECT id,status,sha1_hash,metadata_json FROM photos WHERE id=?", (photo_id,)).fetchone()
    if row is None:
        return None
    history = [dict(zip(('id','reason','action','note','created_at', 'payload'), e)) for e in conn.execute(
        'SELECT id,reason,action,note,created_at,payload FROM review_events WHERE photo_id=? ORDER BY id DESC', (photo_id,))]
    preset = 'other'
    for event in reversed(history):
        payload = json.loads(event.pop('payload'))
        event.update({key:payload[key] for key in ('cause','date_taken','run_id') if key in payload})
        if event['reason'] == 'later' and event['action'] == 'later':
            preset = payload.get('bookmark_reason', 'date')
        event['bookmark_reason'] = preset if event['reason'] == 'later' else None
    meta = json.loads(row[3] or '{}')
    warning = conn.execute(f'SELECT {review_history.date_warning_sql()}, {review_history.confirmed_sql()} FROM photos p WHERE p.id=?', (photo_id,)).fetchone()
    source = meta.get('date_source')
    source_label = 'file modification fallback' if source == 'file_mtime' else 'photo EXIF' if source == 'exif' else source or 'unknown'
    date_message = f"Recorded value: {meta.get('date_taken')}. Source: {source_label}. {warning[0] or ''}"
    reasons = []
    for reason in REASONS:
        if conn.execute(f'SELECT 1 FROM photos p WHERE p.id=? AND ({predicate(reason)})', (photo_id,)).fetchone():
            if reason == 'small':
                dims = conn.execute("SELECT width,height FROM contents WHERE hash_algorithm='sha1' AND digest=?", (row[2],)).fetchone()
                limit = conn.execute(f'SELECT {LIMIT_SQL}').fetchone()[0]
                reasons.append({'reason': reason, 'label': 'Small image',
                    'message': f'{dims[0]} × {dims[1]} — below your {limit}-pixel minimum on the shorter side.'})
            elif reason == 'date':
                reasons.append({'reason':'date','label':'Suspicious date','message':date_message})
            else:
                note = next((e['note'] for e in history if e['reason']=='later'), '')
                preset = next(e['bookmark_reason'] for e in history if e['reason'] == 'later')
                reasons.append({'reason': reason, 'label': BOOKMARK_REASONS.get(preset, 'Other'),
                                'message': note, 'bookmark_reason': preset})
    return {'reasons': reasons, 'history': history, 'revision': history[0]['id'] if history else 0,
            'date_taken':meta.get('date_taken'), 'date_confirmed':bool(warning[1]),
            'date_warning':warning[0], 'date_message':date_message, 'sha1': row[2], 'location': 'Library' if row[1] in ('Completed','Copied','Found_At_Destination') else
            'Rejects' if row[1] in ns_db.REJECTED_STATUSES else 'Not organized'}


def validate_decision(body):
    if not isinstance(body, dict) or set(body) - {'bookmark_reason','date_taken'} != {'photo_id','sha1','revision','reason','action','note','request_id'}:
        raise ValueError('Send the photo, content, revision, reason, action, note and request ID.')
    pid, reason, action = body['photo_id'], body['reason'], body['action']
    if type(pid) is not int or not 1 <= pid <= 2**63-1 or type(body['revision']) is not int or body['revision'] < 0:
        raise ValueError('Invalid photo or revision')
    if not isinstance(reason, str) or not isinstance(action, str) or reason not in REASONS or action not in ({'small': ('reviewed',), 'later': ('later','done','keep'), 'date': ('correct',)}[reason]):
        raise ValueError('Unknown review action')
    if not isinstance(body['note'], str) or len(body['note']) > 60 or (reason != 'later' and body['note']):
        raise ValueError('The optional Bookmark note must be at most 60 characters.')
    if reason == 'date' and (not isinstance(body.get('date_taken'), str) or not body['date_taken']):
        raise ValueError('Send the recorded date you are confirming.')
    if reason != 'date' and 'date_taken' in body:
        raise ValueError('A recorded date applies only to date confirmation.')
    preset = body.get('bookmark_reason', 'date')
    if not isinstance(preset, str) or preset not in BOOKMARK_REASONS:
        raise ValueError('Choose a valid Bookmark reason.')
    if reason != 'later' and 'bookmark_reason' in body:
        raise ValueError('Bookmark reasons apply only to bookmarks.')
    if not isinstance(body['request_id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', body['request_id']):
        raise ValueError('Invalid request ID')
    if body['sha1'] is not None and (not isinstance(body['sha1'], str) or not re.fullmatch(r'[0-9a-fA-F]{40}', body['sha1'])):
        raise ValueError('Invalid content hash')


def _decide(conn, body):
    pid, reason, action = body['photo_id'], body['reason'], body['action']
    preset = body.get('bookmark_reason', 'date')
    payload = json.dumps(body, sort_keys=True)
    prior = conn.execute('SELECT payload FROM review_events WHERE request_id=?', (body['request_id'],)).fetchone()
    if prior:
        if prior[0] != payload:
            raise ns_db.RevisionConflict('Request ID already used for another decision')
        return details(conn, pid)
    current = details(conn, pid)
    if current is None or current['sha1'] != body['sha1'] or current['revision'] != body['revision']:
        raise ns_db.RevisionConflict('The photo or review changed. Reload before deciding.')
    if reason == 'date' and current['date_taken'] != body['date_taken']:
        raise ns_db.RevisionConflict('The date changed. Reload before confirming it.')
    if current['location'] != 'Library':
        raise ns_db.RevisionConflict('Only organized photos in Library can be reviewed.')
    if action != 'later' and reason not in [n['reason'] for n in current['reasons']]:
        raise ns_db.RevisionConflict('This reminder is no longer current. Reload the photo.')
    note = body['note']
    if reason == 'later' and action != 'later':
        latest = next(e for e in current['history'] if e['reason'] == 'later')
        preset, note = latest['bookmark_reason'], latest['note']
        if action == 'keep' and preset != 'keep':
            raise ValueError('Keep it applies to a keep-decision bookmark.')
    # Payload remains exact request evidence for replay. Completion inherits the
    # reason/note through history; creation records a validated preset.
    event = conn.execute('INSERT INTO review_events(photo_id,sha1,reason,action,note,created_at,request_id,payload) VALUES(?,?,?,?,?,?,?,?)',
                 (pid, body['sha1'], reason, action, note, ns_db.utc_now(), body['request_id'], payload)).lastrowid
    if reason == 'date':
        review_history.confirm_date(conn, pid, body['date_taken'], event)
    return details(conn, pid)


def decide(db_path, body):
    validate_decision(body)
    with contextlib.closing(ns_db.connect(db_path, synchronous='FULL')) as conn:
        ns_db.require_schema(conn)
        with ns_db.transaction(conn):
            return _decide(conn, body)
