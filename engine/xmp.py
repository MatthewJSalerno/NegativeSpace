"""Bounded read-only XMP capture for the planned import pipeline.

Not connected to Index/Copy/Move. Preserve original bytes and qualified XML trees;
only explicitly supported RDF forms enter canonical fields. No XML resource is fetched.
"""

import calendar
import contextlib
import os
import re
import stat
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path, PurePosixPath
from xml.parsers import expat

from engine.metadata import MetadataSource

RDF = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'
XML = 'http://www.w3.org/XML/1998/namespace'
XMP_META = 'adobe:ns:meta/'
EXIF = 'http://ns.adobe.com/exif/1.0/'
TIFF = 'http://ns.adobe.com/tiff/1.0/'
DC = 'http://purl.org/dc/elements/1.1/'
XAP = 'http://ns.adobe.com/xap/1.0/'
CRS = 'http://ns.adobe.com/camera-raw-settings/1.0/'

# Safety ceilings, not tuned performance thresholds. Over-limit inputs are held,
# never classified as junk or silently truncated. Change only with fixture evidence.
MAX_BYTES = 8 * 1024 * 1024
MAX_DEPTH = 64
MAX_NODES = 50000
MAX_ATTRIBUTES = 100000


def _tag(namespace, local):
    return '{' + namespace + '}' + local


# Validate supported values, preserving lexical precision and unknown time zones.
# CreateDate is not a capture-date alias. The Index date adapter is a separate step.
FIELD_TAGS = {
    _tag(EXIF, 'DateTimeOriginal'): 'date_taken',
    _tag(TIFF, 'Make'): 'camera_make',
    _tag(TIFF, 'Model'): 'camera_model',
    _tag(TIFF, 'Orientation'): 'orientation',
    _tag(XAP, 'Rating'): 'rating',
    _tag(DC, 'title'): 'title',
    _tag(DC, 'description'): 'caption',
    _tag(DC, 'subject'): 'keywords',
    _tag(DC, 'creator'): 'creators',
    _tag(DC, 'rights'): 'rights',
}
_ARRAY_FIELDS = {'keywords': 'Bag', 'creators': 'Seq'}
_LOCALIZED_FIELDS = {'caption', 'title', 'rights'}


@dataclass(frozen=True)
class ReadResult:
    """Only valid results may supply effective values; all other states carry a code.

    Nonvalid complete captures retain original bytes for later preservation/inspection.
    Missing/unstable/over-limit reads have no original bytes: never archive a partial read.
    source is available only for valid, supported captures. tags are qualified XML
    property snapshots (lists preserve repeated properties), not flattened short names.
    """
    state: str
    code: str
    original_bytes: bytes | None = None
    source: MetadataSource | None = None
    tags: dict | None = None
    owner_name: str | None = None
    detail: str | None = None


class _Refused(ValueError):
    pass


def relative_path(value: str) -> PurePosixPath:
    """A catalog-relative POSIX path. Reject instead of normalizing unsafe input."""
    if (not isinstance(value, str) or not value or '\x00' in value or '\\' in value
            or any(part in ('', '.', '..') for part in value.split('/'))):
        raise ValueError('Expected a nonempty relative path without traversal.')
    path = PurePosixPath(value)
    if path.is_absolute():
        raise ValueError('Expected a relative path.')
    return path


def _qualified(name):
    return '{' + name if '}' in name else name


def _tree(data):
    parser = expat.ParserCreate(namespace_separator='}')
    parser.buffer_text = True
    stack, roots = [], []
    nodes = attributes = 0

    def start(name, attrs):
        nonlocal nodes, attributes
        nodes += 1
        attributes += len(attrs)
        if nodes > MAX_NODES or attributes > MAX_ATTRIBUTES or len(stack) >= MAX_DEPTH:
            raise _Refused('xml_limit')
        node = {'name': _qualified(name),
                'attributes': {_qualified(k): v for k, v in attrs.items()},
                'text': [], 'children': []}
        (stack[-1]['children'] if stack else roots).append(node)
        stack.append(node)

    def end(name):
        stack[-1]['text'] = ''.join(stack[-1]['text'])
        stack.pop()

    def text(value):
        if stack:
            # Retain all character data, including whitespace. Original bytes are
            # authoritative for ordering/formatting; this tree is for inspection.
            stack[-1]['text'].append(value)

    def forbidden(*args):
        raise _Refused('unsafe_xml')

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = text
    parser.StartDoctypeDeclHandler = forbidden
    parser.EntityDeclHandler = forbidden
    parser.ExternalEntityRefHandler = forbidden
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    # One bounded buffer avoids repeated parsing of an unfinished large token on
    # older Expat versions. DTDs/entities are refused before expansion.
    parser.Parse(data, True)
    return roots[0]


