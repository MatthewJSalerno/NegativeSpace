# Workflow Review Closeout

Scope: reconcile the agreed user workflows with the component specifications.
This is a documentation review, not an engine audit or implementation approval.

## Remaining user-workflow decisions

**0 confirmed unresolved decisions within this review's scope.** No additional
feature or edge-case discussion is required to close this round. This is not a
claim that implementation cannot expose further questions. Add a new question only
when a concrete conflict or missing behavior is demonstrated against these specs.

## Consolidated requirements

The component specs cover startup and storage errors; Index/Copy/Move previews,
selection and outcomes; progress, cancellation and reconnection; photo inspection,
similarity, rename, deletion and metadata editing; original snapshots and full
lineage; settings behavior; and catalog backup/retention/manual recovery.

Unavailable selected photos remain visible with a reason and must be removed before
confirmation. Previously agreed filename search and folder-grouped, downloadable
Move/Copy plans are included in the web spec. Old suggestions of hash-only lineage
or a second history database are rejected alternatives, not pending user decisions.
Earlier private working notes may contain superseded proposals; the component specs
and later explicit decisions govern implementation.

## Deferred technical work

1. **Settings write ownership:** deliberately parked. One database, saves allowed
   during jobs, and immutable job-start configuration are agreed; writer coordination
   is not yet selected.
2. **Lineage and persistence schema:** stable file identity, original snapshots,
   hash transitions, batch membership, recovery provenance and retained deletion
   records. Preserve the single-database requirement.
3. **API and job contracts:** request-to-action association, measured progress and
   exclusion counts, cancellation, reconnect status, reliable startup reconciliation
   and server-side enforcement of the no-queue rule. A successful Index must count
   indexed outcomes, not only transfer successes.
4. **Safe file and metadata operations:** supported-tag validation, date-only support,
   staged writes/readback/publication, integrity checks and partial-failure handling.
   Verify the limitations of perceptual-hash checks; they are not proof of exact
   pixel equality. No expansion to arbitrary image formats is required.
5. **Backup and cache implementation:** consistent snapshots, durable backup outcome
   tracking, mount-separation checks, thumbnail generation/diagnostics and cleanup.
   Compression is Zstandard level 10, chosen by measurement (`webui-spec.md` §9).
6. **Implementation verification:** map the agreed requirements to code and tests,
   including pending capture-date-only routing and Index-time fallback preservation.
   Existing durability and pre-release schema-version work remains in `TODO.md`.

These are implementation workstreams, not six more user-workflow questions. Do not
reopen approved behavior while choosing their technical representation.
