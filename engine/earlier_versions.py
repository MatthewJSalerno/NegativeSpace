"""Earlier versions: source files whose bytes a verified Library edit replaced.

A file is an earlier version of a Library photo when its content is the before-content
of a recorded `file_changes` row for that photo and no organized photo has that content
now. It is held until the user answers (engine-spec 10, "Earlier versions: the agreed
behaviour"); only "Keep it as its own photo" lets it be organized.
"""
from engine import constants, ns_db

HOLD = ('This is an earlier version of a photo you edited in the Library. It stays in the '
        'source until you choose what to do with it in Not organized → Needs attention.')

# The content is current, not earlier, while a photo holding it is organized or rejected:
# an identical arrival is then an ordinary duplicate.
_HELD_IN_LIBRARY = constants.sql_values(constants.ANCHOR_DELIVERED_STATUSES + ns_db.REJECTED_STATUSES)


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
        f'AND NOT EXISTS(SELECT 1 FROM photos now WHERE now.sha1_hash=? AND now.status IN ({_HELD_IN_LIBRARY})) '
        'ORDER BY fc.change_id DESC LIMIT 1', (sha1, photo_id, sha1, sha1)).fetchone()


def record(conn, photo_id, version_of, change_id, run_id=None):
    """Link a source photo to the Library photo it is an earlier version of; first link wins."""
    conn.execute('INSERT OR IGNORE INTO photo_versions(photo_id,version_of,change_id,found_run_id,found_at) '
                 'VALUES(?,?,?,?,?)', (photo_id, version_of, change_id, run_id, ns_db.utc_now()))


def hold(conn, photo_id):
    """The hold message while this photo is an unanswered or not-kept earlier version."""
    row = conn.execute(
        'SELECT pv.answer FROM photo_versions pv JOIN photos p ON p.id=pv.photo_id '
        'JOIN file_changes fc ON fc.change_id=pv.change_id JOIN contents c ON c.content_id=fc.before_content_id '
        "WHERE pv.photo_id=? AND c.digest=p.sha1_hash", (photo_id,)).fetchone()
    return HOLD if row and row[0] != 'keep_separate' else None
