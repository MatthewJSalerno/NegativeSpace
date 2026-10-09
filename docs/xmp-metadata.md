# XMP import and metadata provenance

## Implementation status

`engine/metadata.py` provides a tested, pure source-resolution primitive. It retains
separate embedded and XMP snapshots, resolves an explicitly chosen source, and returns
field origins and differences. It does not read files or change the catalog.

**Index does not yet read XMP.** Parsing, association, durable snapshots, API exposure,
sidecar transfers, version decisions, metadata editing and the source tabs remain
unimplemented. Enable XMP-derived organization only alongside safe sidecar transfer;
using corrected dates while leaving their sidecars behind would lose metadata.

This document records the agreed import contract and the UI handoff. General editing
and transfer rules remain in [engine-spec.md §9.6](engine-spec.md#96-writing-metadata-into-files)
and the corresponding metadata section of `webui-spec.md`.

## Source precedence and preservation

- Read associated XMP at Index regardless of the setting for where future edits go.
  RAW writes default to XMP; other formats default to embedded writes, as specified.
- The active XMP supplies each field it contains. **An explicitly empty value stays
  empty**, even when embedded metadata has a value. Only an absent field falls back
  to embedded metadata. Zero and false are values, not missing metadata.
- Preserve both sources, including extracted tags the app does not interpret. Map
  equivalent fields explicitly; identical short tag names do not establish equivalence.
- Preserve original XMP bytes exactly. Parsed metadata cannot reproduce those bytes.
  Alternative sidecars remain distinct versions; do not merge them automatically or
  imply a chronological order merely because one was imported later.
- A cleared capture date must not revive the embedded capture date. Integration must
  apply the existing undated/location-fallback policy without presenting a file date
  as a capture date. Date parsing and validation remain reader responsibilities.
- Choosing a metadata source is a separate operation from viewing a source tab.
  Explicitly choosing embedded metadata retains the XMP alternatives for inspection.

The resolver accepts validated reader output: source IDs, qualified extracted `tags`,
canonical `fields`, and original bytes for every XMP version. It returns JSON-compatible
snapshots, the active/primary source ID, effective fields, each field's source ID,
source kind (`embedded`, `xmp`, `mixed`, or null for no effective fields), and fields
whose presence or values differ across snapshots. Original bytes are represented as
base64 with a SHA-1 fingerprint. This is an in-memory contract, not a storage schema or
public API. The future reader must enforce parsing limits and filesystem safety.

## Association and import decisions

A full filename sidecar (`photo.CR2.xmp`) takes precedence for that photo over a short
name (`photo.xmp`). Explicit ownership information may disambiguate a short name.
Otherwise evaluate all matching photos before applying job selections or format filters.
Excluding RAW from a job does not make the JPEG the owner of a shared sidecar.

For ambiguous short names, offer **Ask me** (default), **RAW only**, **non-RAW only**,
or **all matching photos**. A format restriction that still leaves multiple candidates
requires a decision. Ask me supports a single case or a selected batch, with an optional
**Remember this choice in Settings**. Store the resolved association. Changing the
setting applies to new or unresolved associations, never silently rewrites old ones.

Unresolved associations and differing XMP versions for identical photo bytes stay in
**Not organized → Metadata choice needed**. Index reports them separately from failures;
Copy/Move skips the affected pairs with a reason while other photos proceed. They are
not Library Needs review items. Preserve all original versions and origins, show their
field differences through lineage, and let the user choose the active one explicitly.

When a destination sidecar already exists, reuse an identical version. For differing
versions, retain the current destination version as active pending a decision, preserve
both, and hold the incoming pair. Choosing an incoming date that changes organization
requires any refiling to be part of the confirmed operation.

## Unreadable and shared sidecars

An extension alone does not establish XMP. A confidently non-XMP file (for example an
empty file or a recognized unrelated binary format) is flagged and left at the source;
the photo may organize using embedded metadata. Recognizable damaged XMP holds the
photo and sidecar together for repair/reindex or an explicit use-embedded decision.
Permission and storage failures also hold the pair: a parse/read failure alone is not
proof the sidecar is junk. Potentially useful originals must be preserved; an unreadable
original must not become an active, usable destination sidecar by assertion.

When one sidecar is associated with several photos, each destination photo receives
its own full-filename sidecar and records the shared origin. Later edits are independent.
During a partial Move, verify the moved photo and its destination sidecar before removing
that source photo. Leave the shared source sidecar while another associated source photo
still needs it. Remove it only when all required copies are verified and no associated
source photo needs it; uncertainty means retaining it. Copy leaves all source files alone.

## UI handoff — not implemented

Within Photo information, use the shared tabs for **Used metadata**, **Embedded/EXIF**
and **XMP**. Used metadata is the default. Keep the existing Photo information / Similar
photos navigation intact. The active preferred source has a visible textual **Primary**
marker, not just a color. Used metadata may mix XMP and embedded values; show their
origins accurately using the shared field table and restrained source labels.

Source views show captured metadata, not only conflicts. Distinguish **Empty** from
**Not present**. Allow inspection of alternate XMP versions without activating them;
mark the active version clearly. Do not call every alternative an earlier edit.
**Use this version** is a separate confirmed action, enabled only after the backend can
safely persist the choice, lineage and any required refiling.

Preserve photo/selection context and stable layout while switching tabs. Follow
`ui-design.md` for typography, spacing, tabs, keyboard behavior and differences. Validate
with embedded-only, XMP-only, mixed, conflicting, explicitly empty, unknown-tag and
multiple-version fixtures before enabling the screens.

## Remaining implementation and decisions

- Build a bounded, safe reader and explicit canonical field mapping that preserves
  missing versus empty values and all extracted tags; do not treat arbitrary bytes
  accepted by the pure resolver as validated XMP.
- Design durable snapshot/version/origin storage and association records, then integrate
  Index, effective metadata and the API. The resolver alone provides no crash durability.
- Implement verified photo/sidecar transfer, collision handling, partial shared Move,
  decisions, and recovery before enabling XMP-derived Copy/Move organization.
- Decide the archive location/retention for alternative or damaged originals; test
  source removal and every interrupted transfer stage before claiming preservation.
- Build the source tabs and import decision UI in the separate UI workstream.
- Orphan sidecars with no matching photo still need a policy decision.
- Detecting a sidecar changed between Index and Copy/Move is deferred for future
  discussion. The current expectation is to reindex after an external edit. This does
  not relax existing verification or source-deletion safety requirements.
