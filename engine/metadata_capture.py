"""Read-only qualified photo capture and three-source resolution for Index evidence.

These are observations, not primary-source activation or transfer dates. ExifTool
reads an already-open descriptor through procfs in the supported Linux container.
No caller-controlled path is reopened by the external reader.
"""
import contextlib
import copy
import os
from pathlib import Path
import re
import stat

from engine import fileinfo, metadata_adapter, metadata_gps, xmp
from engine.metadata import MetadataSource

VERSION = 3
_EXIF_KEYS = set(metadata_adapter._EMBEDDED) | metadata_adapter.GPS_KEYS | {
    'ExifIFD:DateTimeOriginal', 'ExifIFD:SubSecTimeOriginal', 'ExifIFD:OffsetTimeOriginal'}
_XMP_KEYS = {'XMP-exif:DateTimeOriginal': 'date_taken', 'XMP-tiff:Make': 'camera_make',
             'XMP-tiff:Model': 'camera_model', 'XMP-tiff:Orientation': 'orientation',
             'XMP-xmp:Rating': 'rating', 'XMP-dc:Title': 'title',
             'XMP-dc:Description': 'caption', 'XMP-dc:Rights': 'rights',
             'XMP-dc:Subject': 'keywords', 'XMP-dc:Creator': 'creators'}

_GPS_KEYS = {'XMP-exif:'+name for name in metadata_gps.PARTS}


