# Functional & Technical Design Specification: NegativeSpace Phase 3 — Fuzzy Matching & EXIF Editing

## 1. Scope

Phase 3 covers near-duplicate (visually similar, not byte-identical) detection and grouping, plus EXIF metadata editing/synchronization across related images. This content was originally drafted as part of `phase2-spec.md` §4.3 and was moved here since Phase 2's scope is explicitly the web UI for existing Move/Copy/Index operations — fuzzy matching is a separate body of work with its own data-model and UX implications, not a natural fit alongside Phase 2's file-selection/job-management focus.

Phase 1 already generates and stores a pHash (`phash` column on `photos`) for every file — that work is done and is a prerequisite for everything below. What's *not* built yet is anything that acts on those hashes: comparing them to each other, grouping visually similar images, or surfacing that grouping in the UI.

## 2. Match Mode Switcher (Exact vs. Fuzzy)

The top header provides a Match Mode toggle:
* **Exact SHA-1 (Default):** 100% byte-for-byte checksum matching for operations — this is what Phase 1/2 already implement.
* **Fuzzy Match (pHash):** Perceptual hash visual similarity grouping based on Hamming distance thresholds. Displays similarity percentage scores in the inspector. Groundwork for the EXIF editing capabilities below.

## 3. Destination Inventory and Duplicate Reporting

The destination is normally NegativeSpace's exclusively. Deduplication happens at Index time by SHA-1 — among files with identical content one row is `Pending` and the rest are `Duplicate`, and only `Pending` rows are ever written — so a destination the engine owns is meant to hold one copy of each distinct content. That is the invariant the engine is built to keep, not something it proves: a selection or delivery bug can break it, and so can anything outside the engine that writes to the destination. The inventory below is how the user finds out either way.

**The engine must keep its invariant: nothing under `--dest` changes on the engine's own initiative.** Every modification or removal of an existing destination file is the direct result of the user explicitly asking for that specific thing. The automatic operations — Index, Copy, Move — only ever *add* files there; they never touch one that already exists. Curation (§3.4) does modify the destination, but only per deliberate act, recorded, and recoverable. That property is why `--copy` is trivially safe, and why the worst case of a bug in the move loop is a lost source file that still exists at the destination. Deduplicating in place would trade it away permanently, giving the engine the ability to delete from the copy the user has designated canonical, on the strength of a hash comparison. Every future bug in that path would eat the good tree.

Phase 3 therefore **reports** destination duplicates rather than resolving them. A read-only inventory pass records each destination file's current SHA-1 and location; the UI groups by hash and shows what is redundant. The same view that groups by `phash` for near-duplicates groups by `sha1_hash` for exact ones — one query shape, two columns. The user acts on the result with their own tools, or by re-processing (below). No deletion path into `--dest` is added.

### 3.1 Re-processing a Disordered Destination

When a destination has been reorganized or polluted from outside, the supported repair needs no new engine capability: point `--source` at the old destination, `--dest` at a fresh location, and run `--move`. Index deduplicates by content, only anchors are written, and duplicate cleanup removes the redundant copies from what is now the source. **Costs to surface in the UI before offering this.**

Space: the pre-flight check requires free space at the new destination for the whole pending payload — every distinct file — plus a 500 MB margin, before anything is copied. Deleting from the old destination frees space only on *its* filesystem, so when the two are on different filesystems the new destination needs room for the entire de-duplicated library. Even on one filesystem, the check asks for the full amount up front.

Photo IDs and run history do not survive it — see §3.2.

More subtly, **files dated from modification time depend on that time surviving.** A photo with no usable EXIF date was filed under its mtime. The engine preserves mtime when it copies (verified: destination and source mtimes are identical), so re-indexing a destination the engine wrote files those photos in the same place again — provided nothing touched them in between and the timezone is the same. Two things break that: a tool that rewrote or re-copied the old destination without preserving times, which leaves the date of that operation as the new mtime, and a different `TZ`, which can move a file across a day boundary. Files carrying a real EXIF date are unaffected. The UI must say this before starting and show both the count — directly available as `date_source = 'file_mtime'` in `metadata_json` — and the timezone in effect.

This is a strong argument for reporting over re-processing on a library that is already organized: reporting costs nothing and moves nothing.

### 3.2 Open Question: Content-Addressed History

`photos.id` is the engine's identity for a file, and `operations.photo_id` hangs off it. Rebuilding the catalog — the documented remedy for a schema change, and the outcome of the re-processing above — issues new IDs, orphaning every historical row. This is in tension with the project's stated position that the catalog is a derived artifact that can be deleted and rebuilt: `photos` genuinely is derived, but `runs` and `operations` are not. They are the only record of what the engine did, and nothing recomputes them.

