"""Pure comparison views for qualified embedded captures and validated XMP sources.

Index uses these views for capture-only evidence, never filing or file writes.
Original tags/sidecar bytes remain unchanged;
canonical fields are a comparison view, not a replacement for captured evidence.
Legacy flat/print-converted Index metadata is deliberately not accepted as qualified
ExifTool output. IPTC mapping/precedence remains a separate decision.
"""

import re
from decimal import Decimal

from engine import metadata, metadata_gps, xmp
from engine.metadata import MetadataSource

_EMBEDDED = {'IFD0:Make': 'camera_make', 'IFD0:Model': 'camera_model',
             'IFD0:Orientation': 'orientation', 'IFD0:XPTitle':'title',
             'IFD0:ImageDescription':'caption','IFD0:Copyright':'rights',
             'IFD0:Artist':'creators','IFD0:XPKeywords':'keywords','IFD0:Rating':'rating'}
GPS_KEYS = {'GPS:'+name for name in metadata_gps.PARTS} | {'GPS:GPSLatitudeRef','GPS:GPSLongitudeRef'}
_DATE = 'ExifIFD:DateTimeOriginal'
_FRACTION = 'ExifIFD:SubSecTimeOriginal'
_OFFSET = 'ExifIFD:OffsetTimeOriginal'
_EXIF_DATE = re.compile(r'[0-9]{4}:[0-9]{2}:[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}')


def for_comparison(source: MetadataSource) -> MetadataSource:
    """Normalize supported scalar representations without changing captured evidence.

    XMP input comes from the bounded reader, not arbitrary unvalidated XML. Preserve
    date precision and recorded offsets: no time-zone conversions, date completion,
    whitespace trimming, array sorting or inferred textual aliases. A mapped invalid
    value refuses this view; callers must not use that refusal as embedded fallback.
    """
    if (source.kind not in ('embedded', 'xmp') or not isinstance(source.source_id, str)
            or not source.source_id.strip()):
        raise ValueError('invalid_source')
    if ((source.kind == 'embedded' and source.original_bytes is not None)
            or (source.kind == 'xmp' and not isinstance(source.original_bytes, bytes))):
        raise ValueError('invalid_original')
    tags = metadata._json_copy(dict(source.tags))
    fields = metadata._json_copy(dict(source.fields))
    for field in ('date_taken', 'orientation', 'rating', 'camera_make', 'camera_model'):
        if field not in fields:
            continue
        value = fields[field]
        if value == '':
            continue
        if field == 'orientation':
            if type(value) is int and 1 <= value <= 8:
                continue
            if not isinstance(value, str) or xmp._ORIENTATION.fullmatch(value) is None:
                raise ValueError('invalid_orientation')
            fields[field] = int(value)
        elif field == 'rating':
            # Decimal parsing and fixed formatting do not round through float/context.
            if not isinstance(value, str) or xmp._REAL.fullmatch(value) is None:
                raise ValueError('invalid_rating')
            number = Decimal(value)
            if not (number == -1 or 0 <= number <= 5):
                raise ValueError('invalid_rating')
            text = format(number, 'f')
            if '.' in text:
                text = text.rstrip('0').rstrip('.')
            fields[field] = '0' if number == 0 else text
        elif field == 'date_taken':
            if not isinstance(value, str) or not xmp._valid_date(value):
                raise ValueError('invalid_date_taken')
            # Z and explicit positive zero describe the same recorded offset. Keep
            # negative zero separate; never assume an absent offset means UTC.
            fields[field] = value[:-1] + '+00:00' if value.endswith('Z') else value
        elif not isinstance(value, str):
            raise ValueError('invalid_' + field)
    for field in ('title','caption','rights'):
        if field not in fields:continue
        value=fields[field]
        if not isinstance(value,str) and (not isinstance(value,dict) or
                any(not isinstance(k,str) or not k or not isinstance(v,str) for k,v in value.items())):
            raise ValueError('invalid_'+field)
    for field in ('keywords','creators'):
        if field in fields and fields[field]!='' and (not isinstance(fields[field],list)
                or any(not isinstance(v,str) for v in fields[field])):
            raise ValueError('invalid_'+field)
    if 'gps' in fields:fields['gps']=metadata_gps.validate(fields['gps'])
    return MetadataSource(source.source_id, source.kind, tags, fields, source.original_bytes)


def from_embedded(tags: dict, *, source_id: str) -> MetadataSource:
    """Map initial EXIF fields from family-1 qualified, non-print-converted tags.

    Capture with ExifTool -G1 -n and JSONQ to preserve numeric-looking strings. Use
    this only when the reader established unambiguous tag instances; this helper
    cannot recover duplicates a JSON dict or an extraction already discarded.
    IFD1 thumbnails, MakerNotes, embedded XMP and file/composite dates are retained
    but never guessed to be the IFD0/ExifIFD originals. Unsupported date components
    refuse the view instead of silently losing information or falling back to mtime.
    """
    copied = metadata._json_copy(tags)
    if not isinstance(copied, dict) or any(':' not in key and key != 'SourceFile' for key in copied):
        raise ValueError('qualified_tags_required')
    fields = {field: copied[tag] for tag, field in _EMBEDDED.items() if tag in copied}
    if 'creators' in fields:
        if not isinstance(fields['creators'],str):raise ValueError('invalid_creators')
        fields['creators']=[fields['creators']] if fields['creators'] else []
    if 'keywords' in fields:
        if not isinstance(fields['keywords'],str):raise ValueError('invalid_keywords')
        # XPKeywords is semicolon-delimited. Preserve whitespace/order verbatim.
        fields['keywords']=fields['keywords'].split(';') if fields['keywords'] else []
    if any(key in copied for key in GPS_KEYS):fields['gps']=metadata_gps.from_embedded(copied)
    if _DATE not in copied:
        if _FRACTION in copied or _OFFSET in copied:
            raise ValueError('date_components_without_date')
    else:
        value = copied[_DATE]
        if value == '':
            fields['date_taken'] = ''
        else:
            if not isinstance(value, str) or _EXIF_DATE.fullmatch(value) is None:
                raise ValueError('invalid_date_taken')
            value = value[:10].replace(':', '-') + 'T' + value[11:]
            if _FRACTION in copied:
                fraction = copied[_FRACTION]
                if not isinstance(fraction, str) or re.fullmatch(r'[0-9]+', fraction) is None:
                    raise ValueError('invalid_date_fraction')
                value += '.' + fraction
            if _OFFSET in copied:
                offset = copied[_OFFSET]
                if not isinstance(offset, str) or re.fullmatch(r'[+-][0-9]{2}:[0-9]{2}', offset) is None:
                    raise ValueError('invalid_date_offset')
                value += offset
            fields['date_taken'] = value
    return for_comparison(MetadataSource(source_id, 'embedded', copied, fields))
