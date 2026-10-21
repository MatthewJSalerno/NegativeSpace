"""Read-only naming choices and validated rename previews for organized photos."""
import re
from engine import relocate
from . import catalog


def validate(photo_id, name=None):
    if type(photo_id) is not int or not 1 <= photo_id <= 2**63-1:
        raise ValueError("Choose a valid photo.")
    if name is not None and (not isinstance(name, str) or not name or len(name.encode('utf-8')) > 1024):
        raise ValueError("Enter a filename of at most 1,024 bytes.")


def require_library(cfg, photo_id):
    validate(photo_id)
    with catalog.connect(cfg.db_path) as conn:
        row = conn.execute("SELECT status FROM photos WHERE id=?", (photo_id,)).fetchone()
    if not row or row[0] not in ('Copied', 'Completed', 'Found_At_Destination'):
        raise ValueError("Rename is available for organized Library photos only.")


def candidates(cfg, photo_id):
    require_library(cfg, photo_id)
    result = relocate.rename_candidates(cfg.db_path, photo_id)
    if result['error']:
        raise ValueError(result['error'])
    return result


def preview(cfg, photo_id, body):
    if not isinstance(body, dict) or set(body) != {'name'}:
        raise ValueError("Supply the new filename only.")
    validate(photo_id, body['name'])
    if not isinstance(body['name'], str):
        raise ValueError("Enter a filename.")
    require_library(cfg, photo_id)
    result = relocate.preview_rename(cfg.db_path, cfg.dest, photo_id, body['name'])
    if result['error']:
        raise ValueError(result['error'])
    return result


def confirmed(photo_id, body):
    if not isinstance(body, dict) or set(body) != {'name', 'token', 'request_id'}:
        raise ValueError("Send the filename, preview token and request ID.")
    validate(photo_id, body['name'])
    if not isinstance(body['name'], str) or not isinstance(body['token'], str) or not re.fullmatch('[0-9a-f]{64}', body['token']):
        raise ValueError("Refresh the filename preview before saving.")
