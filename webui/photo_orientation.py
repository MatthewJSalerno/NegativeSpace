"""Display applied orientation without changing content-keyed thumbnails or photo bytes."""
import io
import json

from PIL import Image
from fastapi.responses import FileResponse, Response

# EXIF's mirrored cases must remain mirrored when the user turns the displayed image.
CLOCKWISE = {1: 6, 6: 3, 3: 8, 8: 1, 2: 7, 7: 4, 4: 5, 5: 2}
TRANSPOSE = {2: Image.Transpose.FLIP_LEFT_RIGHT, 3: Image.Transpose.ROTATE_180,
             4: Image.Transpose.FLIP_TOP_BOTTOM, 5: Image.Transpose.TRANSPOSE,
             6: Image.Transpose.ROTATE_270, 7: Image.Transpose.TRANSVERSE,
             8: Image.Transpose.ROTATE_90}
INVERSE = {6: 8, 8: 6}


def turned(value, turns):
    if type(value) is not int or value not in CLOCKWISE or type(turns) is not int or turns not in (0, 1, 2, 3):
        raise ValueError('Choose a quarter turn, half turn or reset.')
    for _ in range(turns):
        value = CLOCKWISE[value]
    return value


def state(conn, photo_id):
    row = conn.execute('SELECT sha1_hash,status FROM photos WHERE id=?', (photo_id,)).fetchone()
    event = conn.execute("SELECT e.detail_json FROM operations o JOIN operation_events e ON e.operation_id=o.id "
        "WHERE o.photo_id=? AND e.step IN ('metadata_saved','metadata_activated','photo_metadata_activated') "
        'ORDER BY e.event_id DESC LIMIT 1', (photo_id,)).fetchone()
    if not row or not event or row[1] not in ('Copied','Completed','Found_At_Destination','Rejected','Rejected_Copied'):
        return 1, 1
    receipt = json.loads(event[0])
    if receipt.get('sha1_hash', row[0]) != row[0]:
        return 1, 1
    sources = receipt.get('sources')
    if sources is None:
        capture = conn.execute('SELECT report_json FROM metadata_captures WHERE capture_id=?',
                               (receipt.get('capture_id'),)).fetchone()
        sources = json.loads(capture[0]).get('sources', {}) if capture else {}
    embedded = sources.get('exif', {}).get('fields', {}).get('orientation', 1)
    if type(embedded) is not int or embedded not in CLOCKWISE:
        embedded = 1
    effective = receipt.get('resolution', {}).get('proposed_effective', {}).get('orientation', embedded)
    if type(effective) is not int or effective not in CLOCKWISE:
        effective = embedded
    return embedded, effective


def transform(image, embedded, effective):
    """The cache already applied embedded orientation. Undo it before applying XMP."""
    if embedded == effective:
        return image
    inverse = INVERSE.get(embedded, embedded)
    if inverse in TRANSPOSE:
        image = image.transpose(TRANSPOSE[inverse])
    return image.transpose(TRANSPOSE[effective]) if effective in TRANSPOSE else image


def response(conn, photo_id, path):
    embedded, effective = state(conn, photo_id)
    if embedded == effective:
        return FileResponse(path, media_type='image/jpeg', headers={'Cache-Control': 'no-cache'})
    # Only the small disposable preview is decoded. Neither the photo nor its
    # sidecar is opened here, and no shared cache entry is overwritten.
    with Image.open(path) as image:
        output = io.BytesIO()
        transform(image, embedded, effective).save(output, format='PNG')
    return Response(output.getvalue(), media_type='image/png', headers={'Cache-Control': 'no-store'})


def dimensions(conn, photo_id, width, height):
    embedded, effective = state(conn, photo_id)
    return (height, width) if (embedded in (5,6,7,8)) != (effective in (5,6,7,8)) else (width, height)