def _literal(node):
    attrs = node['attributes']
    if node['children'] or set(attrs) - {_tag(XML, 'lang')}:
        raise _Refused('unsupported_property')
    return node['text']


def _field_value(field, node):
    children = node['children']
    if not children:
        if field in _LOCALIZED_FIELDS and _tag(XML, 'lang') in node['attributes']:
            return {node['attributes'][_tag(XML, 'lang')]: _literal(node)}
        return _literal(node)
    if node['attributes'] or node['text'].strip() or len(children) != 1:
        raise _Refused('unsupported_property')
    array = children[0]
    if array['attributes'] or array['text'].strip():
        raise _Refused('unsupported_property')
    if field in _LOCALIZED_FIELDS and array['name'] == _tag(RDF, 'Alt'):
        values = {}
        for item in array['children']:
            lang = item['attributes'].get(_tag(XML, 'lang'))
            if item['name'] != _tag(RDF, 'li') or not lang or lang in values:
                raise _Refused('unsupported_property')
            values[lang] = _literal(item)
        return values
    if field in _ARRAY_FIELDS and array['name'] == _tag(RDF, _ARRAY_FIELDS[field]):
        values = []
        for item in array['children']:
            if item['name'] != _tag(RDF, 'li') or item['attributes']:
                raise _Refused('unsupported_property')
            values.append(_literal(item))
        return values
    raise _Refused('unsupported_property')


_DATE = re.compile(
    r'(?P<year>[0-9]{4})(?:-(?P<month>[0-9]{2})(?:-(?P<day>[0-9]{2})'
    r'(?:T(?P<hour>[0-9]{2}):(?P<minute>[0-9]{2})'
    r'(?::(?P<second>[0-9]{2})(?:\.[0-9]+)?)?'
    r'(?:Z|[+-](?P<zone_hour>[0-9]{2}):(?P<zone_minute>[0-9]{2}))?)?)?)?')
_REAL = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)')
_ORIENTATION = re.compile(r'\+?0*[1-8]')


def _valid_date(value):
    """Adobe XMP Date syntax/calendar checks, without completing or shifting dates."""
    match = _DATE.fullmatch(value)
    if match is None:
        return False
    parts = {key: int(item) for key, item in match.groupdict().items() if item is not None}
    if 'month' in parts and not 1 <= parts['month'] <= 12:
        return False
    if 'day' in parts and not 1 <= parts['day'] <= calendar.monthrange(parts['year'], parts['month'])[1]:
        return False
    return all(parts.get(key, 0) <= maximum for key, maximum in (
        ('hour', 23), ('minute', 59), ('second', 59), ('zone_hour', 23), ('zone_minute', 59)))


def _validate_fields(fields):
    """Validate only interpreted values, not unknown extension schemas or truthfulness.

    Explicit empty strings remain clearing values under the import contract. Values
    are not stripped/coerced; originals and snapshots keep the user's exact content.
    A problem holds the whole source rather than silently falling back to embedded.
    """
    for field, value in fields.items():
        if value == '':
            continue
        if field == 'date_taken' and not _valid_date(value):
            raise _Refused('invalid_date_taken')
        if field == 'orientation' and _ORIENTATION.fullmatch(value) is None:
            raise _Refused('invalid_orientation')
        if field == 'rating':
            # Decimal avoids rounding a value just outside a boundary into range.
            if _REAL.fullmatch(value) is None:
                raise _Refused('invalid_rating')
            number = Decimal(value)
            if not (number == -1 or 0 <= number <= 5):
                raise _Refused('invalid_rating')