The sharpest case is `Removed_Duplicate`. After a `--move`, that row is the only evidence a file ever existed: the source is gone by design and the content survives only under the anchor's name. Delete the catalog and the knowledge that it existed goes with it.

Keying history on `sha1_hash` rather than `photos.id` would let it survive a rebuild, since content identity is stable across renames, moves, re-processing and new catalogs. Three problems have to be answered first:

* **Failed files have no hash.** A file that could not be read produces `sha1_hash = ''` — and failures are precisely the history worth keeping. A content key cannot cover them; they need `source_path` as a fallback identity, which is itself unstable.
* **Content identity is not file identity.** Two distinct files with identical bytes share one hash. History keyed on content becomes "everything that happened to this content," spanning several original paths. That is arguably more correct, but it is a different question from "what happened to this file," and the UI would have to say which one it is answering.
* **Editing content breaks the chain.** The EXIF editing in §5 rewrites files, changing their hashes. A content-addressed history would need to record that hash *A* became hash *B*, or it loses everything before the edit — a rename-tracking problem in a different costume.

Worth considering alongside: whether `runs` and `operations` belong in the rebuildable catalog at all, or in a separate store that is never discarded. That would remove the tension directly rather than working around it, at the cost of a second database file and cross-file joins the API layer would have to do itself.

**This question has a deadline, and it is earlier than Phase 3.** `phase2-spec.md` §5.3 (Error Center) and §5.4 (Operations Audit Log) are both specified directly on `operations`, joined through `photo_id`. Once that UI exists, changing how history is keyed stops being a schema decision and becomes a migration plus a rework of two views. **Answer it before the Error Center is built, not before Phase 2 starts** — the spec work itself is unaffected, and deferring the answer costs nothing until code is written against those tables. Recorded here rather than in `phase2-spec.md` because the alternatives belong with the rest of the history design, but the timing constraint is Phase 2's.

### 3.3 Idea: Choosing a Filename from a Duplicate Group

When duplicates are removed, the surviving copy keeps its own filename — which may be the least descriptive name in its group. A camera-style `20051001.JPG` can survive while the duplicate removed against it was named something like `birthday_party.jpg`. Offer a way to rename a delivered file at the destination to the name any member of its duplicate group once had.

* **The data already exists.** Every source path in a group is recorded and kept after a move or duplicate removal: `photos.source_path` on the `Duplicate`/`Removed_Duplicate` rows, and `operations.source_path` for every attempt, grouped by `sha1_hash`. No new capture is needed — provided the catalog is kept, since it is the only record of those names once the sources are gone (see §3.2).
* **User-chosen, never automatic.** Which name is more meaningful is a judgement; the UI offers the group's names as candidates and the user picks.
* **Keep the file's real extension.** Use the chosen name's stem with the delivered file's actual extension, so a rename never mislabels a file's format.
* **This is a new kind of destination write.** Every *automatic* operation only adds files under `--dest`; this changes an existing one, and so may happen only on an explicit user request for that file. It must be no-overwrite (link-then-unlink, or a no-replace rename) with the same `_N` suffix rule on a collision; it must update `photos.dest_path`; and it must record an operation carrying both the old and new path, so a photo's history still leads to where it is now. Removing the old *name* does not remove content, so the invariant that nothing under `--dest` is deleted still holds.

### 3.4 Curating the Destination: Three Capabilities, Three Risk Profiles

Choosing which copy of a photo survives is not one feature. It is three, and they are listed here in increasing order of danger so they can be built and reasoned about separately, whatever the UI eventually presents as a single screen.

**1. Rename a delivered file** (§3.3). The safe one. Every member of an exact-duplicate group is byte-identical, so "which to keep" is meaningless for content — only the name differs. A rename destroys nothing, is reversible from the recorded operation, and the file is correct whatever it is called. This needs no new safety machinery and could ship on the existing catalog: the candidate names are already recorded.

**2. Supersede a delivered file.** Choosing between files that differ — a JPEG versus the DNG it came from, a thumbnail versus its original — means one file leaves the library. This is where the original invariant ("nothing under `--dest` is ever deleted") stops being literally true, and it must not simply become false.

**The rule, decided 2026-09-20: a superseded file is deleted, and the deletion is recorded.** No quarantine area. The user asked for that file to go; the engine removes it and writes an operation carrying its path, size, hash and the reason, so the record of what was there survives even though the bytes do not.

