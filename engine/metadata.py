"""Captured metadata shapes and lossless JSON validation shared by the readers and editors."""

import json
from dataclasses import dataclass
from typing import Any, Mapping


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
