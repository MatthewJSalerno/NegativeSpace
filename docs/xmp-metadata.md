# XMP import and metadata provenance

## Implementation status

`engine/metadata.py` provides a tested, pure source-resolution primitive. It retains
separate embedded and XMP snapshots, resolves an explicitly chosen source, and returns
field origins and differences. It does not read files or change the catalog.

`engine/xmp.py` now captures bounded RDF/XML sidecars without writing files, and
`engine/xmp_association.py` plans ownership from a complete source photo inventory.
Both are independently tested, including generated ExifTool output.

`engine/xmp_store.py` now retains exact originals, parsed snapshots and immutable
arrival/participant records in schema 23, with verified catalog backup coverage.

**Index does not yet read XMP.** Import/association integration, primary-choice state,
API exposure, sidecar transfers, version decisions, metadata editing and source tabs
remain unimplemented. Older catalogs are refused, not migrated; do not deploy this
schema change over a running development catalog without an explicit reset plan.
Enable XMP-derived organization only alongside safe sidecar transfer;
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
- A present partial capture date (year only or year/month) is preserved without
  inventing a month, day, time or time zone. It does not fall back to embedded EXIF.
  Without a complete usable capture date, organize under Undated using the existing
  undated layout; retain the partial value for display and review. Do not turn a
  file-modification fallback into a claimed complete capture date. Integration is pending.
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
text. The reader's limits and filesystem contract follow below.

## Reader and ownership helper boundary (built; not integrated)

`xmp.read_sidecar(root, relative_name, source_id=...)` opens a stable regular file
through directory descriptors, refuses traversal/symlinks/nonregular files, checks
identity/size/timestamps before and after reading and verifies the directory chain.
An unstable or partial read is never returned as an original for archival. This is
read-time safety, not a substitute for verification before later deletion.

The parser refuses DTDs and entity declarations without fetching external resources.
Its initial safety ceilings are 8 MiB of input, 64 nested elements, 50,000 elements and
100,000 attributes. Exceeding a ceiling holds the item for attention; it is neither
truncated nor treated as junk. These are safety bounds, not measured tuning values.
Original bytes retain comments, formatting and encoding. Qualified XML property trees
retain unknown structures and repeated properties for inspection, without guessing
aliases from short tag names. Parsed trees are not a byte reconstruction format.

Supported canonical fields are EXIF DateTimeOriginal; TIFF Make, Model, Orientation;
XMP Rating; and Dublin Core title, description, subject, creator and rights. Common
attribute/element literals, RDF Bag/Seq and language Alt values are supported. Empty
literals/containers remain present. Unknown forms of mapped fields, repeated mapped
fields or unsupported subjects yield attention with the original capture retained;
there is no silent partial effective-metadata result. Unknown unmapped structures are
retained without applying them. The reader is not a complete RDF/schema validator.
The reader validates mapped date, orientation and rating values before producing a
usable source. A bad value holds the entire source with `invalid_date_taken`,
`invalid_orientation` or `invalid_rating`, retaining its original and XML snapshot.
Storage reparses the capture, so a held value cannot bypass validation through retention.
Reader revision 2 records this validation contract; no catalog schema change is needed.

Dates follow XMP's partial-date and date-time syntax, with calendar/leap-day, clock and
numeric-offset checks. Precision, fractions and time zones remain as written; missing
components or an unknown time zone are never invented. Four-digit years including 0000
are preserved at this reader boundary; this does not assert that they can be used for
filing. Suspicious but possible dates stay available for the separate review policy.
TIFF orientation accepts integers 1–8. Ratings accept decimal -1 or values from 0 through
5, including fractional ratings; decimal comparisons avoid rounding an invalid value
into range. Imported -1 is metadata, not permission to move a photo to Rejects.
Explicit empty values still clear fields under the agreed import contract, even where
a strict external schema might expect a number/date. Whitespace-only typed values are
held, not silently trimmed into blanks. Unknown extension fields remain uninterpreted.

These are validated lexical snapshots, not normalized cross-format values. The future
embedded-metadata adapter, canonical normalization and the agreed partial-date filing
behavior must be built before these values can determine organization or semantic comparisons.