def parse_bytes(data: bytes, *, source_id: str) -> ReadResult:
    """Capture RDF/XML without XML rewriting, truthiness fallback or alias guessing.

    Unknown properties are retained structurally, but mapped properties with unknown
    forms or duplicates hold the sidecar. Malformed XML is never proof of non-XMP.
    """
    if not isinstance(data, bytes) or not isinstance(source_id, str) or not source_id.strip():
        raise ValueError('Expected bytes and a nonempty source ID.')
    if len(data) > MAX_BYTES:
        return ReadResult('needs_attention', 'size_limit')
    if not data:
        return ReadResult('not_xmp', 'empty_file', data)
    if data.startswith((b'\xff\xd8\xff', b'\x89PNG\r\n\x1a\n', b'PK\x03\x04',
                        b'GIF87a', b'GIF89a', b'%PDF-')):
        return ReadResult('not_xmp', 'unrelated_binary', data)
    try:
        root = _tree(data)
    except _Refused as exc:
        return ReadResult('needs_attention', str(exc), data)
    except (expat.ExpatError, ValueError, LookupError) as exc:
        return ReadResult('needs_attention', 'malformed_xml', data, detail=str(exc))

    tags = {'xml': root, 'properties': {}}
    if root['name'] == _tag(XMP_META, 'xmpmeta'):
        if root['text'].strip() or len(root['children']) != 1:
            return ReadResult('needs_attention', 'unsupported_packet', data, tags=tags)
        rdf = root['children'][0]
    elif root['name'] == _tag(RDF, 'RDF'):
        rdf = root
    else:
        pending = [root]
        while pending:
            node = pending.pop()
            if node['name'] in (_tag(RDF, 'RDF'), _tag(XMP_META, 'xmpmeta')):
                return ReadResult('needs_attention', 'unsupported_packet', data, tags=tags)
            pending.extend(node['children'])
        return ReadResult('not_xmp', 'unrelated_xml', data, tags=tags)
    if rdf['name'] != _tag(RDF, 'RDF') or rdf['attributes'] or rdf['text'].strip():
        return ReadResult('needs_attention', 'unsupported_packet', data, tags=tags)
    fields, owners = {}, []
    try:
        for description in rdf['children']:
            if (description['name'] != _tag(RDF, 'Description')
                    or description['text'].strip()
                    or description['attributes'].get(_tag(RDF, 'about'), '') != ''):
                raise _Refused('unsupported_subject')
            properties = list(description['children'])
            for name, value in description['attributes'].items():
                if name == _tag(RDF, 'about'):
                    continue
                if name.startswith('{' + RDF + '}') or not name.startswith('{'):
                    raise _Refused('unsupported_subject')
                properties.append({'name': name, 'attributes': {}, 'text': value, 'children': []})
            for node in properties:
                name = node['name']
                if not name.startswith('{') or name.startswith('{' + RDF + '}'):
                    raise _Refused('unsupported_property')
                tags['properties'].setdefault(name, []).append(node)
                if name in FIELD_TAGS:
                    field = FIELD_TAGS[name]
                    if field in fields:
                        raise _Refused('repeated_field')
                    fields[field] = _field_value(field, node)
                if name == _tag(CRS, 'RawFileName'):
                    owners.append(_literal(node))
        _validate_fields(fields)
        if len(owners) > 1:
            raise _Refused('repeated_owner')
        owner = owners[0] if owners else None
        if owner is not None:
            try:
                if len(relative_path(owner).parts) != 1:
                    raise ValueError('Owner is not a basename.')
            except ValueError as exc:
                raise _Refused('invalid_owner') from exc
    except (_Refused, ValueError) as exc:
        return ReadResult('needs_attention', str(exc), data, tags=tags)
    source = MetadataSource(source_id, 'xmp', tags, fields, data)
    return ReadResult('valid', 'parsed', data, source, tags, owner)


def _signature(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read_sidecar(root: Path, relative_name: str, *, source_id: str) -> ReadResult:
    """Read a stable regular file below a trusted root, without following symlinks.

    Walk directory descriptors from / through the root and relative path. No resolved
    string is reopened after a safety check; FIFO/device opens cannot block this read.
    This read is a snapshot, not an authorization for later source deletion.
    """
    relative = relative_path(relative_name)
    if relative.suffix.lower() != '.xmp':
        raise ValueError('Expected an XMP sidecar name.')
    absolute = Path(os.path.abspath(root))
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        with contextlib.ExitStack() as stack:
            def opened(name, open_flags, parent=None):
                fd = os.open(name, open_flags, dir_fd=parent)
                stack.callback(os.close, fd)
                return fd
            folder = opened('/', flags | os.O_DIRECTORY)
            chain = []
            for part in (*absolute.parts[1:], *relative.parts[:-1]):
                child = opened(part, flags | os.O_DIRECTORY, folder)
                chain.append((folder, part, child))
                folder = child
            fd = opened(relative.name, flags | os.O_NONBLOCK, folder)
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode):
                return ReadResult('needs_attention', 'not_regular')
            if before.st_size > MAX_BYTES:
                return ReadResult('needs_attention', 'size_limit')
            chunks, size = [], 0
            while True:
                chunk = os.read(fd, min(65536, MAX_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_BYTES:
                    return ReadResult('needs_attention', 'size_limit')
            after = os.fstat(fd)
            named = os.stat(relative.name, dir_fd=folder, follow_symlinks=False)
            if (_signature(before) != _signature(after) or _signature(after) != _signature(named)
                    or size != after.st_size):
                return ReadResult('needs_attention', 'changed_during_read')
            for parent, name, child in chain:
                linked = os.stat(name, dir_fd=parent, follow_symlinks=False)
                captured = os.fstat(child)
                if (linked.st_dev, linked.st_ino) != (captured.st_dev, captured.st_ino):
                    return ReadResult('needs_attention', 'changed_during_read')
            data = b''.join(chunks)
    except OSError as exc:
        return ReadResult('needs_attention', 'read_error', detail=f'{exc.errno}: {exc.strerror}')
    return parse_bytes(data, source_id=source_id)
