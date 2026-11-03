# XMP import and metadata provenance

## Product scope

Metadata editing primarily supports correcting dates and organizing photos. The
common-field engine foundation remains available, but this release does not aim to
replace a general-purpose EXIF editor. Qualify reliable date changes, preservation,
filing and recovery before expanding format or tag coverage. The agreed writer
limits below remain explicit; broader editing controls are deferred. The first UI
shows and compares captured fields broadly, but edits/copies only Date taken. Saved
orientation is a separate future action; common-field engine support remains intact.

## Implementation status

`engine/metadata.py` provides a tested, pure source-resolution primitive. It retains
separate embedded and XMP snapshots, resolves an explicitly chosen source, and returns
field origins and differences. It does not read files or change the catalog.

`engine/metadata_adapter.py` adds a tested comparison view for initial qualified
embedded EXIF fields and validated XMP sources; see the adapter boundary below.

`engine/xmp.py` now captures bounded RDF/XML sidecars without writing files, and
`engine/xmp_association.py` plans ownership from a complete source photo inventory.
Both are independently tested, including generated ExifTool output.

`engine/xmp_store.py` now retains exact originals, parsed snapshots and immutable
arrival/participant records (introduced in schema 23; current catalog schema 34), with
verified catalog backup coverage.

**Index now reads associated XMP as capture-only evidence.** It retains qualified
embedded EXIF/XMP, sidecar originals and proposed priority separately from live filing
metadata. `metadata_capture` and `metadata_index` implement this boundary.
`metadata_import` connects resolved first imports to normal Copy/Move and
selected-date filing; primary/ownership establishment follows verified pair completion.
Reindex preserves an established import's filing and current filename. Other canonical
fields/origins remain in the activation receipt for the source viewer. Photo-only
imports now apply embedded-XMP/EXIF priority after verified delivery. Deliberate embedded
primary switches are available through the engine CLI without rewriting tags.
First-import choices and pair retry have API/UI controls. Incoming-alternative
decisions, organized primary changes and non-JPEG embedded editing remain unfinished. The web source
viewer is read-only and compares recorded EXIF, embedded XMP and sidecar versions.
The engine now saves common-field XMP edits, copies explicit fields from retained sources,
activates associated XMP versions deliberately, and refiles verified pairs. Confirmed
incoming metadata/Return choices execute through verified jobs; their decision UI remains
unbuilt. Older catalogs are refused, not migrated; do not deploy this
schema change over a running development catalog without an explicit reset plan.
Resolved imports activate XMP-derived filing only with verified sidecar transfer;
unresolved ownership or metadata choices remain held at source.

