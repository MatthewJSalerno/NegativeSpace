# TODO

Open work, open design questions and the durability claims ledger. Designs live in
`docs/`; features specified but not yet built are listed in
[project-spec.md](docs/project-spec.md) §4 ("Specified but not yet on screen").

## "Couldn't confirm what happened" issues are invisible and never clear

- [ ] **Found 2026-10-05; rare, but a dead end.** When recovery cannot establish what
  happened to a photo (an interrupted or failed Move, Rename, Reject or Return whose files
  cannot be verified; `engine-spec.md` §4.2 and §9.4), it records the evidence and opens an
  `unestablished_outcome` attention issue. Three gaps remain:
  - **Invisible:** the screens show only the empty-source and network-share issues; a
    per-photo issue appears in no panel, log view or count.
  - **Never clears once recovery gives up:** an issue resolves only when a later recovery
    verifies the outcome; one settled as unestablished is never looked at again.
  - **Silently blocks:** under claim 15 such a library copy never authorizes removing a
    duplicate's original.

  Planned fix: a Needs review note, "Couldn't confirm what happened to this photo", held,
  showing its evidence, with **Check it now**: a destination check of that file whose
  verified result clears the issue (`docs/webui-spec.md` §7.9).

## Copy, then delete the originals yourself

- [ ] A Copied photo whose original was deleted outside NegativeSpace is not recorded: a
  full Index checks for missing originals only among photos not yet copied. It should read
  as normal ("original removed outside NegativeSpace; the copy is in the library"),
  recorded in the photo's history, never as a failure, and drop out of Move's count and
  Stats' "A Move would free" (`docs/engine-spec.md` §4.2). Copy-only users depend on it.

## Names

- [ ] "Also arrived as" in the photo panel: the other names and folders of identical
  copies, each with Use this name, plus Rename… and a Has other names filter; the engine's
  rename and candidate list already exist (`docs/webui-spec.md` §7.3).

## One screen per job

Found 2026-10-05 looking for screens that do the same job twice.

- [ ] **Merge the two "Reject?" dialogs into one** (decided 2026-10-05,
  `docs/ui-design.md`, "Rejecting while comparing"): the general confirmation
  (`Confirm.tsx`) and the comparison's own (`RejectConfirm.tsx`) become a single dialog,
  with "Don't ask again while comparing" and the last-photo warning appearing only where
  they apply. Every later reject question uses it.
- [ ] **Remove Explore reference sets** (decided 2026-10-05), leaving no trace: the window
  (`ReferenceSets.tsx`), the Explore related sets button on set cards, its API route
  (`/similar/{id}/sets`), its tests and its spec and API-spec text. The comparison covers it:
  ‹ › steps through a photo's look-alikes and **Use as reference** walks into a neighbouring
  set. Only the combined view of several overlapping sets goes; if it is ever missed, it
  returns as a section of the Similar photos tab, not a window.
- [ ] **Needs review mockup** (on hold): boards in the design canvas; its two-photo note
  reuses the comparison workspace, which gains the "Will be rejected" marking.

## Views

- [ ] **Same-named photos look identical on a card:** a card shows only the filename, so two
  different photos named alike (in different source folders) read as one photo in two
  places. Show the source folder on hover, or beside the name when the view holds both.

