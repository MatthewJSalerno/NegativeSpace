"""Date confirmations and transactional history for computed review concerns.

The gallery remains read-only. Catalog triggers record facts disappearing in the
same transaction as their cause; confirmations are small indexed current state,
with every deliberate answer retained in append-only review_events.
"""
import json
from engine import ns_db

DELIVERED = "'Completed','Copied','Found_At_Destination'"
MIN_YEAR_SQL = f"COALESCE((SELECT CAST(value_json AS INTEGER) FROM settings WHERE key='suspicious_min_year'),{ns_db.SUSPICIOUS_MIN_YEAR_DEFAULT})"
MIN_SIZE_SQL = "(SELECT CAST(value_json AS INTEGER) FROM settings WHERE key='small_image_min' AND value_json!='null')"


def date_value(alias='p'):
    return f"json_extract({alias}.metadata_json,'$.date_taken')"


def year_warning_sql(year, minimum=MIN_YEAR_SQL, latest="(CAST(strftime('%Y','now') AS INTEGER)+1)", subject='Recorded year'):
    return (f"CASE WHEN {year}<{minimum} THEN '{subject} is before your earliest expected year (' || {minimum} || ').' "
            f"WHEN {year}>{latest} THEN '{subject} is more than one year ahead of the current year.' END")


def date_warning_sql(alias='p', minimum=MIN_YEAR_SQL, latest="(CAST(strftime('%Y','now') AS INTEGER)+1)"):
    value = date_value(alias)
    year = f"CAST(substr({value},1,4) AS INTEGER)"
    return (f"CASE WHEN {alias}.status!='Failed' AND {value} GLOB '[0-9][0-9][0-9][0-9]-*' "
            f"THEN {year_warning_sql(year, minimum, latest)} END")


def confirmed_sql(alias='p'):
    return (f"EXISTS (SELECT 1 FROM review_date_confirmations d WHERE d.photo_id={alias}.id "
            f"AND d.date_taken={date_value(alias)})")


def date_pending_sql(alias='p', minimum=MIN_YEAR_SQL, latest="(CAST(strftime('%Y','now') AS INTEGER)+1)"):
    return (f"{alias}.status IN ({DELIVERED}) AND ({date_warning_sql(alias, minimum, latest)}) IS NOT NULL "
            f"AND NOT ({confirmed_sql(alias)})")


def small_pending_sql(alias='p', minimum=MIN_SIZE_SQL, dimensions=None):
    dims = dimensions or (f"EXISTS (SELECT 1 FROM contents c WHERE c.hash_algorithm='sha1' "
        f"AND c.digest={alias}.sha1_hash AND c.width>0 AND c.height>0 AND min(c.width,c.height)<{minimum})")
    return (f"{alias}.status IN ({DELIVERED}) AND ({dims}) AND NOT EXISTS "
            f"(SELECT 1 FROM review_events e WHERE e.photo_id={alias}.id AND e.reason='small' "
            f"AND e.sha1={alias}.sha1_hash AND e.action='reviewed')")


def confirm_date(conn, photo_id, value, event_id):
    if not conn.in_transaction:
        raise RuntimeError('Date confirmation requires the outcome transaction')
    conn.execute('INSERT INTO review_date_confirmations VALUES(?,?,?) ON CONFLICT(photo_id) '
                 'DO UPDATE SET date_taken=excluded.date_taken,event_id=excluded.event_id', (photo_id, value, event_id))


def record_saved_date(conn, photo_id, operation_id, preview, metadata, sha1):
    """Only an explicitly supplied date is confirmed, after its bytes are verified.

    Call before updating photos within the SAME outcome transaction. The triggers
    retain this new confirmation and avoid a second generic clearing event. Primary
    switches, rotations, absent/cleared dates and fallback timestamps aren't answers.
    """
    chosen = preview.get('changes', {}).get('date_taken')
    value = metadata.get('date_taken')
    if not chosen or chosen != value or metadata.get('date_source') == 'file_mtime':
        return
    if not conn.in_transaction:
        raise RuntimeError('Saved date requires the outcome transaction')
    request = f'date-saved:{operation_id}'
    if conn.execute('SELECT 1 FROM review_events WHERE request_id=?', (request,)).fetchone():
        return
    run_id = conn.execute('SELECT run_id FROM operations WHERE id=?', (operation_id,)).fetchone()[0]
    payload = json.dumps({'date_taken':value,'operation_id':operation_id,'run_id':run_id}, sort_keys=True)
    event = conn.execute("INSERT INTO review_events(photo_id,sha1,reason,action,note,created_at,request_id,payload) "
        "VALUES(?,?,'date','date_saved','',?,?,?)", (photo_id, sha1, ns_db.utc_now(), request, payload)).lastrowid
    confirm_date(conn, photo_id, value, event)


def _cleared(reason, cause, where, source='photos p', alias='p'):
    # Random internal IDs make independent transitions distinct. Rollback includes
    # both this event and its cause; repeating a settled update cannot add a row.
    return ("INSERT INTO review_events(photo_id,sha1,reason,action,note,created_at,request_id,payload) "
        f"SELECT {alias}.id,{alias}.sha1_hash,'{reason}','cleared','',strftime('%Y-%m-%dT%H:%M:%f','now')||'+00:00',"
        f"'auto:'||lower(hex(randomblob(16))),json_object('cause','{cause}') FROM {source} WHERE {where};")


