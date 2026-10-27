"""Earlier versions: source files whose bytes a verified Library edit replaced.

A file is an earlier version of a Library photo when its content is the before-content
of a recorded `file_changes` row for that photo. Each change found for a source photo is
its own link, and answers belong to a link, so new bytes at the same path never inherit
an answer about other bytes. A photo is held while its current content matches a link and
no organized or rejected photo has that content (then it is an ordinary duplicate), until
the user answers (engine-spec 10, "Earlier versions: the agreed behaviour"). Only "Keep it
as its own photo" lets it be organized. Links and answers are appended, never replaced.
"""
import contextlib
import json
import re
import sqlite3

from engine import constants, metadata_capture, ns_db

HOLD = ('This is an earlier version of a photo you edited in the Library. It stays in the '
        'source until you choose what to do with it in Not organized → Needs attention.')
NOT_KEPT = ('You chose not to keep this earlier version of a Library photo. It stays in the '
            'source untouched; NegativeSpace never removes it.')
ANSWERS = ('not_kept', 'keep_separate')
_IN_SOURCE = ('Pending', 'Duplicate')
_CURRENT = constants.sql_values(constants.ANCHOR_DELIVERED_STATUSES + ns_db.REJECTED_STATUSES)
# Recorded tags interpret() maps to named fields; any other changed tag is shown by name.
_TRANSLATED = metadata_capture._EXIF_KEYS | set(metadata_capture._XMP_KEYS) | metadata_capture._GPS_KEYS
_LOCALIZED = ('XMP-dc:Title-', 'XMP-dc:Description-', 'XMP-dc:Rights-')


def find(conn, sha1, photo_id):
    """(version_of, change_id) when this content is an earlier version of another photo."""
    if not sha1:
        return None
    return conn.execute(
        # The changed file is the Library copy; the edit's operation names its photo.
        'SELECT o.photo_id, fc.change_id FROM contents c '
        'JOIN file_changes fc ON fc.before_content_id=c.content_id '
        'JOIN operation_events e ON e.event_id=fc.event_id JOIN operations o ON o.id=e.operation_id '
        'JOIN photos p ON p.id=o.photo_id '
        "WHERE c.hash_algorithm='sha1' AND c.digest=? AND o.photo_id<>? AND p.sha1_hash<>? "
        f'AND NOT EXISTS(SELECT 1 FROM photos now WHERE now.sha1_hash=? AND now.status IN ({_CURRENT})) '
        'ORDER BY fc.change_id DESC LIMIT 1', (sha1, photo_id, sha1, sha1)).fetchone()


def record(conn, photo_id, version_of, change_id, run_id=None):
    """Link a source photo to the Library photo it is an earlier version of, once per change."""
    conn.execute('INSERT OR IGNORE INTO photo_versions(photo_id,version_of,change_id,found_run_id,found_at) '
                 'VALUES(?,?,?,?,?)', (photo_id, version_of, change_id, run_id, ns_db.utc_now()))


_LINKS = ('FROM photo_versions pv JOIN file_changes fc ON fc.change_id=pv.change_id '
          'JOIN contents c ON c.content_id=fc.before_content_id')


def link_sql(alias='p'):
    """The link shown for photo `alias`: the newest for its current content, else its newest."""
    return (f'COALESCE((SELECT MAX(pv.link_id) {_LINKS} WHERE pv.photo_id={alias}.id AND c.digest={alias}.sha1_hash), '
            f'(SELECT MAX(link_id) FROM photo_versions WHERE photo_id={alias}.id))')


def state_sql(alias='p'):
    """'waiting', 'not_kept' or 'keep_separate' while photo `alias` is a held-or-answered
    earlier version; NULL once it is not one, recomputed from recorded facts."""
    return (f"(SELECT COALESCE((SELECT a.answer FROM photo_version_answers a WHERE a.link_id=pv.link_id "
            f"ORDER BY a.answer_id DESC LIMIT 1),'waiting') {_LINKS} "
            f"WHERE pv.photo_id={alias}.id AND c.digest={alias}.sha1_hash AND NOT EXISTS(SELECT 1 FROM photos now "
            f"WHERE now.sha1_hash={alias}.sha1_hash AND now.status IN ({_CURRENT})) ORDER BY pv.link_id DESC LIMIT 1)")


def hold(conn, photo_id):
    """The hold message while this photo is an unanswered or not-kept earlier version."""
    row = conn.execute(f'SELECT {state_sql()} FROM photos p WHERE p.id=?', (photo_id,)).fetchone()
    state = row[0] if row else None
    return HOLD if state == 'waiting' else NOT_KEPT if state == 'not_kept' else None