- [ ] **"A job is already running" just after a job finishes:** the engine keeps its lock
  while it takes the catalog backup that follows a settled run, so a start in that moment
  is refused with no running job shown. Say what is happening ("finishing the last job's
  catalog backup") and offer to start when it is done, or wait briefly before refusing.

- [ ] Views named by where a photo is: Library (default), To organize, Rejects, Needs
  review; Has similar photos, Suspicious dates and No capture date become filters within a
  place; All photos goes (`docs/webui-spec.md` §2).

## Needs review

- [ ] The in-tray itself (`docs/webui-spec.md` §7.9).
- [ ] "Looks like a reject": a photo only similar to a reject (small pHash distance) is
  never rejected automatically; it waits in Needs review. With the reject still in
  Rejects: full side by side, Reject it too · Keep it · Keep the old one instead. With
  the reject emptied: its stored thumbnail and details (`docs/webui-spec.md` §7.8).
- [ ] "No capture date": suggested dates from the name, the folder or a dated look-alike,
  answered in bulk through the editor; the photo stays under `Undated/` meanwhile
  (`docs/webui-spec.md` §3.1).
- [ ] "Review later": a button beside Reject… in the photo panel, with an optional short
  note; Done clears it (`docs/webui-spec.md` §7.9).
- [ ] "Small image": photos under a size set in Settings wait outside the library for Keep
  or Reject, a larger look-alike shown beside them (`docs/webui-spec.md` §7.9).
- [ ] "Which photo is this sidecar for?": a short-named XMP sidecar that could belong to
  several photos, held with them until the user answers (`docs/engine-spec.md` §9.6).

## Similar photos

- [ ] Selected-photo gallery discoverability and grouped-set behavior. Show only
  selected already exists; discuss before adding another control.
- [ ] Broader relationships between overlapping sets beyond the current explicit
  one-hop exploration. Do not infer transitive matches.
- [ ] Assess finding rotated matches that the current pHash search misses. Rotating a
  preview helps a person compare but does not change retrieval or scores.
- [ ] Follow the [large-library measurement plan](docs/large-library-performance.md):
  query performance at 250k/500k, dense and overlapping sets, memory, invalidated caches
  and response times. Repeat A/B runs before claiming supported capacity. Original-file
  processing, comparison build costs and long-session browser work remain separate;
  filesystem latency is not benchmarked. The 75% floor is the chosen range. Measure a
  concrete bottleneck before proposing another database.

## Dates and metadata

- [ ] Read XMP sidecars at Index (always on); the sidecar's value wins per field, both
  kept, each shown with its source; sidecars travel with their photos through Copy, Move,
  Reject and Return. Today they are neither read nor carried (`docs/engine-spec.md` §9.6).

- [ ] Extend date review to malformed/raw EXIF fields, conflicting capture tags,
  configurable bounds and dismissing known-valid dates if users need these. Current
  flags inspect only the recorded gallery date.
- [ ] EXIF editing and copying details between photos, with explicit targets, previews
  and per-file history (`docs/webui-spec.md` §7.5, `docs/engine-spec.md` §9.6). The
  reference, donor and targets are distinct roles, never inferred from navigation or
  checkboxes. Edits go in the file or an XMP sidecar by format (decided 2026-10-02,
  §9.6): sidecars move with their photos and are part of its lineage.
- [ ] Saved orientation edits, separate from temporary viewing rotation: one
  end-of-review decision for photos still rotated, in the comparison and the photo
  panel, and the selection bar's Rotate… for a selection; no control on thumbnails
  (`docs/webui-spec.md` §7.5). Built on the verified Orientation write; no save promise
  before that works.

## Stats

- [ ] The thumbnail cache panel in Settings › Performance (Free up previews, Repair grid
  thumbnails, Rebuild all), with API routes for the existing engine jobs, and a Manage
  thumbnails link from Stats (`docs/webui-spec.md` §4.2.1).
- [ ] The Dates chart on its own full-width row, with suspicious years set apart at each
  end, so a few impossible dates cannot squash it (`docs/webui-spec.md` §5.9).

## Warnings that need a way out

- [ ] An import-completion summary and a catalog-wide filter for files whose visual
  processing failed, distinguishing corrupt data from missing decoder support and IO
  failures; absent EXIF is not proof of damage. Do not retry unchanged bad files.
- [ ] Audit warnings throughout the app for a working action or a direct route to the
  affected items ([validation and feedback contract](docs/ui-design.md#validation-and-feedback)).

## Durability claims: stated vs enforced

Every durability claim resolves to either **enforced and tested** or **a documented limitation** — never something the prose asserts and the code only usually does. **A claim that cannot be enforced is raised with the maintainer before it is weakened:** weakening a guarantee is his decision, not an editorial fix. Until he decides, mark it **Unresolved** here with what fails and why.

| # | Claim | Stated in | Status |
| :--- | :--- | :--- | :--- |
| 1 | A source is deleted only after its copy's **bytes** are fsynced | `engine-spec.md` §4.2, §7 | **Enforced**, tested (`durability barriers precede source deletion`) |
| 2 | …and after the copy's **own directory entry** is fsynced | `engine-spec.md` §4.2 | **Enforced**, tested |
| 3 | …and after **every ancestor entry from `--dest` down**, retried until it succeeds | `engine-spec.md` §4.2 | **Enforced at the deletion gate**, for all three deletion callers, tested (`a failed ancestor sync is retried not forgotten`, `the already present deletion establishes the ancestor barrier`, `duplicate cleanup establishes the ancestor barrier`) |
| 4 | The chain walk never touches anything **above** `--dest` | this file | **Enforced**, tested (`the durability chain never reaches above the destination`) |
| 5 | The source is unchanged since it was verified | `engine-spec.md` §4.2 | **Enforced**, tested (`a source edited after verification is kept`) |
| 6 | The copy is a different file from the source | `engine-spec.md` §4.2 | **Enforced**, tested (`a source is never deleted as its own copy`) |
| 7 | `mtime` is preserved by a copy | `engine-spec.md` §9.2 | **Enforced**, tested (`a delivered copy keeps its source mtime exactly`) — to the nanosecond, for Copy and Move, with undated and dated photos |
| 8 | The documented repair for a destination file removed outside the engine — re-index with `--force-rehash`, then Copy — actually re-delivers it | `Skipped` reason string, `webui-spec.md` §5.3 | **Enforced**, tested (`the documented recovery redelivers a removed destination file`) |
| 9 | A filesystem that cannot fsync directories **says so at runtime**, rather than leaving the weaker guarantee to be inferred from this document | `engine-spec.md` §4.2 | **Enforced**, tested (`an unsupported directory fsync is reported once per run`). Once per run, naming the first such directory — once per directory would be a line per date folder. |
| 10 | The move/copy loop **commits its intent marker at `synchronous=FULL`**, so `status=Processing` with `dest_path` is fsynced before the source is unlinked | `get_db_connection`, `engine-spec.md` §5 | **Enforced**, tested (`the move loop commits at full synchronous`). Scoped to that one connection — the scan path keeps `NORMAL`; measured 1.42x on the move path (+1.9 ms/photo) against the ~4.4x `NORMAL` buys on the scan path. **The claim stops at the fsync:** whether a real power cut preserves it depends on the storage honouring it, which is untested (see the power-loss item below). **If the marker is lost anyway, the next run still records the truth**, tested (`a move whose catalog commits were lost is recorded as found`): a photo or duplicate whose source is gone and whose exact content is on the destination is recorded `Found_At_Destination` from that evidence, never `Failed` and never as an action it did not take. An entirely empty source folder is asked about rather than guessed at (`an empty source asks before anything is recorded`; engine-spec §4.2). |
| 11 | **Complete lineage is reconstructable for every catalogued file, in every settled status** — original Index snapshot, current state, creation origin, and every operation it took part in | `webui-spec.md` §6.3, `engine-spec.md` §10 | **Enforced**, tested (`every_catalogued_file_assembles_complete_lineage`). Four catalogs, because one cannot hold every status at rest: a run ending in Move leaves `Completed`/`Failed`/`Removed_Duplicate`; one ending in a targeted Copy leaves `Pending`/`Copied`/`Duplicate`; lost catalog commits leave `Found_At_Destination`; rejecting after a Move and after a Copy, then emptying Rejects, leaves `Rejected`/`Rejected_Copied`/`Rejected_Emptied`. The test asserts the required set is covered, so a NEW status that nothing verifies fails it. The guard also rejects settled source removals still recorded as present and successful transfer intents with no destination participant. Interrupted-Move tests cover verified fresh delivery, reuse of an existing copy, duplicate removal, unverified destinations and atomic rollback of a failed lineage repair. **One documented exception:** a destination the engine found rather than created has no source snapshot, because no Index ever saw it; it is recorded as `observed_destination` with a NULL origin rather than given a fabricated one. Verified against a real-library catalog of 971 identities at 0.02–0.08 ms per history. |
| 12 | **A settled run's whole history is fsynced when it settles**, including scan results and audit rows the scan path committed at `NORMAL` | `finish_run`, `engine-spec.md` §5 | **Enforced**, tested (`a settled run fsyncs the history its scan committed at normal`). In WAL mode a `FULL` commit fsyncs the WAL file, which covers every earlier `NORMAL` commit in it: one history-settle fsync per run (a dirty count-cache rebuild adds its own commit). **Why not `FULL` on the scan path:** it pays the ~4.4x on every batch to protect rows a re-Index reproduces. Backup attempts record their outcome at `FULL` too. **Scope:** a run killed before it settles is not covered — its last `NORMAL` batch can be lost to a power cut, it is recorded `Interrupted`, and a re-Index reproduces the scan rows; a database writer that misses its 60 s shutdown deadline can commit after the settle. Like claim 10, the claim stops at the fsync. **If a power cut takes a run's scan rows anyway, the next Index re-creates them identically**, tested (`scan rows lost with their commits are recreated by the next index`). |
| 13 | Startup reconciliation commits at `synchronous=FULL` | `reconcile_interrupted_state` | **Enforced**, tested (`startup reconciliation commits at full synchronous`). Recovery records evidence and attention state — conclusions from observations that may not be repeatable, because storage disappears and files are replaced between runs. A lost repair would discard the only record that an outcome could not be established. It runs once per interrupted row at startup, so the cost is negligible. |
| 14 | A Move never deletes a source on the strength of an fsync a network share may acknowledge early | `--confirm-network-destination`, `engine-spec.md` §4.1 | **Enforced**, tested (`a move to a network share asks before anything is deleted`, `the destination filesystem is read from the mount table`). A client cannot see how a share is exported — an `async` NFS export acknowledges an `fsync` before the data is on disk — so the engine does not try to. It reads the destination's filesystem type from the mount table and, for a network filesystem, stops a Move before copying or deleting anything: a needs-attention issue recommends Copy (which never deletes, so it is the one way to guarantee no loss) and the user chooses Copy instead, Move anyway after confirming the share is exported `sync`, or neither. Copy is never stopped. **Residual, by the maintainer's decision:** a confirmed Move is only as durable as the share's honesty about `fsync`, and a mount table that cannot be read is treated as local. |
| 15 | A destination file with an unresolved needs-attention issue never authorizes deleting a duplicate source | `ns_db.paths_needing_attention`, `engine-spec.md` §4.2 | **Enforced**, tested (`a_copy_needing_attention_never_authorizes_removing_a_duplicate`, and the database tests for the lookup). Move's duplicate cleanup drops such copies from its candidates before verifying bytes; with none left the source stays, recorded `Skipped` with the reason, and the next Move after the issue is resolved removes it. A matching SHA-1 alone is not enough, because recovery could not establish what is at that path. |

### Outstanding

- [ ] **Power-loss behaviour is reasoned about, not tested.** Every durability test asserts *which* fsyncs happen and in what order, not that a real power cut preserves the tree. The question splits in two. **Consequence** — "given this loss, does the engine do the right thing?" — is testable without hardware: construct the state a power cut leaves behind (for example, take a completed move and rewind the catalog behind it while the filesystem keeps what it did) and test what the next run concludes. Claims 10 and 12 now have such tests. Every future durability claim needs one too. **Mechanism** — "does `NORMAL` really lose that commit on this hardware?" — needs `dm-log-writes` or device-mapper `flakey` in a VM, or a statement that it is untested and why.

- [ ] **Re-audit these claims whenever the write path changes.** Defects in this path come from fixes to the path itself — a barrier added in one deletion caller and missing from another. A change to `copy_verify_delete`, `_mkdir_durable`, `_finalize_partial` or `_remove_verified_source` ends with this table re-checked rather than assumed.

## Before the first release

- [ ] **Review every message the user sees**, once the screens are settled: a private
  document listing each message's text with where it appears and the scenario that shows
  it (screen, condition), drawn from the screens, the API's error messages and the
  engine's reasons that reach the page, so the maintainer can read them all in one place.

- [ ] **Version 1.0.0 and the changelog:** keep [CHANGELOG.md](CHANGELOG.md) current as each
  change merges; 1.0.0 is the first release ([Semantic Versioning](https://semver.org/)).
- [ ] **Say what it runs on:** a minimum Linux and Docker version in the README, and that
  Mac and Windows are not tested.

- [ ] **One password for the web interface** (`docs/webui-spec.md` §11): generated on first
  start and printed to the container output, changeable in Settings. Until then the README
  tells users to keep the app off the internet.

- [ ] **Decide on catalog migration.** `engine/ns_db.py` stamps `catalog_schema.version` and refuses any catalog whose version it does not recognise. While every catalog is a development catalog, refusal plus a fresh Index is enough; that stops being acceptable once a user holds history that cannot be recreated.

## Later

- [ ] **Reports**, not designed yet. A first candidate: a checksum list (`sha1sum` format)
  of the library, and of the source, so a user who copies and then deletes originals
  themselves can verify every copy with standard tools, independently of NegativeSpace.

## Other

Deferred performance and robustness work — a stalled worker having no deadline, the unchanged-file check loading every settled row, batch barriers at submission tails — lives in `engine-spec.md` §8 with the condition that should bring each one back. This file tracks claims that need enforcing; that section tracks work deliberately postponed.