*An earlier draft specified a `.superseded/` quarantine mirroring the original path, emptied only by a separate explicit act.* The argument for it was that a decision made carelessly at 2am should be recoverable. That was rejected on two grounds, both the maintainer's. **Quarantine does not buy reversibility where it matters** — it defers a deletion the user already chose, and the user who empties it carelessly at 2am is the same user. **And the protection it offers is available upstream, with no engine complexity**: a user worried about losing destination files can mount the source `:ro` and keep it, which protects the pixels themselves rather than a copy of them.

What the engine owes the user is not a second chance at the same decision but **the information to make it well and to understand it afterwards**: what the file was, where it came from, what replaced it, and what else shared its content. A deletion that is fully recorded is a deletion the user can reason about. One that is merely deferred is a decision made twice.

**Say plainly what this costs.** By the time curation happens the sources are typically gone, so the destination copy may be the only copy in existence — and this capability can therefore destroy the last copy of a photograph. That is why it sits second in this list rather than first, and why it must require explicit consent. We cannot recover pixels; we can refuse to remove them quietly.

**Bulk selection needs its own confirmation, and the count is the point.** The UI should offer a select-all over a group — reviewing several hundred near-identical files one at a time is the kind of tedium that makes people stop reviewing — but a select-all must never act directly. It raises a confirmation that **states the number of files and what will happen to them**, and it must be cancellable:

> *Delete 400 photos? This cannot be undone. If you do not have a backup of these photos, this will lead to data loss.*

The count carries the warning. "Are you sure?" is noise a user learns to dismiss; "400 photos" is the thing that stops someone who meant to select four. State the number, name the consequence, and let Cancel be the easy path.

**3. Write metadata into files.** Correcting or merging EXIF — persisting the good copy's date onto the survivor, or filling in a date the file never had. This is the only capability that mutates file *contents*, and the scope boundary in `project-spec.md` §1 is what makes it eventually unavoidable: a consuming gallery reads EXIF from the file, so a correction that lives only in this project's catalog is a correction the gallery never sees.

**Open: sidecars versus in-file writes.** An XMP sidecar written beside the photo would give portability without ever modifying the original — the file stays byte-identical, its hash stays stable, and the catalog's verification story is untouched. This depends on the consuming application reading sidecars, which needs confirming rather than assuming. If it holds, this capability becomes dramatically cheaper and safer; if not, in-file writes need their own protocol for backup, verification and undo, and the engine's "never modify a photo" property is spent.

Note what capabilities 2 and 3 have in common: both act on the **destination**, the organized library, rather than on incoming sources. Phases 1 and 2 are about getting files in; this is about curating what is already there, and it is a different activity with a different safety story.

## 4. Open Design Questions for Phase 3

These weren't resolved in the original draft and need scoping before implementation:

* **Hamming distance threshold:** what similarity score counts as "a match" for grouping purposes? Likely needs to be user-adjustable rather than fixed, given pHash similarity is inherently fuzzy and different collections (bursts of near-identical shots vs. edited variants of one photo) may want different sensitivity.
* **`collision_group` / `is_master` semantics:** these columns already exist on `photos` (added in Phase 1, unused until now). Need to define: how is a `collision_group` ID assigned (on-demand when the UI requests clustering, or continuously during every Index)? Who/what decides `is_master` — first-discovered, highest-resolution, user-selected?
* **Merger tool UX:** the original Phase 1/2 spec drafts mention a "Merger" tool for resolving fuzzy-match groups, without detail. Needs its own design pass — likely: show the group, let the user pick a master, decide what happens to the others (delete? keep both? merge metadata?).
* **EXIF editing/synchronization:** "groundwork for future EXIF editing capabilities" was mentioned but not specified — does this mean editing a single file's metadata, or propagating metadata from a group's master to its near-duplicates? These are different features with different risk profiles (the latter mutates files that weren't directly selected by the user).

## 5. Dependencies on Phase 1/2

* Requires the `phash` values Phase 1 already computes — no new hashing work needed, just new logic that reads and compares existing values.
* Likely requires a new backend endpoint (e.g. `GET /api/v1/photos/similar/{id}?threshold=N`) computing Hamming distance across the `photos` table's `phash` column — this is a Node.js/API-layer concern, not a `ns-engine.py` engine change, unless clustering needs to happen at index time rather than on-demand.
* The Inspector panel (Phase 2 §4.2) already displays a file's own pHash — Phase 3 extends that panel with the similarity group/percentage data once clustering exists.
