# Database foundation implementation

This is the first implementation increment toward the engine readiness design.
The engine owns schema initialization through `ns_db.py`; a future API can use
its scoped settings functions. The web UI is not implemented.

- Explicit initialization creates a versioned catalog (currently version 3). Existing unversioned
  catalogs are rejected without migration or replacement; preserve them and use
  a fresh development catalog for this increment.
- Connections enforce foreign keys and bounded lock waits. Shared transactions
  roll back on failure; settings updates require matching revisions.
- Settings currently cover workers and extensions. Each accepted CLI run stores
  its effective configuration: defaults, then saved settings, then CLI overrides.
  Later settings changes do not alter that snapshot.
- The database acceptance helper associates a request ID with one run and rejects
  reuse with different input. CLI/API request-ID wiring remains future work.
- Index records an immutable source snapshot for each file identity, including
  duplicates, with subsequent observations stored separately. Unknown filesystem
  dates remain null; Unix ctime is not presented as creation time.
- A source returning after a completed Move or duplicate removal receives a new
  identity. Operation links retain the previous identity and original evidence.

The existing transfer tables remain as an adapter. Successful deliveries now record
destination Copy identities, Move location changes and retained-copy relationships
atomically with outcomes. Copy origins are immutable, deleted sources retain history,
and previously unrecorded destination origins remain unknown. Skipped operations
may link a catalogued retained copy without claiming new verification.

**Recovery evidence landed in schema version 3.** Durable intent precedes every
mutation, reconciliation records what it observed rather than inferring from a
path's existence, an interrupted Move leaving two copies is recorded incomplete
with the published file given its own identity, and an outcome that cannot be
established opens an attention issue instead of resetting the row. A file under
an unresolved issue cannot authorize deleting a duplicate source.

**One defect worth recording, because the tests did not find it.** Recovery
registering an already-recorded destination superseded that identity and created
a duplicate for the same bytes. `record_delivery` reads a fresh publication as
proof the previous occupant is absent, which holds for a re-publication and not
for recovery, which publishes nothing. The synthetic suite stayed green
throughout; it surfaced only by building the state against real delivered files
and reading the identity rows rather than the summary counts. The rule is now
pinned from both sides in the contract suite.

Version 3 also defines the tables later steps need, batched deliberately so the
catalog stops being rebuilt once per increment. The scan writes `contents` and
`thumbnail_cache`; `content_similarity`, `backup_attempts`, `backup_artifacts` and
`file_changes` are defined but not yet written.

The `Undated/<year>` fallback reads the original Index modification time recorded
here, not the file's current one.

This does **not** complete the normalized schema: content-version transitions and
transfer-wide revision enforcement remain to be implemented. Backups, detail
previews, manual edits and web job control are also subsequent work.

Validation: the database contract suite covers concurrent settings saves,
duplicate request acceptance, rollback, stale revisions, configuration snapshots,
and immutable source evidence. Engine integration tests cover duplicate snapshots,
rescans, reimport after Move, and actual CLI configuration snapshots. Both use
synthetic temporary libraries; each increment is also validated against the
maintainer's real library before merge.
