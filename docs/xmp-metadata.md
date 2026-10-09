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
  RAW writes default to XMP; other formats default to embedded writes when no primary
  write target has been established. An established primary takes precedence over
  those defaults: a photo imported with primary XMP is edited only in that XMP, even
  when Settings defaults its format to embedded writes. Editing a field displayed via
  embedded fallback writes the new value to the primary XMP, leaving EXIF unchanged.
  Copying values between XMP and embedded metadata is a separate future action.
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
  Changing primary requires a deliberate action, a preview of changed effective values,
  any resulting refiling and future edit target, and confirmation. It copies no values
  between sources. Existing format support and RAW-write consent still apply.

The resolver accepts validated reader output: source IDs, qualified extracted `tags`,
canonical `fields`, and original bytes for every XMP version. It returns JSON-compatible
snapshots, the active/primary source ID, effective fields, each field's source ID,
source kind (`embedded`, `xmp`, `mixed`, or null for no effective fields), and fields
whose presence or values differ across snapshots. Original bytes are represented as
base64 with a SHA-1 fingerprint. This is an in-memory contract, not a storage schema or
public API. Persist original content as binary BLOBs as specified below, not base64
text. The future reader must enforce parsing limits and filesystem safety.

## Association and import decisions

A full filename sidecar (`photo.CR2.xmp`) takes precedence for that photo over a short
name (`photo.xmp`). Explicit ownership information may disambiguate a short name.
Otherwise evaluate all matching photos before applying job selections or format filters.
Excluding RAW from a job does not make the JPEG the owner of a shared sidecar.

Setup requires an explicit association preference, also available in Settings.
For ambiguous short names, offer **Ask me** (default), **RAW only**, **non-RAW only**,
or **all matching photos**. A format restriction that still leaves multiple candidates
requires a decision. Ask me supports a single case or a selected batch, with an optional
**Remember this choice in Settings**. Store the resolved association. Changing the
setting applies to new or unresolved associations, never silently rewrites old ones.

Unresolved associations stay in **Not organized → Metadata choice needed**. Index
reports them separately from failures; Copy/Move skips affected pairs with a reason
while other photos proceed. Choosing a primary never silently imports a second photo
with identical bytes. Apply the following version rules after ownership is resolved:

| Situation | Agreed behavior (planned) |
| --- | --- |
| Both full-name and short-name XMP belong to a newly organized photo | Use the explicit full-name sidecar as primary without a prompt; preserve the other as an inactive alternative and report its retention. A short name beside RAW/JPEG still needs association resolution. |
| Incoming XMP is byte-identical to any retained version | Reuse its stored content without another prompt; record the new arrival, original filename/source and photo association in lineage. Do not reactivate an inactive version. |
| Existing Library photo has no XMP; incoming identical photo has XMP | Hold the incoming pair at source for a metadata choice. Keep current primary and retain the incoming XMP as an alternative, or explicitly use incoming XMP after preview/confirmation. Decide later leaves the pair untouched. |
| Library photo already has metadata edits; incoming XMP differs | Keep the current primary, safely retain the alternative, and add Needs review → Metadata differences. Import need not stay blocked once preservation is complete. |
| Matching photo is in Rejects | Present metadata choice and location choice together: keep current primary / use incoming XMP, independently of leave in Rejects / Return to Library. Preview and confirm the combination. Decide later leaves the incoming pair at source; no automatic Return. |
| Other differing versions for the same photo | Preserve all versions and origins, retain the existing primary, and hold the incoming pair for an explicit decision. |

Every existing photo keeps its primary unless deliberately changed. A changed capture
date may require refiling as part of the confirmed operation. Merely viewing a version
never chooses it. The association setting determines ownership, not permission to replace
an established primary. Do not infer that incoming metadata is newer or better.

An orphan XMP with no matching photo stays untouched at source. Report that no matching
photo was found, without listing the sidecar as a photo in Library. Reconsider it on a
later Index; clear that notice when association resolves, or replace it with an unresolved
association notice if more than one photo could own it.

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

## Exact originals, compression and catalog backups (decided; not built)

Store retained original XMP bytes as BLOBs in the catalog, alongside separately queryable
parsed metadata and lineage. There is no separate destination archive in this design.
Only the active sidecar is published beside the photo. Preserve the previous active
version before publishing another; inactive versions never contribute effective fields.

Use lossless Zstandard compression when the compressed payload is smaller; otherwise
store the original bytes. Record the encoding (raw or Zstandard), original size and
original-content hash. Verify decompressed size and hash before restoration/publication,
with bounded decompression and an explicit error on corruption or unsupported encoding.
Store identical content once while preserving each arrival's filename, source, job and
association independently. Ordinary metadata/gallery queries use parsed fields and must
not read/decompress the original BLOB per photo.

Measure compression level, space and read/write cost on representative generated XMP
before choosing a level. Include small/large sidecars, repeated and distinct versions,
unknown fields and formatting variations; prove exact byte round trips. Do not promise
an unmeasured ratio or expose a compression setting to users. Catalog backups are already
compressed, so the main expected benefit is a smaller working catalog, not guaranteed
smaller backup files. Blob storage, measurement and restoration are all still pending.

Once implemented and validated, the preservation claim is: **Every retained XMP version
can be reproduced byte for byte from the catalog or a backup containing that version.**
A backup predating an arrival cannot recover that arrival. Restoring the database does
not automatically rewind destination files, restore deleted photos or recreate source
folders. Making an older XMP primary is a new verified operation with preview, confirmation
and lineage; it does not erase intervening history. Catalog backup validation must cover
restoring and verifying retained BLOBs, not just database integrity.

## Interrupted transfers (planned)

Completion is per photo: verify the destination photo, its required sidecar and retained
alternatives, durably save the files and catalog records, then allow Move source cleanup.
Copy never removes source files. A later job failure does not invalidate already verified
completed photos. Retrying must recognize completed work without duplicating versions.
Uncertain outcomes use File needs checking; never label an uncertain operation successful.
Test interruption and restart at each publication, catalog and source-removal boundary
before claiming the combined photo/XMP durability guarantees are enforced.

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
safely persist the choice, lineage and any required refiling. The preview also states
where future edits will go; switching primary is not copying metadata between sources.

Import messages distinguish preservation from activation: **Keep current primary** saves
the incoming XMP as an inactive alternative without changing current metadata/folder;
**Use incoming XMP as primary…** previews changes; **Decide later** leaves the source pair
untouched. For already edited Library photos, explain the nonblocking review reason:
“Another copy arrived with different XMP metadata. Your current metadata is unchanged.”
For Rejects, explain that new metadata may change the user's decision and present the
independent metadata/location choices together with one preview and Apply choices.

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
- Implement the decided compressed-BLOB catalog storage and benchmark compression
  before selecting a level. Validate backup restoration and every interrupted transfer
  stage before claiming preservation. Retention/purging must not silently discard versions
  still referenced by lineage.
- Build the source tabs and import decision UI in the separate UI workstream.
- Detecting a sidecar changed between Index and Copy/Move is deferred for future
  discussion. The current expectation is to reindex after an external edit. This does
  not relax existing verification or source-deletion safety requirements.
