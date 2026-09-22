# Database foundation implementation

This is the first implementation increment toward the engine readiness design.
The engine owns schema initialization through `ns_db.py`; a future API can use
its scoped settings functions. The web UI is not implemented.

- Explicit initialization creates a versioned catalog (currently version 2). Existing unversioned
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

This does **not** complete the normalized schema: content-version transitions,
complete recovery provenance, and transfer-wide revision enforcement remain to
be implemented. Failed or interrupted deliveries await the recovery-evidence step;
they are not presented as successful destination lineage. Original Index timestamps are captured here; switching date
routing to use them belongs to the transfer adaptation step. Backups, previews,
manual edits, thumbnails, and web job control are also subsequent work.

Validation: 15 database contract tests passed, covering concurrent settings saves,
duplicate request acceptance, rollback, stale revisions, configuration snapshots,
and immutable source evidence. The container engine suite passed 72 tests with
one genuine-RAW fixture skip. New integration tests cover duplicate snapshots,
rescans, reimport after Move, and actual CLI configuration snapshots. Tests use
synthetic temporary libraries; user-library validation is still required before
merge.