This document records the agreed import contract and the UI handoff. General editing
and transfer rules remain in [engine-spec.md §9.6](engine-spec.md#96-writing-metadata-into-files)
and the corresponding metadata section of `webui-spec.md`.

## Source precedence and preservation

**Default read priority (filing active for photo-only and resolved first imports):** for a newly
imported photo without an established or deliberate source choice, use the selected,
valid associated **XMP sidecar → XMP embedded in the photo → embedded EXIF**, field by
field. This is a preference, not a claim that XMP is newer or more accurate. Resolve
sidecar ownership/version choices first; an unresolved or unusable source follows the
existing attention/decision rules, not silent fallback as if its fields were absent.

Only a missing field proceeds to the next source. An explicitly empty field remains
empty and stops fallback; a present partial date likewise remains partial. Preserve
all captured sources separately and record the exact origin of each effective field.
An existing primary or deliberate source choice is not replaced by this default order,
including when another archive arrives or Settings changes. Read precedence does not
silently change the established write target or authorize embedded RAW writes.

Index uses the three-source observation resolver in `metadata_capture` over qualified
EXIF, embedded XMP and sidecar views. Its results explicitly say `capture_only` / `applied: false`; they are not
an established primary or an edit target. Legacy IPTC mapping/precedence is not decided
by this rule; retain extracted evidence without guessing aliases.

- Read associated XMP at Index regardless of the setting for where future edits go.
  RAW writes use XMP only; other formats default to embedded writes when no primary
  write target has been established. An established primary takes precedence over
  those defaults: a photo imported with primary XMP is edited only in that XMP, even
  when Settings defaults its format to embedded writes. Editing a field displayed via
  embedded fallback writes the new value to the primary XMP, leaving EXIF unchanged.
  Copying values between XMP and embedded metadata is a separate future action.
- The active XMP supplies each field it contains. **An explicitly empty value stays
  empty**, even when embedded metadata has a value. Only an absent field falls back
  to embedded metadata. Zero and false are values, not missing metadata.
- Preserve all sources, including extracted tags the app does not interpret. Map
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
  file-modification fallback into a claimed complete capture date. This filing rule is
  built for photo-only/resolved first imports and verified XMP/qualified JPEG edits.
- Choosing a metadata source is a separate operation from viewing a source tab.
  Explicitly choosing embedded metadata retains the XMP alternatives for inspection.
  Changing primary requires a deliberate action, a preview of changed effective values,
  any resulting refiling and future edit target, and confirmation. It copies no values
  between sources. Existing format support still applies; an embedded RAW primary
  must be deliberately changed to XMP before editing, never switched automatically.

The resolver accepts validated reader output: source IDs, qualified extracted `tags`,
canonical `fields`, and original bytes for every XMP version. It returns JSON-compatible
snapshots, the active/primary source ID, effective fields, each field's source ID,
source kind (`embedded`, `xmp`, `mixed`, or null for no effective fields), and fields
whose presence or values differ across snapshots. Original bytes are represented as
base64 with a SHA-1 fingerprint. This is an in-memory contract, not a storage schema or
public API. Persist original content as binary BLOBs as specified below, not base64
text. The reader's limits and filesystem contract follow below.

## Embedded/comparison adapter boundary (built; capture integration connected)

`metadata_adapter.from_embedded` maps unambiguous family-1 ExifTool captures: IFD0
Make/Model/Orientation and ExifIFD DateTimeOriginal with its own SubSecTimeOriginal and
OffsetTimeOriginal. Other captured tags are retained without guessing aliases. Thumbnail,
MakerNotes, embedded XMP, file dates and CreateDate never silently replace those EXIF
fields. The capture must use unconverted values (`-n`) and qualified groups (`-G1`);
JSONQ preserves numeric-looking strings such as camera names and fractional seconds.

The ordinary photo-scan worker still collects flat, print-converted metadata for existing
consumers. It never feeds that dictionary into this adapter. A separate Index metadata
phase uses family-1/family-4 qualified, structured, non-print-converted JSONQ capture;
family 4 retains repeated tag instances. Conflicting copies of a supported tag produce
attention, not a guessed winner. This adds a qualified ExifTool query for each photo
whose evidence is new/changed, using the existing bounded worker pool and persistent
ExifTool processes. Unchanged stable captures are reused. Legacy IPTC mappings and
broader format/property coverage remain pending; extracted tags are not all original
embedded packet bytes or proof of complete proprietary-metadata recoverability.

`metadata_adapter.for_comparison` produces detached canonical fields while preserving
all captured tags and original sidecar bytes. Orientation becomes an integer; XMP rating
uses exact decimal text without float rounding; EXIF capture-date components form the
same date representation as XMP. Explicit UTC `Z` and `+00:00` compare alike, but unknown
zones, recorded precision and local wall-clock values remain distinct. Missing date
components are never completed or borrowed from another source. Empty values remain
empty; a present partial primary date still suppresses embedded fallback.

Malformed supported values refuse the comparison view; callers must retain the capture
and explain the issue, not silently select another source. Unknown fields, arrays and
localized values remain unchanged. These views are not replacement storage snapshots,
filing dates or a metadata-writing API. Generated JPEG and TIFF tests independently write
and read EXIF using ExifTool, then compare against bounded-reader XMP captures. Common logical fields, including location, and the read-only source viewer are built;
broader format fixtures and mutation controls remain separate work. Photo-only and
resolved first imports use these captured fields for filing.

Extraction references: [ExifTool JSON/group options](https://exiftool.org/exiftool_pod2.html)
and [EXIF tag groups](https://exiftool.org/TagNames/EXIF.html).

## Index observation boundary (built; newly observed metadata remains inactive)

After the ordinary photo scan, Index records an immutable `metadata_captures` observation
per changed photo/evidence set, bound to its file identity, job and relative source path.
Schema 26 requires a fresh development catalog. Separate embedded evidence and proposed
resolution JSON keep existing photo metadata, destination projections, statuses, source
snapshots unchanged. Copy/Move also capture before transfer preflight, including direct
transfers without a prior Index. A development safety gate holds affected photo/XMP pairs
and photos with saved primary choices until paired transfers and filing activation exist.

The photo reader opens each path through no-follow directory descriptors and gives
ExifTool the held file descriptor through procfs. It refuses nonregular files, changed
names/content signatures and mismatched scan size/mtime; failed captures supply no
proposed fields. The catalog SHA-1 is the ordinary scan identity, not a second digest
verification in this phase. Unknown tags remain in qualified evidence. Supported mapped
fields use the tested adapter; malformed/ambiguous values and reader warnings carry
codes and details rather than disappearing into an embedded fallback.

Sidecar ownership considers every supported plain photo in the same directory, including
unselected/unindexed siblings and extensions excluded from the current job. The capture phase uses the association preference frozen at job start; saved
explicit ownership takes precedence. Proposals alone do not establish ownership. Unresolved ambiguity supplies no proposed values. Full-filename sidecars
outrank short names when resolved; other versions remain retained alternatives. Identical
candidate bytes need no arbitrary content choice. Unsafe sidecar names (symlinks or
nonregular entries) are reported and never followed. Orphans stay untouched; a complete
orphan inventory/notice remains part of later import integration.

Sidecar originals and known candidate file identities are retained in the existing
BLOB/arrival tables within the same FULL transaction as the observation. Unindexed
candidates remain named in the report, not invented catalog identities. This is evidence,
not activation. An unchanged re-index adds no duplicate observation/arrival, while a
sidecar-only change is read and retained even if photo bytes did not change. Removing a
sidecar changes the proposed observation without changing an existing primary choice.

Backups carry an additional capture-ID watermark from the actual SQLite snapshot;
observations arriving later remain unbacked even with older timestamps. A failure while
retaining an observation rolls back its newly retained BLOB/arrival. Cancellation stops
new read work and leaves committed observations intact; another Index reassesses the
source rather than interpreting missing work as a successful complete capture. Reader
issues appear in the engine log with the photo, category and available diagnostic details;
Source inspection and first-import ownership/version controls are built; incoming
and organized-primary decisions remain pending. No file edit, refile, automatic primary
replacement or paired source cleanup is enabled by this phase.

## Saved decisions (first-import API/UI built)

`engine/metadata_decisions.py` provides catalog-only `preview` and `confirm` functions.
Association choices bind a source root and relative sidecar name to captured photo file
identities; primary choices bind a photo to an immutable capture and resolved field origins.
Re-indexing may record new proposed evidence, but never rewrites a saved primary/version.
A deliberate sidecar-primary confirmation also atomically saves the ownership shown in
its preview if it has not already been saved. Changed defaults cannot detach that owner.
Removing ownership from a photo using that sidecar as primary requires changing its
primary deliberately first. Unknown/unindexed candidate identities cannot be selected.

Previews show old/new values, presence versus emptiness, field differences and whether
the filing date may change. This is not a computed destination-path preview or permission
to refile: use the separate verified activation CLI for Library photos. The SHA-256 preview token binds
the capture, current decision revision, ownership dependencies and proposed result. Confirm
recomputes it inside a FULL transaction and refuses stale evidence or active jobs. Changing
Settings alone does not invalidate an explicit choice. Exact request replay returns its
original decision; reusing the ID for different input is refused. Failed publication rolls
back both ownership and primary decisions. Records are immutable `metadata_decisions` rows,
with a snapshot-derived backup watermark so later decisions remain visibly unbacked.

The settings API accepts `xmp_association` (`ask`, `raw_only`, `non_raw_only`, `all`),
`metadata_write_raw` and `metadata_write_non_raw` (`xmp` or `embedded`). Defaults are ask,
XMP and embedded respectively. A job freezes these and the latest decision ID when accepted.
Setup and Settings expose these preferences with read-priority guidance. First run
requires an explicit association choice; ordinary Settings uses revision-checked saves.
Write defaults apply only without an established primary target and cannot enable an
unqualified writer. RAW remains XMP-only; embedded editing is qualified for JPEG only.
First-import ownership and competing-XMP choices are available in Not organized →
Needs attention. Deliberate primary changes for organized photos and incoming alternatives
remain separate unfinished workflows.
A live Settings notice explains that running jobs retain their starting configuration.

The transfer gate records Skipped for unsupported/unresolved cases, leaving source bytes
intact. Resolved first-import pairs proceed through verified transfer; ambiguous,
damaged and unresolved multiple-sidecar cases remain held with an explanation.
The incoming-alternative bridge below handles supported duplicate arrivals.
This also guards duplicate-source removal and direct Copy/Move without a preceding Index.
Other ordinary photos proceed. First-import ownership/version choices are available from source attention;
incoming-alternative choices remain unfinished. Confirmed import-pair retry is available from the photo issue, Logs and
eligible selections; see the import recovery contract below.

## Field-scoped edit plans (built; XMP execution connected)

An edit changes only explicitly selected fields and their required companions. The first
confirmed RAW edit creates a new full-filename XMP if no primary is established.
Index alone never creates one. That new XMP contains only the requested fields; other
values continue to resolve from embedded metadata. Its creation becomes established
primary only after the execution path verifies and records the operation. Existing
sidecars require a preservation-aware writer; never regenerate them from mapped fields.

`engine/metadata_edits.py` now implements read-only `plan` and `preview_catalog`, plus
`first_sidecar`, which constructs validated new XML bytes in memory. Supported planned
XMP edits are Date taken, Orientation, title, caption, keywords, rating, creators,
copyright/rights and GPS. Unsupported fields are refused as a whole; there
is no silent partial patch. JPEG embedded EXIF date plans explicitly set/remove
DateTimeOriginal's fraction/offset companions. Embedded XMP/sidecar dates use one XMP
property. An absent offset in the requested logical date does not inherit a stale old
one. The future editor must prefill the complete value and show any deliberate removal.
Partial/blank dates are supported in XMP; the initial embedded EXIF planner requires a
complete date/time and refuses blank/partial writes. Embedded RAW plans are refused:
RAW files are never written, and their edits use XMP sidecars only.

Catalog previews accept only an organized Library photo and its current stable capture.
They honor the saved primary version before Settings defaults, show per-field changes,
exact planned tag operations, a proposed primary/new-sidecar packet and a relative filing
path. A selected full date uses its recorded calendar day without zone conversion; a
blank/year/year-month uses Undated with the immutable original modification year.
Orientation alone leaves the current path alone, even if another date discrepancy exists.
Preview tokens bind photo/content/capture, primary revision, preferences and destination.
This does not freeze a future job: execution must accept its settings snapshot and
revalidate/recompute before touching files.

The planning functions change no files, catalog rows or primary decisions. The separate
XMP execution path below performs collision checks, live verification, backup, publication,
history and refiling. No web edit route or editor screen is exposed.
A preview is not a reservation or proof that files are intact. First-sidecar bytes are
not permission to replace an existing sidecar. Embedded publication and all
edit UI controls remain separate unfinished work. The embedded EXIF planner supports
Date taken, Orientation and representable text/list/rating values; it refuses unsupported
values rather than redirecting an established primary to XMP. This is a writer-capability boundary, not a new metadata
source preference. Generated tests independently read
new XMP through ExifTool and apply planned EXIF tags to a temporary JPEG, checking the
unchanged source, pixels, camera, caption and GPS alongside the updated date.

## Embedded JPEG edits (built for qualified representations)

`metadata_embedded.stage` creates a separate verified JPEG output without replacing
Library files or changing the catalog. `metadata_photo_save` connects it to the bounded
`--metadata` CLI after a confirmed preview, catalog backup and durable operation intent.
It publishes one photo at a time and records changed SHA-1/content identity, qualified
metadata before/after, source-versus-retained history, cache identity and date refiling.

For baseline/progressive single-image JPEGs, it verifies the expected original SHA-1,
reads qualified metadata, edits a private copy, reads back the requested fields and
compares unrelated tag instances. All JPEG bytes outside the selected EXIF or XMP block
must remain identical, including encoded scans, color profiles, comments, JFIF and IPTC.
Pillow also decodes both copies and compares unrotated pixels. This integrity check is
not the deferred image-only duplicate hash and authorizes no deletion or consolidation.
Extended XMP, trailers/multiple images and unsupported marker layouts are refused.
This includes embedded EXIF/XMP edits to motion-photo JPEGs. Sidecar edits can preserve
the unchanged photo and video; generated Google legacy, Pixel and Samsung save/refile
regressions verify extracted video against the manifest. Embedded motion-photo support
requires separate qualification and is not implied by successful sidecar saves.

Embedded XMP uses the preservation-aware packet writer and exact packet read-back,
including localized text, linked GPS, partial/empty dates and empty lists. EXIF supports
complete Date taken with linked fraction/offset removal, Orientation, Unicode XPTitle,
ASCII caption/copyright, one ASCII creator, semicolon-free keyword elements and whole
ratings 0–5. Explicit removal is qualified for all mapped common EXIF fields, including
the capture-date companions and supported GPS coordinate/reference/altitude tags. Removal
is distinct from writing an empty value. Other representations—including new EXIF GPS
coordinates, explicit empty values and partial EXIF dates—are refused without switching primary. Known required IFD scaffolding may
be added only with verified values, and is listed in the returned receipt. Existing
unrelated fields cannot be changed. Embedded TIFF and HEIC writing remain unqualified;
RAW files are never written.

The writer checks free space, bounds live reader output and tool runtime, rejects
symlink traversal and occupied staging names, preserves photo read/write permissions,
and returns before/after SHA-1 plus metadata evidence. Ordinary failed verification or
staging removes only its own working files. The publisher retains the old JPEG at a
recorded recovery name until the new file, catalog history and any date move verify.
Explicit retry resumes recorded publication or moves saved metadata without rewriting.
Check it now observes; it never publishes. An interruption before a staging receipt
commits leaves the original untouched and requires preserving/removing the unverified
staging file before retry. Filesystem guarantees remain subject to working fsync/storage.
Generated tests include a lying writer, image-data corruption, an unrelated-tag change,
missing date-companion removal, insufficient space, changed inputs, sync failure,
malformed images, Unicode values, progressive JPEG/ICC preservation, tool output limits
and a stalled tool. Public RAW smoke checks cover reading RAW files, not writing them.

Index can record source observations while retaining the edited Library content and an
unfinished operation's retry binding. The original source snapshot stays immutable.
Caches for the new SHA-1 use the edited retained file; old-source bytes cannot supply
its preview. Embedded EXIF and XMP writes recompute the visual hash from the verified
published JPEG and record it alongside the new SHA-1 in the photo, content and save
receipt. Orientation changes can change that hash even when stored pixels are unchanged.
A failed hash calculation records unavailable matching rather than reusing the old hash.
Apply and Retry compare new visual hashes once at the end of the batch; unchanged hashes
need no further comparisons. Interrupted comparison remains recoverable through similarity
repair. Exact-byte results matching another organized photo are recorded as
`exact_duplicate_photo_ids`. The public preview stages a verified output on a disposable
copy and binds its digest and survivor snapshot to the token. Confirmed equal-primary
Library matches retain the existing photo and retire the redundant edited destination;
Rejects or conflicting effective metadata refuse. Old duplicate source
pointers are detached because they no longer prove equality to the edited destination.

Copy leaves originals untouched. Move also keeps sources whose organized photo has
embedded edits unless this job explicitly confirms their removal (see below).
Unsupported embedded formats/values are refused; primary is never silently changed
to make an edit succeed.
Ordinary JPEG originals are temporary recovery material, not permanent photo backups.
After completion, metadata history does not promise byte-for-byte photo reconstruction.



### Source cleanup after embedded edits (engine; UI pending)

Correcting a date and refiling the organized photo is one edit. It does not remove
an original left at source by Copy. A later Move can include those originals under
**one confirmation for the job**, with the affected count and expandable list, or
leave them at source while moving the remaining photos. This choice is never a
persistent setting or a per-photo prompt. A filename-only change does not alter bytes
and follows normal verified Move without this extra consent.

The engine exposes a read-only `--metadata source-cleanup-preview` request with
`{"photo_ids":[1,2]}` on stdin, using the configured `--source` and `--dest`. It returns
per-photo eligibility, original/retained hashes, paths and reasons; it does not grant
permission. `--move --confirm-edited-sources --request-id <new-id>` supplies consent
for that job's normal selection. The flag is part of request identity; replay starts
nothing, and changing it on the same request ID conflicts. There is no settings default.
The caller must submit the same intended selection as the displayed confirmation;
execution rechecks each file against current evidence under the engine lock.

Before consuming a source, verify its live original hash, the live retained photo,
the recorded chain of image-preserving embedded writes, required destination XMP and
exact archived source sidecars. Require the current source identity, separate roots,
no unresolved file issue or unfinished edit, and a verified pre-action catalog backup.
Flush destination bytes and directory ancestry, commit verification at FULL, then
retire source names and flush their parent directories. Never overwrite the edited
copy. Shared source XMP stays until every owner has verified preservation; observed
absence alone does not authorize its deletion. Changed, unrecorded or unreadable
files refuse with an explanation.

Interrupted cleanup retains its intent and per-file outcome. Startup and Check it now
only observe and record; they never delete another source. A new explicitly confirmed
Move can finish the recorded cleanup after re-verification. Already completed photos
stay complete if a later file fails. No whole-job undo is provided.

The confirmation must say that the edited Library version is kept and source metadata
history remains, **but exact original photo bytes are not retained**. This is a deliberate
exception to byte-identical Move, not image-only duplicate detection. Preview/deletion
controls in the web interface remain unbuilt; ordinary web Move therefore preserves
these originals until that separate UI work is implemented.

### Release writer boundaries (agreed)

| Target | Supported in this engine release | Explicit limits |
| --- | --- | --- |
| XMP sidecar | Common-field values and removals for supported photo formats, including RAW; photo bytes unchanged | Custom unsupported extensions still refuse; existing primary never changes automatically |
| Embedded JPEG XMP | Qualified JPEG layouts; common fields, localized text, linked GPS, partial/empty dates, lists, decimal ratings and removals | Extended XMP, multiple images, trailers or unsupported JPEG layout refuse |
| Embedded JPEG EXIF | Complete capture date/time with recorded fraction/offset; Orientation 1–8; one default-language title/caption/rights; one creator; representable keywords; integer ratings 0–5; explicit mapped-field removal | GPS coordinate writes, partial dates, present-empty values, localized alternatives, multiple creators, fractional/-1 ratings and keyword elements containing semicolons refuse |
| Embedded TIFF/HEIC and other non-RAW formats | No embedded writing in this release | Deferred for separate preservation qualification; deliberately choose an XMP primary instead |
| Embedded RAW | Never supported | RAW edits use XMP sidecars only; deliberately choose an XMP primary before editing if needed |

The maintainer accepted these release boundaries. Unsupported values refuse the whole
request before publication; no automatic rounding, fabricated date/time, primary switch
or sidecar creation makes a refused embedded edit succeed. Existing text rules apply:
EXIF XPTitle/XPKeywords preserve supported Unicode, caption/rights/creator require ASCII,
and NUL characters refuse. An empty Orientation is not a supported value in either
writer; explicit removal is distinct from Orientation 1 (normal display).

`remove_fields` explicitly removes mapped properties; it does not write empty strings.
It can accompany independent `changes`, but the same field cannot appear in both.
Removing Date taken removes its fraction/offset together. Removing GPS removes the
mapped latitude/longitude references and altitude/reference; unrelated GPS properties
remain untouched, so this is not a privacy-scrubbing operation. The established primary
is the only write target. Sidecar/XMP removal may expose a fallback value, shown in preview;
EXIF-only primary does not fall back. Historical reproduction still refuses a fallback
that cannot reproduce the selected state. Date removal previews and executes any refile.

ExifTool can drop EXIF header values when the last date is removed. The writer reasserts
existing ExifVersion, ComponentsConfiguration and ColorSpace values, then runs the same
strict unrelated-tag and image-byte checks. It does not excuse their loss or substitute
defaults. Read-back must establish that every requested removed field is absent. Missing
fields are a no-op, and unrequested namespaces/properties remain preserved.

## Common-field XMP construction (built; XMP publication connected)

`metadata_writer.sidecar_bytes` changes only requested properties in a validated existing
packet. It preserves unrelated qualified property trees, language alternatives, arrays,
qualifiers and comments, then reparses and checks the result. A true no-op returns the
original bytes. Serialization can change after an edit; the archived original remains
the exact previous version. The minimal first-sidecar builder must not replace an existing
packet. Neither helper writes a photo, publishes a file or changes the catalog.

The common-field request contract uses `date_taken`, `orientation`, `title`, `caption`,
`keywords`, `rating`, `creators`, `rights` and `gps`. Text accepts language dictionaries;
a new plain string becomes the `x-default` alternative. Keywords are RDF Bag values and
creators are ordered RDF Seq values, preserving order, Unicode and duplicates. Empty
strings/arrays/alternatives remain explicit values. Rating retains decimal precision.
Existing unknown properties remain unchanged; unsupported requested fields refuse the
whole patch. The bounded parser validates generated output too.

GPS is one source-owned logical value, never latitude from one source and longitude
from another. Its engine representation retains XMP coordinate strings (degrees,
minutes, optional seconds, and hemisphere), plus optional altitude and altitude reference.
An edit supplies both coordinates and, if present, both altitude components. `{}` clears
the location explicitly. Partial recorded GPS is preserved for inspection and suppresses
fallback; it is not silently completed. Decimal-degree ExifTool captures convert to XMP
minutes using decimal arithmetic, without binary-float rounding. Original lexical evidence
is always retained; different lexical representations can still appear as differences.

Qualified EXIF capture additionally maps XPTitle, ImageDescription, Artist, Copyright,
XPKeywords, Rating and GPS. It does not infer IPTC precedence, or mix EXIF and embedded
XMP into one source. New mappings advance the observation reader version so unchanged
files are recaptured once. Generated tests independently read all new XMP fields with
ExifTool and check explicit clears, partial GPS, precision and namespace conflicts.

## Verified XMP editing (engine and CLI built; UI pending)

`metadata_save` accepts only a fresh, confirmed catalog preview under the engine lock.
`metadata_command` exposes `--metadata preview|apply|retry|discard` using bounded JSON
stdin. Mutations require a request ID; the normal job acceptance layer handles replay
and conflicting reuse. Every batch freezes its settings. An existing primary wins over
format defaults; unsupported embedded targets are refused rather than redirected.

The engine retains exact old/new XMP versions before a verified pre-action catalog backup.
Batch preparation takes one backup covering all prepared versions before publication.
It stages and reads back only the requested edits, moves the old sidecar to its recorded
recovery name, and publishes with no-replace operations. Interrupted gaps remain journaled;
retry completes the same intent. A partially written staging file may be reused/removed
only when its recorded inode still belongs to the edit. Unknown files are never cleanup.
No-op edits leave the file timestamp and version count unchanged.

After photo/XMP verification and file/directory sync, one FULL transaction records active
sources, primary, differences, before/after version identities and photo revision.
Date changes then use verified pair relocation. Failed refiling retains saved metadata
and exposes the recorded move for retry; it does not rewrite the metadata again.
Reject/Return and force reindex preserve the new verified metadata and current pair.
Failures retain their causes in immutable attempt events plus an actionable file issue.
Shared unsafe storage errors stop later batch publications. Completed edits remain saved;
later items are reported not started. There is no job undo.

`--metadata retry` resumes explicit operation IDs; it can repair a failed pre-action backup
before publishing. `discard` succeeds only while the original pair verifies unchanged,
then cleans only its own staging material. Once metadata has been saved, finish the move
or cleanup rather than discarding the successful edit. Startup and Check it now observe
unfinished metadata intents without publishing, moving, deleting or guessing success.

Explicit field copying takes whole logical values from an immutable capture/source or
associated retained XMP version. Missing donor values refuse; explicit empties remain
empty. Donor/version/hash origins accompany the edit history. Copying fields keeps the
target primary. A separate retained-version request previews a deliberate complete XMP
primary change, including effective values and date refiling. It verifies association and
publishes the exact selected packet, preserving the previous version. This engine action
works for Library photos. A confirmed incoming-decision request separately binds
metadata selection and optional Return for Library/Rejects photos (see below).

Qualified JPEG publication/recovery and content/cache updates are connected.
Still unfinished: additional embedded formats/representations, plus web routes and UI.
A source-reader's format support is not permission to write that format. Supported
earlier-state reproduction is connected to the verified writers below.

## Photo-only imports and embedded-primary activation (engine built)

Photo-only Copy/Move uses captured embedded XMP before EXIF for absent fields; explicit
empty and partial dates remain Undated. Unsupported custom extensions retain their existing
transfer behavior. The frozen job choice and verified delivery receipt determine the
catalog projection; no metadata bytes are rewritten by import. Automatic read priority
alone establishes no embedded write primary, so the RAW sidecar write path remains available.
Source read failures are failed transfers with their underlying reason, not decision skips.

A Library metadata request can select `primary_id: "exif"` or `"embedded_xmp"` instead
of field changes or an XMP version ID. Preview shows actual before/after field origins,
future edit target and date filing; Apply verifies the photo and any recorded sidecar,
requires the batch backup, and records the deliberate choice. The selected source must
already exist. No tags are copied between sources. Existing sidecars remain byte-identical
and follow the photo if its effective date changes. Source switching does not authorize
an unsupported embedded writer; RAW edits use XMP sidecars only.

An unapplied catalog decision is not proof that the photo was refiled: preview uses the
last verified activation. Saved primary changes survive a failed date move; Retry finishes
that move without repeating the metadata choice. Check observes and explains remaining
work; Discard is permitted only before activation. Copy/Move preserves sources until an
unfinished metadata operation is completed or discarded. Reindex preserves verified metadata and
current filenames. Photo-only force Index retains normal transfer eligibility so a later
Copy can repair a removed destination. Switching after a JPEG edit retains its new content
identity and leaves original source bytes intact; post-edit source cleanup remains separate.

## Multiple-sidecar first imports (engine built)

Normal Copy/Move now activates a resolved first import with multiple associated sidecars.
A full-filename packet takes priority over a short-name packet unless a saved explicit
primary says otherwise. Equally specific differing packets require a choice; identical
packets reuse one BLOB while retaining every arrival/name. Ownership of every associated
packet must be resolved before transfer, including short names shared by RAW/JPEG files.
Damaged or unreadable associated metadata still holds the photo for attention.

Only the selected packet is written beside the destination photo. Every inactive original
is retained byte-for-byte in the catalog with its source arrival and photo association.
The completed operation lists those versions and reports alternative retention. A later
edit or primary switch cannot make a known alternative appear to be a new arrival.

Transfer intent freezes all packet hashes, versions, source identities and owners.
Before deleting any source, Move verifies the destination photo/sidecar and every archived
original, and commits durable evidence. It rechecks an alternative immediately before
unlinking it and syncs its directory. A shared source packet stays while another owner
needs it or lacks verified delivery evidence. Recorded ownership survives partial Move
jobs; replacement files at an old source path require a new association decision.

Recovery observes files and originals without cleanup. If an alternative still needs
removal, the operation remains incomplete for explicit same-mode retry; a retry repeats
failed directory barriers even after an unlink. Missing originals without prior verified
evidence never authorize success. Copy keeps every source. Adding/changing versions
beside an already organized source remains on the separate incoming-choice path.

## Incoming duplicate XMP (engine preservation and confirmed activation built)

Schema 26 adds immutable `incoming` decisions and persists the metadata-observation
progress phase. Rebuild development catalogs; there is no upgrade path. For an identical
photo already in Library or Rejects, `metadata_incoming` preserves associated original
XMP versions and arrivals without replacing the retained primary or changing its location.
Different incoming metadata beside an existing XMP records a review flag. An identical
known version reuses its BLOB and records its origin without reactivating an alternative.
A retained photo without XMP requires an explicit metadata choice first.

Catalog preview/confirmation offers primary and location choices together, binds retained
identity/revisions and captured versions, rejects stale choices and conflicting request
IDs, and respects each job's decision watermark. **Keep current** can proceed without
changing primary/location. **Use incoming** and **Return to Library** execute through
a separately previewed metadata job; saving a decision alone does not apply it.
Decision/review routes and screens are unbuilt.

`metadata_incoming_apply` accepts a confirmed decision identity, the retained photo and
its current capture. Preview shows effective field differences and the final location.
The saved decision independently selects current/incoming metadata and current/Library
location. Choosing new metadata never implicitly returns a reject. Keep current + Return
moves the current photo/pair unchanged, creating no XMP when none existed. Use incoming
publishes the exact archived packet; empty fields stay empty and an explicitly cleared
date files to Undated when moving into Library. Keeping a photo in Rejects preserves its
current rejected path even when the chosen metadata has a different date.

A job binds the decision, both photo identities/revisions, captured versions and frozen
preferences. Superseded decisions, newer-than-job choices, stale captures/ownership and
changed retained targets refuse. Every original verifies before mutation; the normal
verified pre-action backup precedes publication. No-overwrite names and the existing
journaled save/refile paths handle collisions, orphan XMP, cancellation and storage
failures. Metadata saved before a failed Return remains saved; explicit Retry finishes
the remaining move. Discard only abandons unchanged work, never undoes saved metadata
or an initiated relocation. Startup and Check it now observe without finishing it.

A separate immutable `incoming_choice_applied` receipt commits with the final status;
it does not rewrite the original choice. Return restores the existing Copy/Move status
semantics. Applying a choice never deletes incoming source files. A later Copy/Move
uses the verified post-application binding and still checks source identity, retained
photo/active XMP, every archived alternative and shared-owner proof before cleanup.
Unfinished metadata operations block consumption of their associated incoming pair.

Normal duplicate Copy/Move jobs verify the retained photo, any recorded active sidecar,
and every archived incoming original before committing preservation evidence. Copy keeps
the sources and records a duplicate skip with its preservation reason. Move removes the
source photo only against its verified retained copy; source XMP cleanup additionally
verifies archived exact bytes, its current identity and shared-owner receipts. Incomplete
cleanup is recorded with a specific issue and can be retried explicitly in the same mode
and roots. Recovery observes and records, never starts source cleanup. A missing source
without prior durable evidence cannot authorize removal of the remaining member.

This bridge handles distinct incoming photo identities and confirmed late-XMP choices
for the original of an already Copied photo. The latter preserves the organized anchor
instead of relabeling it as its own duplicate; repeated Copy and subsequent Move keep
the verified binding. Unconfirmed late versions remain held. Non-JPEG embedded writers
and metadata mutation API/UI remain unfinished. Photo-only read priority, verified XMP/qualified
JPEG edits and deliberate Library embedded-source activation are built.

## Reader and ownership helper boundary (built; Index capture connected)

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

The reader/storage snapshots remain lexical and unchanged. The separate comparison
adapter above normalizes the initially supported fields. Live capture, broader mappings
and partial-date filing integration must still be built before these values determine
organization.

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

The catalog capture layer chooses primary candidates for newly organized photos
whose associations are resolved: a full-name version takes priority, but multiple
full-name candidates remain unresolved. All associations remain available as alternatives.
No helper modifies recorded ownership/primary, catalog rows or file content. First-import version reuse and catalog choices are integrated. Orphan-notice clearing
still requires its separate integration.

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

| Situation | Agreed behavior (implementation boundaries above) |
| --- | --- |
| Both full-name and short-name XMP belong to a newly organized photo | Use the explicit full-name sidecar as primary without a prompt; preserve the other as an inactive alternative and report its retention. A short name beside RAW/JPEG still needs association resolution. |
| Incoming XMP is byte-identical to any retained version | Reuse its stored content without another prompt; record the new arrival, original filename/source and photo association in lineage. Do not reactivate an inactive version. |
| Existing Library photo has no XMP; incoming identical photo has XMP | Hold the incoming pair at source for a metadata choice. Keep current primary and retain the incoming XMP as an alternative, or explicitly use incoming XMP after preview/confirmation. Decide later leaves the pair untouched. |
| Existing photo already has XMP, or a Library photo has metadata edits; incoming XMP differs | Keep the current primary, safely retain the alternative, and flag Metadata differences for review. Import need not stay blocked once preservation is complete. Keep its current location, including Rejects; review can offer an explicit Return. |
| Matching photo is in Rejects and has no XMP | Present metadata choice and location choice together: keep current primary / use incoming XMP, independently of leave in Rejects / Return to Library. Preview and confirm the combination. Decide later leaves the incoming pair at source; no automatic Return. |
| Several differing incoming versions have no established primary choice | Preserve all versions and origins, and hold the incoming pair for an explicit decision. Do not guess which version to activate. |

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

## Exact originals, compression and catalog backups (storage and resolved first imports built)

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

## Earlier metadata states and exact-result consolidation (engine built)

Reproduction of an earlier meaningful state is distinct from exact-file restoration.
Given surviving unchanged image content and complete structured records, the goal is to
reproduce supported recorded metadata from either the source observation or a selected
pre-edit state. Preserve original observations, before/after field values, absence,
explicit emptiness, removals, source/primary bindings and version origins. Human-readable
log messages alone are insufficient. Reproduction is a new verified operation with
preview, confirmation and lineage; it does not erase history or add an automatic undo.

**Built engine boundary:** `metadata_reproduce` selects this photo's immutable source
observation (`capture_id`) or the state immediately before a completed metadata edit
(`before_operation_id`). It reapplies the supported common-field effective values as a
new confirmed edit to the current established primary. Choosing a historical state never
silently changes primary. Preview lists every supported value and its presence, historical
source/bindings, proposed removals, unchanged primary and any filing change; the intent
and save receipt preserve this provenance. Incomplete observations, foreign identities,
unfinished/discarded operations and stale previews refuse before publication.

Missing historical fields remain absent rather than becoming empty strings. Added mapped
fields can be removed in sidecars and qualified JPEG EXIF/XMP, including complete
mapped GPS coordinate groups. Explicit historical blanks remain blank. Removing the date updates
filing and catalog date provenance. If the current primary's fallback would refill a
historically absent field, the complete reproduction refuses; the user must deliberately
choose a primary or copy selected fields instead. Unsupported EXIF value representations
(such as present-empty fields) remain refused at the agreed release boundary, without
partially applying the other fields. Unknown/unwritable properties are not reproduced; unrequested current
properties remain preserved. A state with no supported values and nothing to remove is
reported as requiring no supported reapplication rather than creating an empty sidecar.

The organized image must survive and verify against its current catalog digest. When
its hash differs from the historical photo, recorded verified JPEG staging/publication
steps must connect those digests and prove unchanged image content. Same photo ID or
pHash alone is insufficient. The original source need not remain on disk. Existing
verified backups, no-overwrite writes, read-back checks, date refiling and explicit retry
apply. No-op reproduction records its intent without inventing another version. This
engine workflow does not restore old filenames, switch location roles, rewind other
jobs, consolidate duplicates or provide an editing UI.

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

**Engine composition is built.** The existing field-copy request accepts an explicit
`base` using the same immutable capture/source or associated retained-XMP selector as a
field donor. It copies the base's present supported common fields, then applies explicit
field donors and typed overrides. A typed value and donor for the same field refuse.
Missing base fields are listed separately and remain unchanged in the target; absence is
not an instruction to clear. Explicit empty values are applied as empty and suppress
fallback. Unsupported/unknown base properties are not transplanted; the writer preserves
unrequested properties already in the target. This is common-field composition, not a
byte-for-byte packet replacement or an implicit primary change.

The preview includes all supported final values, presence, effective source and per-field
origin (base, explicit donor, typed, or unchanged), plus immutable donor identities/hashes
and the filing result. Apply recomputes the preview under the job's frozen settings.
Existing backup, verified publication, retry and no-op rules apply. The immutable intent
and successful save receipt retain composition provenance. No-op composition retains its
intent but does not manufacture new versions. Source originals remain unchanged.

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

An embedded edit that creates an exact whole-file duplicate previews the existing
Library survivor and requires confirmation. `metadata_duplicates` verifies live byte
equality, the survivor's file/revision/primary/sidecar, and preserved XMP originals.
It journals both histories and inactive alternative associations before retiring the
redundant destination. The survivor keeps its name, location and primary. Rejects and
different effective primary fields stop the edit without changing either file. New
matches appearing after preview, including earlier saves in a batch, require a fresh
confirmation. Interrupted cleanup is explicitly retryable and verifies the survivor
again before either unlink. Copy/reindex retain the consolidated relationship; later
Move still requires edited-source consent. History remains connected after later edits.
These checks also guard engine callers without a duplicate-aware preview: they refuse
an unconfirmed match before publication. Existing duplicates are not bulk-cleaned.
This does not enable the proposed image-content matching workflow below.

**Production image-content hashing and its consolidation workflow are deferred by the
maintainer.** Finish EXIF/XMP preservation and verified editing first. The extra hash
is not required to detect byte-identical results of a future staged metadata edit.

A generated-fixture [JPEG experiment](jpeg-content-hash-experiment.md) now tests a versioned
SHA-256 fingerprint over encoded image data and decoding context, with separate recognized
metadata hashing. Twenty tests pass, including independent ExifTool edits and decoded-pixel
checks; measured warm-read cost is documented. It is isolated under tools, not used by
Index or cleanup. Unsupported layouts are refused, and decoding/metadata preservation
are not certified by the fingerprint. RAW and broader JPEG coverage, integrated cost and
pre-removal equality verification remain open. A pHash match never establishes exact
image-content equality. Neither hash stores image data or reconstructs a file. These image-content
consolidation capabilities remain unbuilt. Supported earlier metadata reapplication uses
the verified edit history above, not the experimental content fingerprint.

Existing edit-backup policy remains: a pre-action catalog backup and structured metadata
history for all edits; verified temporary outputs and recovery material until completion;
exact retained XMP versions. RAW files are never written (`engine-spec.md` §9.6). There is no new requirement to permanently retain every
pre-edit JPEG or other ordinary photo file.

## Verified pair transfer primitive (built; resolved first-import jobs connected)

`engine/metadata_transfer.py` provides an internal, FULL-transaction Copy/Move protocol
for one photo and one resolved destination XMP, plus exact archived alternatives.
Normal Copy/Move calls it through
`metadata_import`, with the job's captured evidence, selected filing destination and
frozen decisions. Unresolved ownership/primary choices remain held; a separate
`metadata_incoming` bridge handles supported duplicate alternatives.
Recorded-pair Rename, Reject and Return are implemented separately below.
The caller owns the engine lock. Normal jobs request a bound activation plan from
`metadata_import`; the pair primitive commits it only after successful verification
and cleanup. Internal callers may transfer without activating metadata.

Preparation binds the photo/capture, original XMP version, roots, paths, owner identities
and checksums in durable operation intent. Ordinary photo-name collisions suffix the
photo and full-filename sidecar together. An orphan destination XMP stops the pair for
attention; it is not silently renamed around or adopted. Identical destination pairs
are verified and reused. Differing destination XMP is refused for a metadata decision;
this primitive does not overwrite it or implement alternative-version activation.

Both destination files and their containing directories are verified/durably saved,
then pair evidence commits before any Move source removal. Copy keeps both originals.
A partial shared Move retains source XMP while another owner needs it. Last-owner cleanup
requires matching verified destination receipts for the other captured owner identities;
absence alone, an unindexed owner or an uncertain receipt never permits deletion.
Publication uses the existing durable copy protocol and inherits its documented
filesystem limitations; this is not a stronger guarantee for unsupported/network storage.

Failure leaves published files for inspection/reuse, settles an incomplete operation and
records its specific reason and the attempted step with its involved paths in the
settled event, plus per-member destination verification results. A successful photo
publication followed by XMP failure records verified photo and incomplete XMP. A final
pair-verification failure clears earlier green results conservatively; verified pairs
remain recorded as such when later source cleanup fails. Read-only interrupted recovery
records its observed destination results too. No additional file reads or commits are
needed for execute's diagnostic progress. This does not change publication/cleanup rules.
Older/unlocalized failures retain null context rather than an inferred file diagnosis.
A photo-only arrival does not enter Library. An explicit
retry creates linked new intent, checks the catalog binding and existing bytes, and
reuses verified output. A successful retry clears only its own pair-issue chain; unrelated
issues remain. Completed replay never deletes new files at the former source paths.
Startup dispatches interrupted pair intent to pair-aware read-only recovery before the
legacy photo-only recovery. Recovery never removes a source or finishes a publication;
it either verifies the completed pair or records what is incomplete for explicit retry.

Generated tests exercise actual temporary file transfers, shared owners, collisions,
filesystem/catalog failures, process interruption boundaries, retry/replay and source
preservation. Normal jobs include sidecar space, finish the current pair before
cancellation and support explicit same-mode retry. An incomplete pair remains Failed
outside Library. The shared photo/Logs issue panel and eligible selection count open
**Retry photo/XMP transfers**: recorded failures and paths, then a separate confirmation
for Copy or Move. The preview reads catalog evidence only; it does not promise the
external cause is fixed. The engine verifies live files before reuse or source deletion.

The API passes selected IDs through the normal validated selection file plus
`--pair-retry-token`. The token binds the latest pair intent, issue, catalog identity,
source/destination roots and original mode. The engine checks it at acceptance and
around startup recovery. Stale confirmations refuse; exact request replay returns its
original run. Successful retries resolve only their linked issue chain. Ordinary
Copy/Move eligibility stays unchanged. If all source photos are gone, empty-source
confirmation still applies. Network safety questions preserve the original Move rather
than offering a mode switch for an already-partial pair. No schema change is needed.
Broader metadata decision screens remain separate work.

## Destination pair relocation (built for recorded pairs)

`metadata_relocate` connects recorded photo/XMP pairs to the existing Rename, Reject and
Return actions. The current retained photo identity locates its verified pair receipt;
changing the filename or moving between Library and Rejects keeps the same XMP version.
Contents and metadata priority do not change. An unrecorded sidecar is not adopted.

After the existing catalog backup and durable intent, publish both new names without
replacement. Use hard links where available; otherwise stage verified copies and require
no-replace rename support. Verify and fsync both new files and their directory chain,
commit pair evidence, then retire the old names and sync their directories. Only afterward
do paths/status/history advance together. Photo-name collisions suffix both names;
orphan target XMP, unreadable/missing recorded XMP or mismatched bytes stop the action.
Stable storage-directory assumptions and documented filesystem limits still apply.

Startup recognizes pair relocation intents before photo-only recovery. It can finish
old-name cleanup only after both new members verify. Partial publication is never filled
in automatically: Files needing verification explains that the original action needs repeating after
storage access is restored. Retry uses the recorded target and resolves only its own
issue chain, preserving the earlier failed attempt. A different action/name is refused
until that pair is settled. It does not silently create a suffixed second pair.

Check it now verifies all four recorded locations without publishing or removing files.
Both new members verified and old names absent allow catalog repair; both originals
verified and both new names absent establish that nothing moved. Partial pairs, remaining
old names, cancellation and stale catalog bindings keep the issue. Directory sync is
repeated even after an earlier unlink, so a failed barrier cannot be skipped by recovery.
This uses the existing Files needing verification route. Initial import-pair retry has
its own confirmed Copy/Move flow described above; it does not retry Rename/Reject/Return.

Generated tests cover the full Rename/Reject/Return cycle, bytes and identity preservation,
collisions/orphans, symlinks, unsupported hard links, racing publication, catalog/fsync
failures, interruptions between each member, explicit retry and read-only checks. Normal
CLI imports are enabled only for resolved ownership/primary cases; relocation does not
edit metadata or change its priority.

## Interrupted transfers (resolved imports and incoming choices built)

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
a catalog-wide destination scan. **Check my library** and **Repair** in place for
external changes are decided, not built (`engine-spec.md` §9.2). They are separate
from the required checks on each transfer.

If metadata saving succeeds but subsequent refiling fails, retain the verified edit and
record the actual location plus Needs refiling. Explain the specific permission, space or
storage error; the user fixes the cause and retries only the move, carrying active XMP.
An uncertain outcome requires verification before retry. Individual edit failures may
leave unrelated photos eligible to continue, but shared storage failures that make further
writes unsafe stop new edits. Completed edits remain; report succeeded, failed and
not-started photos separately. These rules are built for XMP and qualified JPEG edits;
additional embedded formats still require qualification.

## Editing behavior agreed for implementation

The editor shows the chosen primary source's own values, not the merged effective view.
A missing XMP date stays absent when editing another field. Other sources are available
for inspection and explicit copying only. An untouched absent field is not a request to
clear it. Distinguish **Not set** from **Explicitly cleared**; a deliberate Clear value
writes the primary's empty value and suppresses fallback. Clearing the effective capture
date proposes Undated/<original source modification year>, with the sidecar following.
The preview shows refiling before confirmation. The current edit time never supplies
that original modification year.

Saving unchanged values does not rewrite files or create metadata versions. Explicitly
copying a fallback value into a previously absent primary field is a real change even
when the effective display stays the same. Batch edits use each photo's established
primary and frozen job settings, preserve successful edits when another fails, and
report completed/no-change/failed/not-started outcomes separately. Never silently create
XMP or switch primary to bypass an unsupported writer or permission failure.

A failed edit is flagged with its cause in photo information and Logs; Library photos
also appear in Needs review → Files needing verification. Distinguish a verified unchanged original
from an uncertain interrupted operation. Successful retry clears only the relevant issue.
Discard requested edit is permitted only when the original is verified unchanged;
uncertain outcomes require verification/recovery. Other review reasons remain intact.
The XMP execution path implements these engine rules; embedded editing and the web
resolution controls remain unfinished. The pair-transfer primitive alone is not an editor.

There is no job-level undo. Restoring supported prior metadata is a new confirmed,
verified operation with new lineage; it does not erase intervening history. Record the
changed fields/source, before/after values, photo hashes, paths, XMP versions and outcome.
Exact XMP restoration remains separate from photo-byte restoration, which needs the
original photo. An interrupted job's recovery is not undo of a completed job.

External destination editing is the maintainer's responsibility for now. No monitoring,
external-edit conflict UI or automatic reconciliation is added in this workstream;
**Check my library** and **Repair** are decided, not built (`engine-spec.md` §9.2).
The engine must still verify its own actual reads/writes, prevent unintended overwrites
and verify before deleting source files.

## UI handoff — source viewer, date editing and preferences built; decisions pending

Setup's Metadata step and Settings › Metadata must show **Which metadata is used?** beside
the metadata association/write questions. Keep the priority explanation visible, using
the shared guidance style rather than hiding it behind a tooltip or introducing another
required choice. Suggested copy:

> Unless you deliberately choose a different source, we use metadata in this order:
> 1. XMP sidecar — a separate file beside the photo.
> 2. Embedded XMP — metadata stored inside the photo.
> 3. EXIF — metadata stored inside the photo, often by the camera.
>
> If a field is missing, we check the next source. An explicitly empty field stays
> empty. All sources remain available for comparison. An existing source choice is
> preserved. This read priority is separate from where future edits are saved.

Use the same explanation in both locations. Index observes priority; a resolved
first-import Copy/Move activates filing only after verification. In the source viewer, name **XMP sidecar**, **Embedded
XMP** and **EXIF** on separate tabs rather than merging embedded evidence or labelling
every XMP value as a sidecar value. Keep the Primary marker and field provenance accurate. Viewing is
not activation; deliberate source changes still require preview and confirmation.

When Settings opens during a running job, show the shared informational notice near
the top, across tabs: **“A job is running. Processing changes you save now will apply
to future jobs, not this one.”** Keep its layout stable if the job starts/finishes while
Settings is open. Retain the near-Save explanation and active-job save confirmation;
see `webui-spec.md` §3 and `ui-design.md`. This notice is implemented through the shared
job feed, with stable active/idle/unknown messages and no draft reload. The generic
future-jobs notice and save confirmation remain.

Future reproduction/consolidation messaging must distinguish supported earlier metadata
states from exact original files: while unchanged image content remains available,
recorded metadata can be reproduced through supported writes, but the file hash may
change. Catalog backups are not photo backups. The engine supports this within its
qualified writer boundaries; the UI remains planned. Do not promise recovery of missing
pixels or unsupported metadata. Consolidation previews identify the surviving photo and preservation of both
origins/history and metadata alternatives.

Within Photo information, use shared **XMP Sidecar**, **Embedded XMP** and **EXIF**
tabs, preserving the outer Photo information / Similar photos navigation. Open the
primary source initially when available and mark its tab **Primary**, not just with
color. Selecting another tab only views that source. Source tables show captured values;
filing information separately identifies any effective fallback origin.

Alternative tabs offer **Compare with primary**, showing Field / Primary value /
This source with neutral differences and **Show differences only**. Distinguish
**Empty** from **Not recorded** and request/read errors from either. Alternate sidecar
versions remain inspectable, with the active version clearly identified.

The first editing UI exposes only **Date taken**. **Copy to primary…** prepares its
draft from the viewed donor; manual input is also available. Absent donor fields leave
the target unchanged; explicit empty values propose a clear, disclosed before saving
and subject to the writer's representation limits. Only requested date components and
required companions change. Other fields remain read-only; no general Select All or
whole-source composition control is required. The broader engine remains supported.

Preview the exact primary write target, before/after date and filing paths, including
first-sidecar creation or Undated filing when applicable. One confirmation covers
Save and required refiling. Ordinary edit/copy-field previews observe destination names
and suffix photo-name collisions before confirmation. This read-only check reserves
nothing: Save re-derives the preview under the engine lock, and a changed target requires
new confirmation. Orphan sidecars, unsafe paths and non-file obstructions still refuse;
execution/recovery never silently changes the confirmed target. Missing XMP dates are
never prefilled from another source.
**Use as primary…** on an organized photo’s readable non-primary tab is a separate
deliberate preview/confirmation of
effective-value changes, future edit target and any refiling; copying does not activate
the donor. UI details live in `ui-design.md`; source reads, Date taken copying and Use as primary… are built.

A completed job must summarize unresolved cases (for example, "1 photo needs a metadata
choice") and link to Not organized → Metadata choice needed. An alternative retained
without blocking import gets a preservation notice and history; Library photos with existing XMP or metadata edits
additionally get Needs review → Metadata differences. These notices remain planned.

Import messages distinguish preservation from activation: **Keep current primary** saves
the incoming XMP as an inactive alternative without changing current metadata/folder;
**Use incoming XMP as primary…** previews changes; **Decide later** leaves the source pair
untouched. For Library photos with existing XMP or metadata edits, explain the nonblocking review reason:
“Another copy arrived with different XMP metadata. Your current metadata is unchanged.”
For Rejects, explain that new metadata may change the user's decision and present the
independent metadata/location choices together with one preview and Apply choices.

Preserve photo/selection context and stable layout while switching tabs. Follow
`ui-design.md` for typography, spacing, tabs, keyboard behavior and differences. Validate
with embedded-only, XMP-only, mixed, conflicting, explicitly empty, unknown-tag and
multiple-version fixtures before enabling the screens.

## Remaining implementation and decisions

The authoritative engine countdown and separate UI/deferred backlog are in
[TODO.md — Dates and metadata](../TODO.md#dates-and-metadata). **Tasks 1–7 of 7 are complete;
0 feature tasks remain.** Update that checklist, this implementation status and the handoff together
when a task is implemented and validated; completed foundations are not new tasks.

Job-confirmed post-edit source cleanup and writer qualification are complete within the
agreed release boundaries above. PR #105 merged after passing CI; PR #107 subsequently
integrated the navigation stack and schema 28 after its combined checks passed.
Additional formats/representations are deferred work, not hidden items
in this countdown. Source tabs, Date taken edits, Move confirmation and import-pair
retry are built in the separate API/UI workstream; broader decisions remain pending.

XMP and qualified JPEG publication/recovery, earlier-state reapplication, base composition
and explicit field copying, Library primary
switching, photo-only and resolved first-import filing and the 200,000-version storage/backup
measurements are built. They must not be described as unimplemented integration work.
Broader destination scans, production image-only hashing and external sidecar-change
handling remain deferred; none relaxes verification or source-deletion safety gates.

The source viewer and Date taken editor API/UI have passed maintainer validation,
including source comparison, date/refiling previews and save feedback. Use as primary…
and first-import XMP choices are built; incoming-duplicate choices remain future UI work. Job-scoped edited-source
cleanup confirmation has also passed maintainer validation. Import-pair retry has
automated coverage and maintainer visual acceptance (R1–R3, 2026-10-15). Metadata
setup/Settings acceptance S1–S3 passed. Warning-only organization (W1) and date/attention
wording (D1) also passed maintainer validation. A dedicated Metadata setup step and
Settings tab remain layout follow-ups. Automated engine tests do not establish
acceptance of future screens.

### Web Move confirmation

The web boundary uses a catalog-only scope snapshot, not repeated full-file hashing
while the user considers the confirmation. It freezes Move all/folder into explicit
catalogued IDs, shows edited-original names and the original-byte preservation warning,
and requires Include or Leave for this job. `--move-preview-token` binds those IDs and
current catalog identities/edit events to engine acceptance under the lock. Changed
state refuses before scanning/transfer. Normal live hashes, image-history proof and
pre-action backup remain the deletion gate; a preview is never proof that files are
currently intact. Exact request replay still precedes stale checks. File verification
failures appear in the resulting job; the source stays whenever safe removal cannot
be established.

### Reader warnings versus import holds

ExifTool Warning diagnostics are retained as informational capture/report `warnings`,
separate from blocking `issues`. Unknown MakerNotes do not prevent unchanged Copy or
Move, with or without an associated readable sidecar; original bytes and diagnostics
remain preserved. Reader Error diagnostics, unstable source reads, source-directory
failures and unresolved/unreadable sidecar associations retain their existing holds.
Metadata interpretation and embedded-write preservation checks are not relaxed.
Reindex refreshes earlier warning-only holds without rewriting historical captures.
The metadata viewer explains known warnings and keeps exact diagnostics available.

### First-import choice screens

Pending photos with captured ownership/version ambiguity offer Resolve XMP choices.
The API delegates confirmation to `metadata_choices` and `metadata_decisions` through
`--import-choice` under the engine lock. Source-root/photo binding, immutable captures,
retained valid sidecars, candidate eligibility, stale tokens and request replay are checked.
All candidates must be indexed and still Pending. Users choose one or more owners;
competing owned XMP versions show recorded fields and effective differences before saving.
This does not expose arbitrary primary switching or incoming duplicate/Rejects decisions.

Saving changes only catalog decisions. It does not refile, edit, delete or imply a
successful import. Normal Copy/Move recaptures and verifies the source before applying
choices. An ownership reindex can clear that observed hold; competing-version observations
may remain visible until import, with the saved choice shown explicitly. Repair issues
cannot be bypassed. The dialog preserves drafts across desktop/narrow layout changes.