def signature(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


@contextlib.contextmanager
def open_source(root, relative_name, *, directory=False):
    """Keep descriptors for the whole chain; reject any replaced name on exit."""
    relative = Path('.') if relative_name == '.' and directory else xmp.relative_path(relative_name)
    absolute = Path(os.path.abspath(root))
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
    with contextlib.ExitStack() as stack:
        def opened(name, flags, parent=None):
            fd = os.open(name, flags, dir_fd=parent)
            stack.callback(os.close, fd)
            return fd
        folder = opened('/', flags | os.O_DIRECTORY)
        chain = []
        parts = (*absolute.parts[1:], *relative.parts)
        for pos, part in enumerate(parts):
            is_dir = directory or pos < len(parts) - 1
            child = opened(part, flags | (os.O_DIRECTORY if is_dir else os.O_NONBLOCK), folder)
            chain.append((folder, part, child))
            folder = child
        before = os.fstat(folder)
        if not directory and not stat.S_ISREG(before.st_mode):
            raise ValueError('not_regular')
        yield folder, before
        if signature(before) != signature(os.fstat(folder)):
            raise ValueError('changed_during_read')
        for parent, name, child in chain:
            named = os.stat(name, dir_fd=parent, follow_symlinks=False)
            held = os.fstat(child)
            if (named.st_dev, named.st_ino) != (held.st_dev, held.st_ino):
                raise ValueError('changed_during_read')


def _qualified(tags):
    """Family 4 preserves repeats; never collapse conflicting copies of a tag."""
    values, conflicts = {}, set()
    for key, value in tags.items():
        parts = key.split(':')
        if len(parts) < 2:
            continue
        if any(re.fullmatch(r'Copy[0-9]+', p) is None for p in parts[1:-1]):
            conflicts.add(parts[0] + ':' + parts[-1])
            continue
        canonical = parts[0] + ':' + parts[-1]
        if canonical in values and values[canonical] != value:
            conflicts.add(canonical)
        values[canonical] = value
    return values, conflicts


def interpret(tags):
    """Keep qualified evidence separately, and map only explicitly supported fields."""
    values, conflicts = _qualified(tags)
    sources, issues = {}, []
    try:
        if conflicts & _EXIF_KEYS:
            raise ValueError('ambiguous_embedded_exif')
        source = metadata_adapter.from_embedded({k:v for k,v in values.items() if k in _EXIF_KEYS}, source_id='exif')
        sources['exif'] = {'kind': 'embedded_exif', 'fields': source.fields}
    except ValueError as exc:
        issues.append({'source': 'exif', 'code': str(exc)})
    fields = {}
    try:
        if any(k in _XMP_KEYS or k in _GPS_KEYS or k.startswith(('XMP-dc:Title-', 'XMP-dc:Description-', 'XMP-dc:Rights-')) for k in conflicts):
            raise ValueError('ambiguous_embedded_xmp')
        for key, field in _XMP_KEYS.items():
            if key not in values:
                continue
            value = values[key]
            if field == 'date_taken' and isinstance(value, str):
                # ExifTool prints even XMP dates using EXIF separators; retain raw
                # evidence above and change separators only in the comparison view.
                value = value[:10].replace(':', '-') + value[10:]
                if len(value) > 10 and value[10] == ' ':
                    value = value[:10] + 'T' + value[11:]
            if field in ('keywords', 'creators'):
                if isinstance(value, str) and value != '':
                    value = [value]
                if value != '' and (not isinstance(value, list) or any(not isinstance(v, str) for v in value)):
                    raise ValueError('unsupported_embedded_xmp_property')
            fields[field] = value
        for key, field in (('XMP-dc:Title', 'title'), ('XMP-dc:Description', 'caption'), ('XMP-dc:Rights', 'rights')):
            localized = {k[len(key)+1:]: v for k,v in values.items() if k.startswith(key+'-')}
            if localized:
                if key in values:
                    localized['x-default'] = values[key]
                if any(not isinstance(v, str) for v in localized.values()):
                    raise ValueError('unsupported_embedded_xmp_property')
                fields[field] = localized
            elif field in fields and not isinstance(fields[field], str):
                raise ValueError('unsupported_embedded_xmp_property')
        if any(k in values for k in _GPS_KEYS):
            fields['gps']=metadata_gps.from_embedded(values,xmp=True)
        # The adapter's embedded kind permits a canonical comparison without
        # claiming an original standalone sidecar packet exists for embedded tags.
        normalized = metadata_adapter.for_comparison(MetadataSource('embedded_xmp', 'embedded', {}, fields))
        if any(key.startswith('XMP-') for key in values):
            sources['embedded_xmp'] = {'kind': 'embedded_xmp', 'fields': normalized.fields}
    except ValueError as exc:
        issues.append({'source': 'embedded_xmp', 'code': str(exc)})
    return {'version': VERSION, 'tags': tags, 'sources': sources, 'issues': issues}


def capture_photo(root, relative_name, expected_size, expected_mtime, previous=None, force=False):
    """Capture a stable photo; cached evidence is reused only with identical stat identity.

    The catalog digest remains the normal Index digest. Stat binding is not a second
    hash verification; use --force-rehash for suspected content changes with preserved
    timestamps. No original packet/blob is inferred from ExifTool's parsed tag JSON.
    """
    try:
        with open_source(root, relative_name) as (fd, info):
            if info.st_size != expected_size or abs(info.st_mtime - expected_mtime) >= 1e-6:
                raise ValueError('changed_since_photo_index')
            if (not force and previous and previous.get('version') == VERSION
                    and previous.get('signature') == signature(info) and not previous.get('issues')):
                result = copy.deepcopy(previous)
            else:
                if fileinfo._worker_exiftool is None:
                    raise ValueError('qualified_reader_unavailable')
                proc_path = f'/proc/{os.getpid()}/fd/{fd}'
                records = fileinfo._worker_exiftool.get_metadata([proc_path], params=[
                    '-G1:4', '-a', '-n', '-struct', '-api', 'StructFormat=JSONQ'])
                if len(records) != 1:
                    raise ValueError('qualified_reader_failed')
                # Filesystem/transport fields describe the held descriptor; the
                # catalog already records the actual file path and stat information.
                tags = {k:v for k,v in records[0].items()
                        if ':' in k and k.split(':')[0] not in ('File', 'System', 'SourceFile')}
                result = interpret(tags)
                # Reader warnings describe metadata we may not understand, not an
                # inability to transfer the original bytes. Keep errors blocking.
                result['warnings'] = []
                for key, value in tags.items():
                    if key.startswith('ExifTool:') and key.endswith(':Warning'):
                        result['warnings'].append({'source': 'photo', 'code': 'embedded_reader_warning', 'detail': str(value)})
                    elif key.startswith('ExifTool:') and key.endswith(':Error'):
                        result['issues'].append({'source': 'photo', 'code': 'embedded_reader_error', 'detail': str(value)})
                result['signature'] = signature(info)
        return result
    except Exception as exc:
        code = str(exc) if type(exc) is ValueError else ('read_error' if isinstance(exc, OSError) else 'qualified_reader_failed')
        detail = f'{exc.errno}: {exc.strerror}' if isinstance(exc, OSError) else str(exc)
        return {'version': VERSION, 'sources': {}, 'tags': {}, 'issues': [{'source':'photo','code':code,'detail':detail, **({'errno':exc.errno} if isinstance(exc,OSError) else {})}]}


def resolve(sources, priority, *, primary_id=None):
    """Explicit priority over captured canonical fields; no silent activation/write."""
    order = list(priority)
    if len(set(order)) != len(order) or any(key not in sources for key in order):
        raise ValueError('invalid_source_priority')
    if primary_id is not None:
        if primary_id not in sources:
            raise ValueError('unknown_primary')
        # A deliberate EXIF-only choice must not refill missing fields from XMP.
        order = ['exif'] if primary_id == 'exif' else [primary_id] + [k for k in ('embedded_xmp','exif') if k in sources and k != primary_id]
    effective, origins = {}, {}
    for source_id in order:
        for field, value in sources[source_id]['fields'].items():
            if field not in effective:
                effective[field] = copy.deepcopy(value)
                origins[field] = source_id
    return {'priority': order, 'proposed_effective': effective, 'field_sources': origins,
            'proposed_primary': order[0] if order else None, 'applied': False}