def ddl():
    # Capture OLD eligibility before invalidating confirmation. Replacing the date
    # with another suspicious value keeps the concern pending rather than clearing it.
    date_clear = _cleared('date', 'date_changed',
        f"p.id=NEW.id AND OLD.status IN ({DELIVERED}) AND NEW.status IN ({DELIVERED}) "
        f"AND ({date_pending_sql('OLD')}) AND ({date_warning_sql('NEW')}) IS NULL AND NOT ({confirmed_sql('NEW')})")
    small_clear = _cleared('small', 'dimensions_changed',
        f"p.id=NEW.id AND OLD.status IN ({DELIVERED}) AND NEW.status IN ({DELIVERED}) "
        f"AND ({small_pending_sql('OLD')}) AND EXISTS (SELECT 1 FROM contents c WHERE c.hash_algorithm='sha1' "
        f"AND c.digest=NEW.sha1_hash AND c.width>0 AND c.height>0 AND min(c.width,c.height)>={MIN_SIZE_SQL})")
    old_size = "(CASE WHEN OLD.value_json!='null' THEN CAST(OLD.value_json AS INTEGER) END)"
    old_year = "CAST(OLD.value_json AS INTEGER)"
    statements = [
        "CREATE TABLE review_calendar (id INTEGER PRIMARY KEY CHECK(id=1), year INTEGER NOT NULL)",
        "INSERT INTO review_calendar VALUES(1,CAST(strftime('%Y','now') AS INTEGER))",
        "CREATE TABLE review_date_confirmations (photo_id INTEGER PRIMARY KEY REFERENCES photos(id), "
        "date_taken TEXT NOT NULL, event_id INTEGER NOT NULL REFERENCES review_events(id))",
        # Index temporarily projects source metadata before restoring the verified
        # destination. Invalidate only its final destination projection, never the
        # intermediate Pending/Duplicate source row within that scan transaction.
        # Clearing must inspect the prior answer BEFORE deleting it, in one trigger.
        f"CREATE TRIGGER review_photo_date AFTER UPDATE OF metadata_json,status ON photos "
        f"WHEN NEW.status IN ({DELIVERED},'Rejected','Rejected_Copied') BEGIN "
        + date_clear + f" DELETE FROM review_date_confirmations WHERE photo_id=NEW.id AND date_taken IS NOT {date_value('NEW')}; END",
        "CREATE TRIGGER review_photo_size AFTER UPDATE OF sha1_hash ON photos WHEN OLD.sha1_hash IS NOT NEW.sha1_hash BEGIN "
        + small_clear + ' END',
        "CREATE TRIGGER review_size_setting AFTER UPDATE OF value_json ON settings "
        "WHEN NEW.key='small_image_min' AND OLD.value_json IS NOT NEW.value_json BEGIN "
        + _cleared('small', 'size_rule_changed', f"({small_pending_sql(minimum=old_size)}) AND NOT ({small_pending_sql()})") + ' END',
        "CREATE TRIGGER review_date_setting AFTER UPDATE OF value_json ON settings "
        "WHEN NEW.key='suspicious_min_year' AND OLD.value_json IS NOT NEW.value_json BEGIN "
        + _cleared('date', 'date_rule_changed', f"({date_pending_sql(minimum=old_year)}) AND NOT ({date_pending_sql()})") + ' END',
    ]
    def dims(alias):
        return f"{alias}.width>0 AND {alias}.height>0 AND min({alias}.width,{alias}.height)<{MIN_SIZE_SQL}"
    statements.append("CREATE TRIGGER review_date_setting_first AFTER INSERT ON settings "
        "WHEN NEW.key='suspicious_min_year' BEGIN "
        + _cleared('date', 'date_rule_changed', f"({date_pending_sql(minimum=str(ns_db.SUSPICIOUS_MIN_YEAR_DEFAULT))}) AND NOT ({date_pending_sql()})") + ' END')
    statements.append("CREATE TRIGGER review_content_size AFTER UPDATE OF width,height ON contents "
        "WHEN NEW.hash_algorithm='sha1' AND (OLD.width IS NOT NEW.width OR OLD.height IS NOT NEW.height) BEGIN "
        + _cleared('small', 'dimensions_changed', f"p.sha1_hash=NEW.digest AND ({small_pending_sql(dimensions=dims('OLD'))}) "
                   f"AND NEW.width>0 AND NEW.height>0 AND min(NEW.width,NEW.height)>={MIN_SIZE_SQL}") + ' END')
    return statements


def reconcile_calendar(conn, run_id):
    """Once per year, at the next job; browsing never writes history."""
    previous = conn.execute('SELECT year FROM review_calendar WHERE id=1').fetchone()[0]
    current = int(conn.execute("SELECT strftime('%Y','now')").fetchone()[0])
    if current <= previous:
        return
    if not conn.in_transaction:
        raise RuntimeError('Calendar review requires the job transaction')
    statement = _cleared('date', 'calendar_year_changed',
        f"({date_pending_sql(latest=str(previous+1))}) AND NOT ({date_pending_sql()})")
    statement = statement.replace("json_object('cause','calendar_year_changed')",
                                  "json_object('cause','calendar_year_changed','run_id',?)")
    conn.execute(statement, (run_id,))
    conn.execute('UPDATE review_calendar SET year=? WHERE id=1', (current,))