def badges(conn, photo_ids):
    """Version links for one bounded page of cards, both directions, in two queries."""
    if not photo_ids:
        return {}
    ids = json.dumps(photo_ids)
    result = {}
    for pid, version_of, state in conn.execute(
            f'SELECT p.id, pv.version_of, {state_sql()} FROM photos p JOIN photo_versions pv ON pv.link_id={link_sql()} '
            'WHERE p.id IN (SELECT value FROM json_each(?))', (ids,)):
        result[pid] = dict(version_of=version_of, state=state, earlier_versions=0, waiting=0)
    for version_of, count, waiting in conn.execute(
            f"SELECT pv.version_of, COUNT(DISTINCT p.sha1_hash), COUNT(DISTINCT CASE WHEN {state_sql()}='waiting' "
            'THEN p.sha1_hash END) FROM photo_versions pv JOIN photos p ON p.id=pv.photo_id '
            'WHERE pv.version_of IN (SELECT value FROM json_each(?)) GROUP BY pv.version_of', (ids,)):
        entry = result.setdefault(version_of, dict(version_of=None, state=None, earlier_versions=0, waiting=0))
        entry.update(earlier_versions=count, waiting=waiting)
    return result


def _differences(before_json, after_json):
    """Named-field and untranslated-tag differences between two recorded tag sets."""
    before, after = json.loads(before_json or '{}'), json.loads(after_json or '{}')
    named_before = metadata_capture.interpret(before)['sources']
    named_after = metadata_capture.interpret(after)['sources']
    fields = []
    for source in sorted(set(named_before) | set(named_after)):
        old = named_before.get(source, {}).get('fields', {})
        new = named_after.get(source, {}).get('fields', {})
        for field in sorted(set(old) | set(new)):
            if old.get(field) != new.get(field):
                fields.append(dict(source=source, field=field, before=old.get(field), after=new.get(field)))
    old_tags, _ = metadata_capture._qualified(before)
    new_tags, _ = metadata_capture._qualified(after)
    tags = [dict(tag=key, before=old_tags.get(key), after=new_tags.get(key))
            for key in sorted(set(old_tags) | set(new_tags))
            if old_tags.get(key) != new_tags.get(key) and key not in _TRANSLATED and not key.startswith(_LOCALIZED)]
    return fields, tags


def _location(status):
    return ('Library' if status in constants.ANCHOR_DELIVERED_STATUSES else
            'Rejects' if status in ns_db.REJECTED_STATUSES else 'Not organized')


def _filing(row):
    """The date this photo is (or will be) filed by, as its catalog row records it."""
    meta = json.loads(row['metadata_json'] or '{}')
    return dict(date_taken=meta.get('date_taken'), date_source=meta.get('date_source'))


def _name(row):
    path = row['dest_path'] if row['status'] in constants.ANCHOR_DELIVERED_STATUSES + ns_db.REJECTED_STATUSES else row['source_path']
    return (path or '').rsplit('/', 1)[-1]


