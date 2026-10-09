"""Source-aware metadata resolution for the planned XMP import and metadata tabs.

This is a pure engine primitive, not yet wired into Index or transfer. A reader must
provide validated, canonical field IDs for values that represent the same concept
across formats; this module never equates tags just because their short names match.
Raw extracted tags remain separate, including tags the application does not interpret.
"""

import base64
import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class MetadataSource:
    """One captured version. IDs identify versions, not paths or chronological order.

    ``tags`` holds the reader's full extracted metadata, preserving qualified names.
    ``fields`` contains its explicit canonical field mapping for precedence/comparison.
    XMP bytes must be captured by a validated reader; accepting bytes here does not
    establish that a file is XMP. The caller owns parsing, limits and path safety.
    """
    source_id: str
    kind: str
    tags: Mapping[str, Any]
    fields: Mapping[str, Any]
    original_bytes: bytes | None = None


def _json_copy(value):
    """A detached JSON value; reject values a catalog/API cannot round-trip."""
    # JSON permits bool/int/float, but not NaN or infinity. Require string keys
    # rather than letting JSON silently coerce keys and collide with real tags.
    def validate(item):
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ValueError('Metadata keys must be strings.')
            for child in item.values():
                validate(child)
        elif isinstance(item, list):
            for child in item:
                validate(child)
        elif item is not None and type(item) not in (str, int, float, bool):
            raise ValueError('Metadata values must be JSON values.')
    validate(value)
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ValueError('Metadata values must be finite JSON values.') from exc


def resolve_sources(embedded: MetadataSource, xmp_versions: Sequence[MetadataSource], *,
                    active_xmp_id: str | None) -> dict:
    """Keep all sources and resolve only the explicitly active XMP against embedded.

    An explicitly empty XMP field wins; only an absent field falls back to embedded.
    Alternative XMP versions are never merged and active ownership is not inferred.
    Passing None explicitly chooses embedded metadata only.

    Output is JSON-serializable and detached from inputs. Original XMP bytes are
    base64 encoded for later byte-for-byte preservation; raw tags are never rebuilt
    into XML. ``different_fields`` compares sources by value *and presence*, and
    ``field_sources`` states what supplies each effective field. Tab selection is
    a UI concern and must never call this function with a different active choice.
    """
    if embedded.kind != 'embedded' or embedded.original_bytes is not None:
        raise ValueError('The embedded source must contain captured photo metadata.')
    sources = [embedded, *xmp_versions]
    ids = [source.source_id for source in sources]
    if any(not isinstance(i, str) or not i.strip() for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('Metadata source IDs must be nonempty and unique.')
    if any(source.kind != 'xmp' or not isinstance(source.original_bytes, bytes)
           for source in xmp_versions):
        raise ValueError('Each XMP version requires its original captured bytes.')
    if active_xmp_id is not None and active_xmp_id not in ids[1:]:
        raise ValueError('The active XMP must identify a supplied sidecar version.')

    snapshots = {}
    for source in sources:
        snapshot = {'kind': source.kind,
                    'tags': _json_copy(dict(source.tags)),
                    'fields': _json_copy(dict(source.fields))}
        if source.kind == 'xmp':
            snapshot['original_base64'] = base64.b64encode(source.original_bytes).decode('ascii')
            snapshot['sha1'] = hashlib.sha1(source.original_bytes).hexdigest()
        snapshots[source.source_id] = snapshot

    effective = copy.deepcopy(snapshots[embedded.source_id]['fields'])
    field_sources = {field: embedded.source_id for field in effective}
    active = snapshots.get(active_xmp_id)
    if active is not None:
        for field, value in active['fields'].items():
            effective[field] = copy.deepcopy(value)
            field_sources[field] = active_xmp_id

    all_fields = sorted({field for snapshot in snapshots.values() for field in snapshot['fields']})
    different_fields = []
    for field in all_fields:
        # Typed JSON equality keeps e.g. False distinct from numeric zero.
        values = {json.dumps([field in snapshot['fields'], snapshot['fields'].get(field)],
                             sort_keys=True, ensure_ascii=False) for snapshot in snapshots.values()}
        if len(values) > 1:
            different_fields.append(field)
    used = set(field_sources.values())
    effective_kind = 'mixed' if len(used) > 1 else snapshots[next(iter(used))]['kind'] if used else None
    return {'version': 1, 'sources': snapshots, 'active_xmp_id': active_xmp_id,
            'primary_source_id': active_xmp_id or embedded.source_id, 'effective': effective,
            'field_sources': field_sources, 'effective_source_kind': effective_kind,
            'different_fields': different_fields}