Independent compatibility tests exercise generated packets through the bundled ExifTool
reader and ExifTool-written packets through our reader, covering UTF-8/UTF-16, Unicode,
arrays, localized text, orientation, ratings and dates. They assert field agreement and
unchanged original bytes. ExifTool is required for these tests (already in the app image),
not invoked as a new runtime validator. Neither these tests nor ExifTool's `-validate`
option establish complete XMP conformance or that metadata belongs to a particular photo.
Adobe's toolkit is not an additional installation dependency.

The rules follow Adobe's [data types](https://developer.adobe.com/xmp/docs/xmp-namespaces/xmp-data-types/),
[TIFF properties](https://developer.adobe.com/xmp/docs/xmp-namespaces/tiff/) and
[XMP properties](https://github.com/adobe/xmp-docs/blob/master/XMPNamespaces/xmp.md).
ExifTool documents the limits of its validation in its [FAQ](https://exiftool.org/faq.html).

Results distinguish `valid`, `not_xmp` and `needs_attention`, with stable reason codes.
Only confidently unrelated recognized binaries/empty files or well-formed unrelated
XML are non-XMP; malformed/unknown inputs stay held. An unfamiliar wrapper containing
XMP/RDF stays held too. Extension alone and a parse error never establish junk.

`xmp_association.PhotoInventory` indexes all supported source photo paths once, then
looks up each sidecar in its directory. Callers must pass the full inventory before
job filters; the helper cannot detect an already filtered input. Stems preserve exact
case and Unicode; recognized extensions are case-insensitive. Filename-case variants
are not silently merged. Declared RawFileName ownership must be a basename and match
an existing candidate; conflicts are held. It never follows a path from metadata.

`primary_candidates` suggests primary candidates only for newly organized photos
whose associations are resolved: a full-name version takes priority, but multiple
full-name candidates remain unresolved. All associations remain available as alternatives.
No helper modifies recorded ownership/primary, catalog rows or file content. Duplicate
version reuse, catalog choices and orphan-notice clearing require the pending integration.

The parser design follows [Adobe's XMP serialization model](https://developer.adobe.com/xmp/docs/xmp-specifications/)
and uses [Expat handlers](https://docs.python.org/3.11/library/pyexpat.html) to enforce
resource and declaration restrictions. `tests/xmp_test.py` exercises these boundaries
using generated XML/files, including output written by the bundled ExifTool.

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

Each job captures its processing settings once at start, including XMP association and
metadata-write preferences, and retains that snapshot in its job details. Saving new
settings never changes a running job, including its later batches/workers. New jobs use
the newly saved values; previously resolved associations and established primary sources
remain unchanged. Apply the existing job-configuration boundary to XMP integration and
test a settings save between two batches. UI-only appearance and review-reminder changes
retain their immediate behavior; they do not change engine processing.

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

## Exact originals, compression and catalog backups (storage built; import pending)

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

The generated [storage experiment](xmp-storage-measurements.md) selected Zstandard
level 1. It compared raw/levels 1, 3, 6 and 10 and verified exact round trips; no compression
control is exposed to users. Catalog backups are already compressed, so a smaller
working catalog is the main benefit. Capacity and backup costs at 200k/500k unique XMP
versions are not yet measured.

Schema 23 adds `xmp_versions`, `xmp_arrivals` and `xmp_arrival_files`. Versions carry
binary payload, encoding, original size/SHA-256, reader revision, classification/code,
parsed fields and qualified tags. Arrivals keep run and relative source path (including
original filename), while participant rows independently retain each file identity and
its candidate/owner evidence. These records are immutable; they do not yet represent
current primary choice or future activation history.

Retention reparses bytes rather than trusting a caller's claimed classification. Empty,
known-unrelated and over-limit captures are refused. A bounded damaged/unsupported
capture may be preserved as `needs_attention`, with no effective fields and only
candidate participants; it cannot be a resolved metadata source. Oversized originals
never become BLOBs. A 5 GiB sparse-file test verifies refusal before even one file-content
read. Exceeding the size limit says the file needs attention, not that it cannot be XMP.

The caller must supply a FULL-synchronous transaction. A savepoint prevents orphan
content on a refused arrival; same-run/path replay must match content and participants.
This does not replace the future source-deletion and publication gates. Reading a saved
original verifies bounded frame parameters, checksum, decoded length and SHA-256; extra
frames/trailing bytes, unknown codecs and corruption are refused. A query checks stored
length before returning payload to Python, and gallery metadata queries need no BLOB.

Backup publication verifies each version one at a time, then verifies the compressed
SQLite snapshot. The snapshot and live backup record hold the maximum included arrival
ID, so later arrivals remain unbacked regardless of clock order. XMP-only jobs qualify
for the existing post-job backup. Tests restore the catalog backup and verify original
bytes and lineage; a corrupt version prevents backup publication. This does not add
an in-app sidecar restoration/activation operation.

The tested storage-level preservation claim is: **Every retained XMP version
can be reproduced byte for byte from the catalog or a backup containing that version.**
A backup predating an arrival cannot recover that arrival. Restoring the database does
not automatically rewind destination files, restore deleted photos or recreate source
folders. Making an older XMP primary is a new verified operation with preview, confirmation
and lineage; it does not erase intervening history. Catalog backup validation must cover
restoring and verifying retained BLOBs, not just database integrity.

## Earlier metadata states and duplicate consolidation (agreed; not built)

Reproduction of an earlier meaningful state is distinct from exact-file restoration.
Given surviving unchanged image content and complete structured records, the goal is to
reproduce supported recorded metadata from either the source observation or a selected
pre-edit state. Preserve original observations, before/after field values, absence,
explicit emptiness, removals, source/primary bindings and version origins. Human-readable
log messages alone are insufficient. Reproduction is a new verified operation with
preview, confirmation and lineage; it does not erase history or add an automatic undo.

The resulting photo may have a different internal layout and whole-file hash. Do not
promise exact original photo bytes without retaining a full original file. Unknown,
unrecorded or unwritable proprietary metadata cannot be promised reproducible. Catalog
backups and lineage cannot recover lost image content. The existing byte-exact guarantee
for retained XMP originals is separate and remains unchanged.

Distinguish two proposed duplicate categories:

- Complete photo-file equality permits one verified surviving copy, preserving both
  origins and histories; separately associated XMP versions may still differ.
- Identical image content with different metadata requires preservation of each metadata
  version and its origin before consolidation, with an explicit primary-source choice.
  Retaining metadata must not replace one version with an automatic merged snapshot.

Use one metadata-comparison workflow rather than a separate conflict process for each
property. The user chooses a base metadata version and may explicitly override selected
supported fields from another retained version: for example, use X but take the capture
date from Y. Using the base unchanged remains the simple path; field selection is optional.
Preview the complete proposed values, per-field donor/version, changes and any refiling
before confirmation. An explicitly selected empty value clears the field; do not silently
fall back. Distinguish absence from emptiness and leave no implicit donor selection.

Saving a composed result creates a new recorded metadata version, retaining the base and
all donor versions unchanged. Record its base version, explicit overrides and their
origins alongside before/after values. Write supported changes to the established primary
metadata source; choosing a base or field donor never silently changes that write target.
Changing the primary source itself remains a separate deliberate choice. Preservation and
write/read-back verification must complete before consolidation removes a redundant file.
If required information cannot be preserved or safely reapplied, explain the limitation
and keep both photos. Select complete logical fields, not arbitrary fragments of their
underlying tags: Location carries its coordinates and related tags together; Date taken
carries its recorded time-zone information. Missing components stay missing instead of
being borrowed silently from another version. Exact per-format mappings still need tests.

For the proposed JPEG content comparison, unchanged encoded image data and the required
decoding information determine the base-image candidate. Orientation instructions and
color information are metadata differences shown in this same comparison workflow, not
separate per-property user workflows. Physical image rewriting is not normalized into
an exact-content match. Preserve presentation metadata sufficiently to reproduce supported
states; a profile name alone is not its original profile data. Precise format coverage,
profile preservation/reapplication and conservative handling of unfamiliar structures
remain implementation requirements, not claims that current extracted EXIF is sufficient.

An edit that would create an exact duplicate should preview the surviving photo and
explain the preservation/removal consequences before confirmation. Prepare and verify
staged output to establish equality; record links from both histories and preserve
required metadata before any redundant-file removal. This is a new coordinated workflow,
not permission to feed image-content matches into today's whole-file duplicate cleanup.

A generated-only [JPEG experiment](jpeg-content-hash-experiment.md) now tests a versioned
SHA-256 fingerprint over encoded image data and decoding context, with separate recognized
metadata hashing. Twenty tests pass, including independent ExifTool edits and decoded-pixel
checks; measured warm-read cost is documented. It is isolated under tools, not used by
Index or cleanup. Unsupported layouts are refused, and decoding/metadata preservation
are not certified by the fingerprint. RAW and broader JPEG coverage, integrated cost and
pre-removal equality verification remain open. A pHash match never establishes exact
image-content equality. Neither hash stores image data or reconstructs a file. These
consolidation/reproduction capabilities remain unbuilt.

Existing edit-backup policy remains: a pre-action catalog backup and structured metadata
history for all edits; verified temporary outputs and recovery material until completion;
exact retained XMP versions; optional first-edit original-file copies for explicitly
enabled embedded RAW editing. There is no new requirement to permanently retain every
pre-edit JPEG or other ordinary photo file.

## Interrupted transfers (planned)

Completion is per photo: verify the destination photo, its required sidecar and retained
alternatives, durably save the files and catalog records, then allow Move source cleanup.
Copy never removes source files. A later job failure does not invalidate already verified
completed photos. Retrying must recognize completed work without duplicating versions.
Uncertain outcomes use File needs checking; never label an uncertain operation successful.
Test interruption and restart at each publication, catalog and source-removal boundary
before claiming the combined photo/XMP durability guarantees are enforced.

During Copy/Move, verify destination names, written photo/sidecar content and durable
records before source cleanup; a name collision cannot authorize overwriting or adopting
unrelated destination content. These are checks on the operation's actual targets, not
a catalog-wide destination scan. A broader **Check my destination** inventory/diff/repair
workflow for external changes is deferred to a separate discussion.

If metadata saving succeeds but subsequent refiling fails, retain the verified edit and
record the actual location plus Needs refiling. Explain the specific permission, space or
storage error; the user fixes the cause and retries only the move, carrying active XMP.
An uncertain outcome requires verification before retry. Individual edit failures may
leave unrelated photos eligible to continue, but shared storage failures that make further
writes unsafe stop new edits. Completed edits remain; report succeeded, failed and
not-started photos separately. These edit/transfer integration rules remain unbuilt.

## UI handoff — not implemented

When Settings opens during a running job, show the shared informational notice near
the top, across tabs: **“A job is running. Processing changes you save now will apply
to future jobs, not this one.”** Keep its layout stable if the job starts/finishes while
Settings is open. Retain the near-Save explanation and active-job save confirmation;
see `webui-spec.md` §3 and `ui-design.md`. This prominent active-job notice is pending;
the generic future-jobs notice and save confirmation already exist.

Future reproduction/consolidation messaging must distinguish supported earlier metadata
states from exact original files: while unchanged image content remains available,
recorded metadata can be reproduced through supported writes, but the file hash may
change. Catalog backups are not photo backups. Present this as a future capability until
it is implemented and verified; do not promise recovery of missing pixels or unsupported
metadata. Consolidation previews identify the surviving photo and preservation of both
origins/history and metadata alternatives.

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

- Integrate the tested bounded reader/association helpers. Add the embedded-field
  adapter and cross-format type/date normalization; expand unsupported RDF forms with fixtures
  as needed. Do not treat arbitrary bytes accepted by the pure resolver as validated XMP.
- Integrate the stored snapshots/arrivals into Index and build current association/primary
  choice records, effective metadata and the API. Retention does not activate a version.
- Implement verified photo/sidecar transfer, collision handling, partial shared Move,
  decisions, and recovery before enabling XMP-derived Copy/Move organization.
- Measure parsed-metadata growth and backup time at large XMP counts. Byte-storage and
  backup restoration tests pass; interrupted photo/sidecar transfer still needs implementation
  and failure tests. Retention/purging must not discard lineage-referenced versions.
- Build the source tabs and import decision UI in the separate UI workstream.
- Detecting a sidecar changed between Index and Copy/Move is deferred for future
  discussion. The current expectation is to reindex after an external edit. This does
  not relax existing verification or source-deletion safety requirements.
