# Audit 024 fixes — review brief — 2026-10-05

`026-gpt-review-brief.md` · **Status: Complete.** Review range:
`2050527..818bb42`; fixes committed at `818bb42` on
`docs/audit-024-current-contracts`, based on `ab2ffff`.

The previous audit examined release 0.14.0, schema 20, at `2050527`.
Local `main` remains there. Remote `origin/main` was `293cff1` when refreshed
for this brief; those newer commits are not integrated or validated by this branch.
This is a handoff for review, not a fresh audit or a claim that the fixes are merged.

## Scope and disposition

All eight original findings were confirmed and addressed; zero were dismissed.
The README and license changes between `2050527` and branch base `ab2ffff`
did not alter the audited implementations. The fixes are one commit,
`818bb42`. No PR was created or merged for this work.

| ID | Severity | Concern and fix | Main files |
| --- | --- | --- | --- |
| F1 | Major | Filesystem errors after Rename/Reject/Return retain recoverable intent, observed evidence and actionable uncertainty; recovery verifies the outcome and clears attention only when established. | `ns-engine.py`, `tests/engine_smoke_test.py` |
| F2 | Major | Relocation recovery verifies regular-file type, expected SHA-1 and stable paths before success or old-link removal; uncertain Return is not mistaken for emptied Rejects. | `ns-engine.py`, `tests/engine_smoke_test.py` |
| F3 | Major | Remove the obsolete 1,000-ID positioning cap while retaining ID validation; cover large selections and Inspector navigation. | `webui/app.py`, `tests/webui_api_test.py`, `tests/large_selection_browser_drive.py` |
| F4 | Minor | Malformed selection fixtures use separate files and assert the intended refusal reason, so earlier cases cannot be overwritten or masked. | `tests/database_test.py` |
| F5 | Major | A persistent selection lock coordinates startup cleanup and publication; descriptor inheritance protects unread input after the submitting API dies. | `webui/jobs.py`, `tests/selection_ownership_test.py`, `tests/selection_engine_fixture.py`, CI workflow |
| F6 | Major | Publication failures clean up only the file this attempt owns; API launch failures return structured errors and permit safe same-request retry. | `ns_db.py`, `webui/jobs.py`, database/API tests |
| F7 | Minor | Correct superseded deletion, metadata-editing and selection contracts without implementing planned features. | `docs/api-spec.md`, `docs/ui-design.md`, `docs/webui-spec.md` |
| F8 | Minor | Progress assertions handle unknown totals safely and reject snapshots that do not prove intermediate progress. | `tests/engine_smoke_test.py` |

Recovery behavior is documented in `docs/engine-spec.md` sections 9.4–9.5;
selection ownership and API errors in the web/API specifications.
`tests/README.md` describes the added focused suites and browser driver.

## Executed validation

Tests used Docker, separate audit image tags and generated fixtures only.
No real catalog, library or running application was changed.

| Check | Result | When |
| --- | --- | --- |
| Full engine smoke suite | 147 passed, 0 failed, 2 skipped | Final implementation, before commit |
| Catalog contracts | 49 passed | Final implementation, before commit |
| Web API | 81 passed | Final implementation, before commit |
| Cross-process selection ownership | 3 passed | Final implementation, before commit |
| Focused relocation suites | 9 passed; 33 F1 and 36 F2 scenarios | Final implementation |
| Large-selection browser driver | Passed with 1,230 selected photos and full-selection position requests returning 200 | Earlier F3 validation; not repeated after engine recovery fixes |
| Spec structure/references | 450 checked | Final specifications |
| API specification | 40 routes matched 40 endpoints | Final implementation |
| Whitespace/error check | `git diff --check` passed | Before commit |

The two smoke skips require genuine RAW camera files, which were not supplied.

### Evidence the regressions detect defects

- F1's initial two tests failed before the fix: lost recoverable intent and
  discarded fallback link. Three additional F1 tests are regression guards.
- F2's initial three tests failed before the fix: false attribution, uncertain
  old-link removal and missing hash evidence. A separate Return regression exposed
  the erroneous emptied-Rejects inference.
- F3's API regression failed with HTTP 422 at the former cap.
- F4's original test passed with checksum validation disabled. The corrected tests
  caught disabled checksum, count and ID guards in scratch mutations.
- F5 reproduced deletion of a live input across API processes. Removing inherited
  descriptor protection in a scratch mutation specifically failed after parent death.
- F6 reproduced leaked published input and unhandled launch/publication errors.
- F8 reproduced `TypeError` and detected a mutation accepting zero/completed counts.
- F7 is a documentation correction; no red executable test is claimed.

## Where review matters most

1. **Failed attempt versus terminal outcome.** F1 deliberately shows an attempt
   as Failed while retaining its intent without a terminal event. Recovery finds
   work by events, not by status. Check error handling, attention lifecycle and
   the subsequent catalog transaction together.
2. **Relocation evidence.** Review hash/type checks, path rechecks, both directory
   barriers, hard-link preservation and the rule excluding uncertain Return from
   emptied-Rejects inference.
3. **Selection ownership.** Check persistent-lock lifetime, inherited descriptors,
   cleanup after parent death and pre-spawn failure, active-input preservation,
   request replay and abandoned-input retry.
4. **Integration with newer main.** Remote-only design/specification changes may
   overlap this branch. Review the combined behavior after integrating them.

## Deliberate absences and remaining work

- No release-version or catalog-schema bump, catalog migration or history upgrade.
- No EXIF/XMP write implementation or destructive photo-deletion feature.
  Their absence follows this branch's specifications; newer remote design decisions
  must be reconciled during integration.
- The engine's internal `--file-ids` option remains supported. Web selected jobs
  use validated selection files. The existing 16 MiB proxy request-body limit remains.
- Selection locking coordinates participating implementations. Direct outside
  replacement of lock/input files is outside that protocol.
- Path rechecks do not make unrelated external filesystem writers atomic with
  unlink or catalog commit.
- No actual power-cut, network-transport-failure or genuine RAW testing was performed.
  Filesystem failures were injected around real operations.
- No full browser rerun or remote CI result is claimed for this final snapshot.
- All eight findings await reviewer acceptance and merge; they are not marked
  Resolved. Integrate newer main and rerun affected checks before landing.

The numbered local review record and review-log entry remain git-ignored under
the repository's review process. This sanitized copy is tracked for remote review.
