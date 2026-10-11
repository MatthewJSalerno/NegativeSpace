"""Pure same-directory XMP ownership planning; no catalog or file changes.

Call with every supported photo in the source inventory BEFORE job filters. Results
are tentative for new/unresolved associations; recorded ownership/primary choices
take precedence in the catalog capture layer. These pure helpers never save decisions.
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import Mapping, Sequence

from engine import ns_db, xmp

POLICIES = frozenset({'ask', 'raw_only', 'non_raw_only', 'all'})


@dataclass(frozen=True)
class Association:
    sidecar: str
    state: str  # associated, needs_choice, needs_attention, orphan, ignored
    photos: tuple[str, ...]  # Owners when associated; affected candidates otherwise.
    reason: str
    basis: str | None = None  # full_name, declared_owner, single, policy, confirmed
    candidates: tuple[str, ...] = ()  # Complete pre-policy candidates when captured by Index.


class PhotoInventory:
    """Index a complete inventory once; each sidecar visits only its matching names.

    Match filename stems exactly (including case/Unicode) rather than merging distinct
    POSIX files. Photo and XMP extension recognition is case-insensitive. Filesystem
    probing and the validity of each photo are the inventory producer's responsibility.
    """
    def __init__(self, photo_paths: Sequence[str]):
        self.by_name = {}
        self.by_stem = defaultdict(list)
        for value in photo_paths:
            path = xmp.relative_path(value)
            if path.suffix.lower() not in ns_db.SUPPORTED_EXTENSIONS:
                raise ValueError('Inventory must contain only supported photo paths.')
            key = (str(path.parent), path.name)
            if key in self.by_name:
                raise ValueError('Inventory contains duplicate paths.')
            self.by_name[key] = value
            self.by_stem[(str(path.parent), path.stem)].append(value)
        for values in self.by_stem.values():
            values.sort()

    def associate(self, sidecar: str, result: xmp.ReadResult, *, policy: str) -> Association:
        if policy not in POLICIES:
            raise ValueError('Unknown XMP association policy.')
        path = xmp.relative_path(sidecar)
        if path.suffix.lower() != '.xmp':
            raise ValueError('Expected an XMP sidecar path.')
        folder, base = str(path.parent), path.stem
        full = self.by_name.get((folder, base))
        candidates = (full,) if full else tuple(self.by_stem.get((folder, base), ()))
        if result.state == 'not_xmp':
            return Association(sidecar, 'ignored', (), result.code)
        if not candidates:
            return Association(sidecar, 'orphan', (), 'no_matching_photo')
        if result.state != 'valid' or result.source is None:
            return Association(sidecar, 'needs_attention', candidates, result.code)
        if result.owner_name is not None:
            owned = self.by_name.get((folder, result.owner_name))
            if owned not in candidates:
                return Association(sidecar, 'needs_choice', candidates, 'owner_conflict')
            # Full-filename binding still outranks the policy and declared ownership.
            return Association(sidecar, 'associated', (owned,), 'resolved',
                               'full_name' if full else 'declared_owner')
        if full:
            return Association(sidecar, 'associated', candidates, 'resolved', 'full_name')
        if len(candidates) == 1:
            return Association(sidecar, 'associated', candidates, 'resolved', 'single')
        if policy == 'all':
            return Association(sidecar, 'associated', candidates, 'resolved', 'policy')
        if policy in ('raw_only', 'non_raw_only'):
            chosen = tuple(p for p in candidates if
                           (xmp.relative_path(p).suffix.lower() in ns_db.RAW_EXTENSIONS)
                           == (policy == 'raw_only'))
            if len(chosen) == 1:
                return Association(sidecar, 'associated', chosen, 'resolved', 'policy')
        return Association(sidecar, 'needs_choice', candidates, 'ambiguous_ownership')


def primary_candidates(associations: Sequence[Association]) -> Mapping[str, tuple[str, ...]]:
    """Suggest primary only for a NEW photo with fully resolved valid associations.

    A sole full-name version wins and other associated versions remain alternatives.
    Otherwise return all candidates: catalog/content comparison and an explicit decision
    are required; never choose by incoming order. A blocked candidate prevents a suggestion.
    Existing primary choices are outside this helper and must never be overwritten by it.
    """
    by_photo = defaultdict(list)
    blocked = set()
    for association in associations:
        if association.state in ('needs_choice', 'needs_attention'):
            blocked.update(association.photos)
        elif association.state == 'associated':
            for photo in association.photos:
                by_photo[photo].append(association)
    result = {}
    for photo, versions in by_photo.items():
        if photo in blocked:
            continue
        full = sorted({v.sidecar for v in versions if v.basis == 'full_name'})
        result[photo] = tuple(full or sorted({v.sidecar for v in versions}))
    return result