def details(conn, photo_id):
    """Both directions of this photo's version links, with the full recorded change list."""
    def query(sql, params):
        cursor = conn.cursor()
        cursor.row_factory = sqlite3.Row
        return cursor.execute(sql, params)
    me = query(f'SELECT p.id,p.status,p.sha1_hash,p.source_path,p.dest_path,p.metadata_json,{state_sql()} AS state '
                      'FROM photos p WHERE p.id=?', (photo_id,)).fetchone()
    if me is None:
        return None
    link = query(f'SELECT pv.link_id,pv.version_of,pv.change_id,pv.found_at FROM photos p '
                 f'JOIN photo_versions pv ON pv.link_id={link_sql()} WHERE p.id=?', (photo_id,)).fetchone()
    earlier = None
    if link:
        target = query('SELECT id,status,sha1_hash,source_path,dest_path,metadata_json FROM photos WHERE id=?',
                              (link['version_of'],)).fetchone()
        changes = [dict(change_id=r['change_id'], operation_id=r['operation_id'], at=r['timestamp'],
                        run_id=r['run_id'], mode=r['mode'],
                        **dict(zip(('fields', 'tags'), _differences(r['before_values_json'], r['after_values_json']))))
                   for r in query(
                       'SELECT fc.*, e.operation_id, e.timestamp, o.run_id, r.mode FROM file_changes fc '
                       'JOIN operation_events e ON e.event_id=fc.event_id JOIN operations o ON o.id=e.operation_id '
                       'JOIN runs r ON r.id=o.run_id '
                       'WHERE o.photo_id=? AND fc.change_id>=? ORDER BY fc.change_id', (target['id'], link['change_id']))]
        # Only verified embedded edits prove the picture itself is unchanged.
        from engine import metadata_reproduce
        try:
            metadata_reproduce._image_chain(conn, target['id'], me['sha1_hash'], target['sha1_hash'])
            same_picture = True
        except ValueError:
            same_picture = False
        answers = [dict(answer=r['answer'], at=r['created_at']) for r in query(
            'SELECT answer,created_at FROM photo_version_answers WHERE link_id=? ORDER BY answer_id', (link['link_id'],))]
        earlier = dict(version_of=dict(id=target['id'], filename=_name(target), location=_location(target['status']),
                                       split_operation_id=changes[0]['operation_id'] if changes else None,
                                       split_at=changes[0]['at'] if changes else None, filing=_filing(target)),
                       state=me['state'], found_at=link['found_at'], same_picture=same_picture, filing=_filing(me),
                       changes=changes, answers=answers,
                       answerable=me['state'] is not None and me['status'] in _IN_SOURCE)
    # split_operation_id: the newest edit whose change replaced that photo's content, for the timeline.
    versions = [dict(id=r['id'], filename=_name(r), location=_location(r['status']), state=r['state'],
                     split_operation_id=r['operation_id'])
                for r in query(f'SELECT p.id,p.status,p.source_path,p.dest_path,{state_sql()} AS state,'
                               '(SELECT e.operation_id FROM photo_versions l JOIN file_changes fc ON fc.change_id=l.change_id '
                               'JOIN operation_events e ON e.event_id=fc.event_id WHERE l.photo_id=p.id AND l.version_of=:me '
                               'ORDER BY l.link_id DESC LIMIT 1) AS operation_id FROM photos p '
                               "WHERE p.id IN (SELECT photo_id FROM photo_versions WHERE version_of=:me) "
                               "AND p.status<>'Duplicate' ORDER BY p.id", {'me': photo_id})]
    # The current link's answers: a link the photo no longer holds the bytes of keeps its own.
    revision = conn.execute('SELECT COALESCE(MAX(answer_id),0) FROM photo_version_answers WHERE link_id=?',
                            (link['link_id'] if link else None,)).fetchone()[0]
    return dict(photo_id=photo_id, revision=revision, earlier_version=earlier, earlier_versions=versions)


def validate_answer(body):
    if not isinstance(body, dict) or set(body) != {'photo_id', 'answer', 'revision', 'request_id'}:
        raise ValueError('Send the photo, answer, revision and request ID.')
    if type(body['photo_id']) is not int or not 1 <= body['photo_id'] <= 2**63-1:
        raise ValueError('Invalid photo')
    if type(body['revision']) is not int or body['revision'] < 0:
        raise ValueError('Invalid revision')
    if body['answer'] not in ANSWERS:
        raise ValueError('Unknown answer')
    if not isinstance(body['request_id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', body['request_id']):
        raise ValueError('Invalid request ID')


def _answer(conn, body):
    pid = body['photo_id']
    payload = json.dumps(body, sort_keys=True)
    prior = conn.execute('SELECT payload FROM photo_version_answers WHERE request_id=? LIMIT 1',
                         (body['request_id'],)).fetchone()
    if prior:
        if prior[0] != payload:
            raise ns_db.RevisionConflict('Request ID already used for another answer')
        return details(conn, pid)
    current = details(conn, pid)
    earlier = current and current['earlier_version']
    if not earlier or not earlier['answerable']:
        raise ns_db.RevisionConflict('This photo is no longer an earlier version waiting in the source. Reload it.')
    if current['revision'] != body['revision']:
        raise ns_db.RevisionConflict('The answer changed. Reload the photo before answering.')
    if earlier['state'] == body['answer']:
        raise ns_db.RevisionConflict('That is already the answer. Reload the photo.')
    # Identical files are interchangeable: the answer covers every copy of this content
    # in the source, including duplicates shown only on this card and copies linked to
    # another edit. Each is appended to that copy's own current link.
    copies = [r[0] for r in conn.execute(
        f'SELECT {link_sql()} FROM photos p WHERE p.sha1_hash=(SELECT sha1_hash FROM photos WHERE id=?) '
        f'AND p.status IN ({constants.sql_values(_IN_SOURCE)}) AND {state_sql()} IS NOT NULL', (pid,))]
    now = ns_db.utc_now()
    for link in copies:
        conn.execute('INSERT INTO photo_version_answers(link_id,answer,request_id,payload,created_at) VALUES(?,?,?,?,?)',
                     (link, body['answer'], body['request_id'], payload, now))
    return details(conn, pid)


def answer(db_path, body):
    validate_answer(body)
    with contextlib.closing(ns_db.connect(db_path, synchronous='FULL')) as conn:
        ns_db.require_schema(conn)
        with ns_db.transaction(conn):
            return _answer(conn, body)


def read(db_path, photo_id):
    with contextlib.closing(ns_db.connect(db_path)) as conn:
        ns_db.require_schema(conn)
        conn.execute('BEGIN')
        return details(conn, photo_id)
