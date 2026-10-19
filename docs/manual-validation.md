# Manual validation

The single record for maintainer browser checks: pending work, accepted results and
historical walkthroughs. Automated suites, fixture builders and measured results stay
in [tests/README.md](../tests/README.md) and the research documents.

Jump to [pending checks](#pending-checks), [accepted sidebar/Stats checks](#sidebar-stats),
or the [historical topic index](#historical-checklists-and-accepted-results).

## Pending checks

**Sidebar and Bookmarks:** the maintainer passed [Tests SB1–SB6](#sidebar-bookmarks),
including all lettered steps. No manual checks remain for the tested behavior.
**SB5a needs a recheck:** a Check the date bookmark now shows its reason, note and
recorded dates first, with **Edit metadata date…** focused, instead of opening the editor.
RC1–RC3 remain accepted historical results.

After each maintainer report, update this queue and the batch's status; record partial
passes by step. A relevant behavior change must explicitly identify the steps needing
a retest. Do not infer manual acceptance from automated results.

## Maintainer validation rules

- Number tests and letter their steps so results can refer to a specific check.
  Refer to these identifiers (for example Test 3a), never document line numbers.
- For every photo-specific check, supply a searchable filename verified in the current
  test catalog, its location (for example Library or Not organized), the expected
  starting state and the expected result. Add a date or other identifier if names repeat.
- A source path or a description such as "an EXIF-primary photo" is not sufficient.
  If the required fixture is absent, say so and arrange it before asking for validation.
- State when a Settings-only check needs no photo. List only remaining checks; preserve
  accepted results unless a relevant change requires a specific retest.
- Keep private sample filenames in the direct validation message or private handoff;
  tracked checklists use generated fixture names and aggregate results.
- Add future manual steps and their results to this document, not separate feature
  checklists or tests/README.md. Other documents link to the relevant section.
- Preserve test IDs already used in maintainer reports. Older batches reused numbers;
  identify them by their topic below as well as the test/step. Use a unique batch prefix
  for new tests, such as RC1a, to avoid ambiguity.
- Keep accepted checks as history. Before requesting a historical check again, verify
  current labels, filenames, dates and starting state in the actual review instance,
  supply any missing fixture, and explicitly list only the requested steps.
- Old walkthroughs describe the build and fixture that were reviewed. Statements such
  as “not built”, “next”, “remaining” or “before merge” inside those archived instructions
  are historical scope, not the current backlog or permission to reset/run jobs.
  Use the component specs and [TODO.md](../TODO.md) for current feature status.

## Sidebar and Bookmarks

<a id="sidebar-bookmarks"></a>

**Accepted:** the maintainer passed SB1–SB6, including SB1a–c, SB2a–d, SB3a–c,
SB4a–d, SB5b–g and SB6a–c. **SB5a is pending a recheck:** it passed, but the
maintainer found that opening the date editor automatically hid the bookmark's reason,
so the date bookmark now shows the reason, note and recorded dates first and the editor
opens from **Edit metadata date…**.

The review instance was prepared with Index and Copy against the demo library and
additional generated scenarios. Starting state: 4,904 Library photos, 25 source files
needing attention, no Rejects, small-image reminders enabled below 800 pixels, and seven
prepared bookmarks. These are the original starting values; validation has used this
catalog, so reverify fixtures before any future retest.
Use the review address supplied with this checklist, and start at its base URL.

These generated filenames were verified in **Library**. Search the whole filename;
if a search also finds an identical source alias, open the card with the exact name.

| Filename | Starting date | Purpose / prepared bookmark |
| --- | --- | --- |
| `generated-005.jpg` | 2020-06-06 | Create your own bookmark; initially none |
| `generated-022.jpg` | 2019-11-23 | Small-image reminder; initially not reviewed |
| `generated-035.jpg` | 2023-12-08 | Check the date |
| `generated-053.jpg` | 2023-06-26 | Compare versions; four matches at 90% |
| `generated-026.jpg` | 2023-03-27 | Fix rotation |
| `generated-034.jpg` | 2022-11-07 | Check the details |
| `generated-043.jpg` | 2022-08-16 | Decide whether to keep it |
| `generated-052.jpg` | 2022-05-25 | Ask someone |
| `generated-033.jpg` | 2021-10-06 | Other |

### Test SB1 — Places and navigation

**a.** Choose **Library**. The sidebar should contain Not organized, Source folders,
Library, Similar photos and Rejects. Activity, Logs and Stats should sit at the bottom
of the sidebar above the version, separated from the photo places. There should be no Look into
section, pins or separate Needs review place. The notes under Not organized and Library
should link to the affected files.

**b.** Search `generated-005.jpg`. Choose **Similar photos**: search should clear and
similarity controls should appear. Use browser **Back**: the Library search should return.
Choose **Library** again: search and optional refinements should clear.

**c.** Open Logs, then Stats. The sidebar should keep its places and whole-place counts.
Use **to review** under Library: it should open the complete review list, without keeping
an unrelated search or filter.

### Test SB2 — Combined refinements and reasons

**a.** In Library, select **Odd dates**, then **No date**. Both should remain selected;
results must satisfy both. Empty results are valid. Counts should reflect the combination,
while the sidebar's Library total stays unchanged. Turn either off, then use
**Clear all filters**.

**b.** Select **Needs review**. Its **Reason** selector should offer All, Small and
Bookmarked; Needs verification should be absent while none exist. Choose Bookmarked:
the seven prepared cards should show their reasons and notes, sorted in preset order.
Switch to Small and back: only one Reason should be active at a time.

**c.** In **Similar photos**, turn on Needs review. It should combine with similarity;
percentage controls remain available, and grouping should explain why other filters
must be cleared. Clear refinements and try grouping again. Library and Similar photos
should use the same review controls.

**d.** Open the **need attention** sidebar note. It should clear unrelated filters and
show source issues. Only source refinements should appear; there should be no Bookmark
or Library review controls. Add a search that matches nothing: the active Needs attention
control should remain clearable at zero. Clear the search before continuing.

### Test SB3 — Size facts and reviewed photos

**a.** In Library, search `generated-022.jpg`. Select Needs review → Small, then
**Review one by one** and **Mark reviewed**. It should leave that Small queue without
rejecting or removing the photo from Library.

**b.** Return to Library, search the same filename, open **Filters**, enter **750** for
**Shorter side below (pixels)**, and apply. The reviewed photo should still appear:
size browsing is independent of its reminder.

**c.** In Settings → Files, change the reminder minimum from 800 to 750. The photo should
stay out of Needs review → Small. Turn small-image reminders off: the independent size
filter should still find it. Finally restore reminders to **800**; the reviewed photo
should not reappear in Small. Clear filters afterward.

### Test SB4 — Create and remove a bookmark

**a.** In Library search `generated-005.jpg`, open its information pane, and choose
**Bookmark…**. Check the date should be selected initially. There should be seven reasons,
an optional note, a visible character counter and a 60-character limit. The note field,
labels and buttons should align with the rest of the app.

**b.** Choose **Ask someone**, enter `Ask about this generated photo`, and save.
Open Library → Needs review → Bookmarked. Its card should show that reason and note.
Refresh the browser: both should remain.

**c.** Search the same filename within Bookmarked and choose **Review one by one**.
The photo and note should appear without an unrelated editing dialog. Choose
**Remove bookmark**. If this empties the filtered result, the old preview should close.

**d.** Search `generated-005.jpg` in Library again. It should still exist, retain its
Small reminder, and show the bookmark addition/removal in **Review history**.

### Test SB5 — Each bookmark opens the right tools

For each step, start in Library → Needs review → Bookmarked, search the specified
filename, and choose **Review one by one**. Return to Library between steps to clear the
previous search. The prepared notes read `Generated Bookmark walkthrough`.

**a.** `generated-035.jpg` — **Check the date** shows the bookmark's reason and note and
the photo's recorded dates, with **Edit metadata date…** focused; the editor must not open
by itself. Choose **Edit metadata date…**, change the calendar date to **2023-12-09**,
preview and save. The photo should remain bookmarked
after the save; its new date should be visible. Close the editor before returning.

**b.** `generated-053.jpg` — **Compare versions** shows the existing similarity controls
and matches. Choose one for side-by-side comparison, then return. No match should be
chosen automatically, and the bookmark should remain until explicitly removed.

**c.** `generated-026.jpg` — **Fix rotation** offers the familiar curved arrows and
Save rotation. Turn right and save. The photo should remain bookmarked after the turn.

**d.** `generated-034.jpg` — **Check the details** shows its recorded metadata and
primary source. No edit or primary-source change should happen merely by opening it.

**e.** `generated-043.jpg` — **Decide whether to keep it** offers Keep it, Remove bookmark
and Reject. Choose **Keep it**. Back in Library, the photo should remain and Review history
should record the keep decision with the original reason and note. Only its bookmark
should be removed; a separate Small reminder can remain.

**f.** `generated-052.jpg` — **Ask someone** displays the photo and note. Choose
Remove bookmark; the photo should remain in Library.

**g.** `generated-033.jpg` — **Other** displays the photo and note without opening an
unrelated editor. Remove bookmark should clear only that reminder.

### Test SB6 — Readability, keyboard and resizing

**a.** In Library, turn Needs review on and off and switch Reasons. Controls and counts
should remain readable; no unexpected banner should push the page around. Check both
dark and light modes.

**b.** At **200% browser zoom**, check the sidebar/menu, refinement row, Reason selector,
Filters panel and Bookmark dialog. Use `generated-005.jpg` to reopen Bookmark… and
**Cancel**. Controls may wrap, but should stay reachable without clipped text or
horizontal page overflow. Restore normal zoom afterward.

**c.** Use Tab and Shift+Tab through refinements and the Bookmark dialog. Focus should
be visible; Space should toggle a refinement, arrow keys should choose a bookmark
reason, and Escape should close the dialog and return focus to its opener.

## Shared Reject confirmation

<a id="shared-reject"></a>

**Accepted:** the maintainer reported **RC1 Pass, RC2 Pass, RC3 pass**.
RC1a–c, RC2a–c and RC3a–d are complete; no repeat checks are requested.
The steps below remain as the regression record. The review instance has been used;
its photos may now be in Rejects. Reverify or prepare their starting state before a
future run, without resetting the instance unasked. Automated publication checks
remain a separate gate.

Starting state verified before the accepted run: `rc-single.jpg`, `rc-bulk-a.jpg`, `rc-bulk-b.jpg`,
`rc-burst-1.jpg`, `rc-burst-2.jpg` and `rc-burst-3.jpg` are each present once in
Library. At 100%, each burst photo matches only the other two. Run RC3 after RC1/RC2;
leave the burst photos in Library until RC3.

### Test RC1 — One photo and appearance

**a.** In Library, search `rc-single.jpg`, open its information pane and choose
**Reject…**. The question should name the photo, explain Rejects briefly, and show
**Cancel** followed by **Reject**. Cancel should have keyboard focus. There should
be no **Don't ask again** checkbox.

**b.** Cancel. Open **Inspect photo…** for `rc-single.jpg` and choose **Reject…**.
The question, spacing and button order should match RC1a. Cancel again; the photo
should remain in Library.

**c.** Reopen the same question in light and dark mode, and at 200% browser zoom.
Text and actions should remain readable without horizontal scrolling. Cancel and
restore your normal zoom/theme. This check does not reject the photo.

### Test RC2 — Selected photos

**a.** In Library, search `rc-bulk-`. Tick `rc-bulk-a.jpg` and `rc-bulk-b.jpg`, then
choose **Reject (2)…**. Review both photos and choose **Reject these 2 photos**.
The shared question should say **Reject 2 photos?**, with Cancel focused and no
comparison checkbox.

**b.** Cancel that question. Both photos should remain selected in the review, and
no Reject job should start.

**c.** Choose **Reject these 2 photos** again, then **Reject**. Wait for completion.
In Rejects, search `rc-bulk-`: both photos should be there and absent from Library.

### Test RC3 — Comparison preference and last photo

**a.** In Library, search `rc-burst-1.jpg`, open **Similar photos** and choose
**100%**. There should be two matches: `rc-burst-2.jpg` and `rc-burst-3.jpg`.
Open either for side-by-side review. Choose **Reject…** under the candidate,
check **Don't ask again while comparing**, then Cancel. Open Reject again:
the checkbox should be unchecked and the photo should still be present.

**b.** Check that box again and confirm **Reject**. Wait for the next candidate.
Reject that candidate too: it should move to Rejects without another question.
The reference, `rc-burst-1.jpg`, should now be the only remaining photo in this
comparison.

**c.** Choose **Reject…** for `rc-burst-1.jpg`. A question must appear even though
RC3b enabled the preference. It should warn that none of these photos would remain
in Library, offer **Cancel** and **Reject it too**, and omit the checkbox. Cancel;
`rc-burst-1.jpg` must remain in Library.

**d.** Use **Return it to the library** in the comparison's last-result message to
bring back its last rejected candidate. Close the comparison and reopen that match
from `rc-burst-1.jpg`'s Similar photos tab. Choose **Reject…**: the question should
appear again with an unchecked preference. Cancel. Closing a comparison must not
remember its preference for the next one.

## Accepted sidebar and Stats checks

<a id="sidebar-stats"></a>

This batch changes wording, sidebar presentation and Stats. Filtering, metadata writes
and file-transfer rules stay the same. Automated results are recorded separately from
these maintainer checks. Report results by test and step, for example **U2c passed**.

Maintainer results: **U1–U4 passed**, including U2b after the label-width fix and
U1b after the live-feed recovery fix. The final U1b check began with fresh setup and
no previous Index; the maintainer confirmed it worked. **No manual checks remain
for this batch.** Automated results are recorded separately.

### Test U1 — Setup and photo-log wording

**a.** On the fresh review instance, complete setup. In Step 2, Small-image review and
Suspicious dates should be visible; expand File types and Rejects reminder to inspect
them, then collapse them. Back/Next should stay visible. In Metadata, check the shared-sidecar
example: `photo.jpg` and `photo.png` can share `photo.xmp`; `photo.jpg.xmp` identifies one
photo. The RAW rule is a statement, with no disabled storage selector. Choose **Ask me**
for shared sidecars. Leave the earliest expected year at 1800 and enable small-image
reminders at 800 pixels.

**b.** Run Index. The initiating control should show Starting immediately; once accepted,
progress should appear below the top toolbar without waiting for the next live update.
Check that the processed count advances. The Index summary should wait until Index
finishes, then the progress drawer should disappear and the Notifications bell should
show the result. A later unchanged re-index can finish in under two seconds. Copy is
needed only for the original full walkthrough, not this U1b recheck. The source is the full demo library plus four generated
validation photos. Processing issues in the demo may leave some files in Not organized;
these do not prevent the checks below. No Move is needed.

**c.** Open Library, search `ui-stats-date.jpg`, and open its information pane. Under
History, check **View photo logs** and **View lineage tree**. The lineage dialog also
uses **View photo logs**. Both log links should show this photo's history.

**d.** Open Settings → Metadata. The same examples and RAW rule should appear. The
shared-sidecar guidance should point to Not organized → Needs attention and Resolve
XMP; it should not say individual choices are unavailable.

### Test U2 — Sidebar alignment and count explanations

**a.** In Library, clear search and filters. Check that the Look into rows have equal
height, with labels, numbers and pins in straight columns. Repeat in Logs and Stats:
the filter labels and counts should stay aligned even though those pages have no pins.

**b.** Hover and keyboard-focus **No usable date** and **Needs verification**. The help should
show their full names. Needs verification should be readable in full, including when
selected. A long label should not wrap and push other rows down.

**c.** Before saving any reminder, Review later should show **0**. Pin Small images:
Review later should show **—**, be unavailable, and explain that Small images must be
unpinned. Unpin Small images: Review later should show its actual count again. Zero
means no matches; a dash does not mean zero.

**d.** Repeat the alignment check at 200% zoom or in a narrow window using Menu. Return
to normal zoom afterward. No sidebar action should be hidden behind its help text.

### Test U3 — Stats dates and duplicate space

**a.** Open Stats. Dates should span a full-width row below the headline tiles. Undated
should sit beside the chart, or below it in a narrow window, and open the no-date view.
Search `ui-stats-undated.jpg` there to verify the link.

**b.** Check the **Before 1800** and **Future** counts. They should sit apart from the
normal year bars. Each link opens Suspicious dates; search `ui-stats-early.jpg` or
`ui-stats-future.jpg` to verify the affected photos. A large suspicious count should
not make normal bars shorter.

**c.** Return to Stats. Keyboard-focus year links, scroll a long range and open **As a
table**. Suspicious years must remain in the table. Check narrow-window/200% reflow.
The Duplicates panel should describe exact copies and space, without a near-duplicates
or similar-photos-as-waste row.

### Test U4 — Verified metadata edits

**a.** Note the Metadata edits counts in Stats. Open Library, search `ui-stats-date.jpg`,
and open Metadata → the primary EXIF tab. Edit Date taken from June 15, 2020 to June 15,
2021, preview and save. Wait for completion.

**b.** Open Stats. Metadata edits should have one additional photo and one additional
date-edited photo. Copied/moved totals should stay unchanged. Follow the count: Logs should say **Saved metadata edits** and show
the save. **Show all log entries** should restore the normal log.

**c.** Change the same photo's date to June 15, 2022 and save. The distinct-photo counts
should stay the same, while the filtered log should show both saves.

**d.** Open `ui-stats-date.jpg`, rotate once using the preview's curved arrow and apply.
After completion, the rotation count should increase by one; the total edited-photo
count should stay the same. Do not compare these category counts by adding them: the
same photo now belongs to both dates and rotations.

## Historical checklists and accepted results

These are reference records, not an additional validation queue. Existing outcomes
are retained; a historical checklist without an explicit acceptance record is not
silently marked passed. Fixtures and counts below are **not verified in the current
review instance**; only RC1–RC3 have been prepared for this batch.

| Topic | Recorded status |
| --- | --- |
| [Same-name cards](#same-name-cards) | Accepted: original Tests 1a–1c and 2a–2c passed before PR #124 merged. |
| [Reference and keeper labels](#reference-and-keeper) | Historical checklist; no new validation requested. |
| [Source preparation](#source-preparation) | Setup reference, not a pending test. Real-library access requires explicit permission for each run; follow private environment rules. |
| [Similarity catalog setup](#similarity-setup) | Historical checklist; no new validation requested. |
| [Similarity browsing after Index and Copy](#similarity-browsing) | Historical checklist; no new validation requested. |
| [Similarity comparison and shared demo](#similarity-comparison) | Historical checklist; no new validation requested. |
| [Historical comparison scope](#comparison-historical-scope) | Historical scope statement, superseded by the accepted inline rotation checks below. |
| [Copy review link](#copy-review-link) | Accepted: Copy review link passed, recorded 2026-10-01. |
| [Small-image review](#size-review) | Historical checklist; no new validation requested. |
| [Review workspace](#review-workspace) | Historical checklist; no new validation requested. |
| [Review controls by location](#location-review) | Historical checklist; no new validation requested. |
| [Alignment and filter persistence](#alignment) | Accepted: Tests 1a–4a and 5a–5b passed, including the source-navigation correction. |
| [Notification bell and selection stability](#notifications) | Historical checklist; no new validation requested. |
| [Filter pins and tab navigation](#filter-pins) | Historical checklist; no new validation requested. |
| [Move after an embedded edit](#edited-source-move) | Accepted: M1–M3 passed, 2026-10-14. |
| [Initial metadata editor acceptance](#metadata-initial-acceptance) | Accepted: source viewer and date editor; original release scope retained below. |
| [Metadata scenario viewer](#metadata-viewer-cases) | Accepted: viewer and broken-sidecar follow-up passed; historical case paths need current filename verification before reuse. |
| [Original date-editor walkthrough](#date-walkthrough) | Accepted through the later numbered date-editor checks; retained as earlier instructions. |
| [Calendar and sidecar-version layout](#date-picker-layout) | Historical checklist; no new validation requested. |
| [Inspector Metadata tab](#metadata-tabs) | Accepted through the final date-editor branch walkthrough below. |
| [Full demo and metadata scenario walkthrough](#combined-library) | Accepted through final date-editor checks; historical setup recipe, not a request to reset the current instance. |
| [Source and destination navigation](#source-navigation) | Accepted: metadata and navigation checks, including follow-ups. |
| [Filter pin and gallery count follow-up](#pin-count-followup) | Accepted as Test 1 in the date-editor branch. |
| [Date-editor branch and follow-ups](#date-editor) | Accepted: Tests 1–6 and follow-ups, 2026-10-13. Original IDs retained. |
| [Incomplete photo/XMP transfer retry](#pair-retry) | Accepted: R1–R3 and delivery-status follow-ups, 2026-10-15. |
| [Metadata setup and Settings](#metadata-settings) | Accepted: S1–S3. Later Metadata tab/setup improvements also passed under readability below. |
| [Informational metadata warnings](#reader-warnings) | Accepted: W1 passed. |
| [Date information and source attention](#date-source-attention) | Accepted: D1, including D1c, passed. |
| [Settings grouping and message readability](#readability) | Accepted: Tests 1–4, all steps, 2026-10-16. |
| [Expanded photo Inspector](#expanded-inspector) | Accepted: Tests 1a–3b passed. |
| [XMP import choices and history](#xmp-choices) | Accepted as recorded below; corrected 2b has automated coverage and its source-only state was not required to be recreated. |
| [Saved-choice metadata comparison](#choice-comparison) | Accepted: Test 5 passed; visibility feedback was separate. |
| [Portrait sizing, choice visibility and inline rotation](#portrait-and-rotation) | Accepted: Tests 6, 7 and 8a–8g passed; the compact unsaved-turn redesign remains separate. |
| [Rotation history follow-up](#rotation-history) | Accepted: 8g passed. |
| [Edits that create identical photos](#edit-duplicates) | Accepted: 9a–9d passed. |
| [Changing an organized photo’s primary source](#primary-source) | Accepted: 10a–10e passed. |
| [Low-detail matches](#low-detail) | Accepted: Tests 1a–1c and 2a–2b passed. Counts apply to its prepared fixture only. |
| [Similarity acceptance, 2026-09-29](#similarity-2026-09-29) | Accepted historical functional results; not a scale-performance sign-off. |
| [Similarity acceptance, 2026-10-01](#similarity-2026-10-01) | Accepted historical functional results; not a scale-performance sign-off. |

## Same-name cards

<a id="same-name-cards"></a>

**Record:** Accepted: original Tests 1a–1c and 2a–2c passed before PR #124 merged.

For a generated `tools/make_scenarios.py build` library, verify the fixture names and
filing dates in the review instance before handing over these tests. The default
seed produces two different `IMG_0001.jpg` photos in `trip-a` and `trip-b`.

**Test 1 — Not organized cards**

a. In Not organized, search `IMG_0001.jpg`. Both cards show their original folders,
`…/trip-a` and `…/trip-b`, under the name.

b. Hover each name: its full original path appears. Moving the pointer away does not
move the cards or add/remove the folder line.

c. Open Source folders, then enter `IMG_0001.jpg` in search again (opening Source
folders clears the search). Expand `scenarios`, then `same-name`, using their arrows.
Check `trip-a`: only its card remains and the extra folder line disappears. Use
Show all above the tree to restore both photos and their folder labels.

**Test 2 — Library and filtering**

a. Select these two photos and Copy them. In Library, search `IMG_0001.jpg`: when their
filing dates differ, both retain that name and their original-folder labels. Their
hover paths still identify the source, not their date folders in the destination.

b. Narrow to one photo's recorded year with Filters. With only one name remaining in
the result, its extra folder line disappears; clearing that date filter restores it.

c. Check the labels in both color modes and at 200% browser zoom. They stay on one
supporting-text line, with the full path available on hover if space is tight.

Arrival collision renames and identical-copy folding have separate automated coverage;
do not assume these two generated photos will collide at the destination when their
filing dates differ.

## Reference and keeper labels

<a id="reference-and-keeper"></a>

**Record:** Historical checklist; no new validation requested.

Manual check: open Similar photos, confirm the large preview is labelled **Reference
photo**, then choose **Keep reference, reject n matches…**. Only the resulting review
should label it **Keeping**; Cancel should return without rejecting anything.

## Source preparation

<a id="source-preparation"></a>

**Record:** Setup reference, not a pending test. Real-library access requires explicit permission for each run; follow private environment rules.

Use generated or sample photos for short checks and the shareable demo. Use a
representative real library over NFS for larger read/performance checks in a separate
private instance. Mount either source read-only and run **Index → Copy → destination
review**. Do not use Move against the real validation source. An indexed source alone
does not populate destination similarity review.

Give each instance its own catalog/appdata, cache, backups and writable destination;
keep the destination on the intended local storage volume with enough room for the
test. Before Copy, verify the running app's bind mounts with `docker inspect`: check
the host source behind `/data/dest` and confirm `/data/source` is read-only. Changing
an environment file alone does not remount an existing container. Recreate the app
after it is idle to apply mount changes; do not assume this migrates an existing
destination or updates recorded paths.

Keep host-specific paths, private filenames and raw reports in ignored local files.
The LAN demo should use only its sample source and separate destination. Share
aggregate timings and generated-fixture screenshots in tracked documentation.
The sampler below makes hard links; those are suitable for read-only input, not
isolated files for future in-place EXIF editing tests.

## Similarity catalog setup

<a id="similarity-setup"></a>

**Record:** Historical checklist; no new validation requested.

The validated sample uses a fresh catalog rebuilt by maintainer choice. With fresh
appdata, use **Create catalog → save settings → Index → Copy**,
then validate the gallery controls and Inspector. Keep the source read-only and the
existing sample destination. No upgrade step is required for this route.

## Similarity browsing after Index and Copy

<a id="similarity-browsing"></a>

**Record:** Historical checklist; no new validation requested.

For manual validation after Copy, open a destination photo in the gallery and choose
**Similar photos** in the Inspector. Click a 75/80/85/90/95/100% count to browse
its matches in the thumbnail grid. Use
**Has similar photos** to narrow the gallery; the count buttons narrow only the
Inspector results. The gallery's separate **Matches at or above** selector changes
its membership, and **Most matches first** sorts counts highest first. Reload and
return from Logs to confirm the reference and threshold
remain.

Manual checks after Index/Copy: use Review matching status for any affected photos;
review the reason, run the appropriate action, and check the remaining count. In
comparison, rotate or zoom, choose a review filter, and refresh: the same comparison
should reopen. Back to gallery clears it. EXIF edits, saved orientation writes and
deletion belong to a separate workstream and do not block these checks.

Manual UI checks: switch All photos / Has similar photos / No usable capture date and
compare card geometry, summary placement and filter actions. At narrow desktop
widths, controls should wrap without clipping. Open a card from Has similar photos:
Similar photos should be selected at the gallery percentage. Switch to information,
use next/previous (retain that choice), then click another similar-gallery card
(reopen Similar photos). Reload preserves the explicit tab. Check the shortcut's
pressed state against Sort. Long filter descriptions remain in More information.

## Similarity comparison and shared demo

<a id="similarity-comparison"></a>

**Record:** Historical checklist; no new validation requested.

Create the catalog, run Index and Copy in this new instance. Then open a photo:
From All photos, Photo information should appear first. Similar photos opens the counts and thumbnail
grid, initially at 90%. Resize the Inspector, switch tabs with the keyboard, and
move to the next photo: the tab/threshold should remain, with match paging reset.
Reload should restore the recorded tab and match page. The provided scenario set
contains intentional unreadable/invalid files; those are expected test outcomes.

Before opening a candidate, enter **Has similar photos**, click the visible
**Most matches first** shortcut (also available in Sort), and
change **Matches at or above**. Check card counts against the Inspector at that same
percentage. Search/date/type filters narrow references, not their counted
matches. Zero-match photos disappear; explicit checkbox selection remains. Reload
and return from Logs: sort and gallery threshold persist. Opening a gallery card
opens Similar photos at the gallery threshold; later Inspector changes do not reorder
the gallery. Leaving Has similar photos resets its special sort to Newest first.
The API checks ranking before pagination, tie ordering, matching facet/selection
scope, exact-copy deduplication, threshold boundaries and partial coverage. Browser
checks exercise the controls, card counts, selection preservation and narrow reflow.

Open a candidate using **Review side by side** to enter the expanded workspace:

1. Rotate and zoom each preview separately; then enable linked zoom/position.
   Rotation stays independent. Switch candidates and return: viewing transforms
   follow their photo until the workspace closes. No file orientation is saved.
   At 90°/270°, dimensions beneath the preview swap width and height and read
   **Displayed**; at 180° they keep the original width/height order. Reset restores
   the original view. Zoom never changes these dimensions. The information pane
   retains recorded dimensions, megapixels and file size throughout.
2. In Information, check **File and image properties** above **Capture information**:
   format, extension, pixel dimensions, megapixels, file size and aspect ratio.
   Missing values and fallback dates remain labelled; a format inferred only from
   the filename says **extension only**. Differences are neutral, with no automatic
   winner based on format or size. Differences only applies to every section;
   All recorded tags adds the full metadata table, with search scoped to that table.
   Scroll each table: **Field / Reference / Candidate** stays visible while its rows
   scroll, including narrow reflow. The heading background should be opaque in both
   light and dark themes.
3. Browse candidates and switch pages: browsing never changes gallery checkboxes.
4. Resize the comparison/information divider and the browser window. Candidate
   browsing remains available; Back to gallery restores the Inspector context.
   Both previews' dimensions, sizes and linked-zoom controls fit their comparison
   area without an inner vertical scroll; the whole review window scrolls when
   needed. The information pane can scroll independently on desktop.
5. Choose **Use as reference** above a candidate. Its blue reference frame moves
   with the photo, its matches reload at the same threshold, and the previous
   reference appears beside it, on page one. Each photo's viewing rotation stays
   with it. Back to gallery returns to the originally opened photo.
   **Reference photo** is a plain heading, not a button; the blue preview border
   distinguishes it from the candidate. Promotion does not select a keeper or donor.

## Historical comparison scope

<a id="comparison-historical-scope"></a>

**Record:** Historical scope statement, superseded by the accepted inline rotation checks below.

Metadata writes and end-of-review orientation saving are tracked in
[TODO.md](../TODO.md#dates-and-metadata). These are not current
validation steps. The workspace compares, rejects and keeps one of a set; closing it
discards temporary rotation without a save prompt.

## Copy review link

<a id="copy-review-link"></a>

**Record:** Accepted: Copy review link passed, recorded 2026-10-01.

1. Open a photo comparison using Review this set or Review side by side. Rotate a
   preview or adjust zoom so the restored state is easy to recognize.
2. Click Copy review link near the top of the comparison window. If Review link
   copied appears, proceed to step 3. If Copy this review link manually appears,
   click inside its text field, press Ctrl+A while the field is focused, then Ctrl+C
   (Command+A / Command+C on macOS). Local-network HTTP may require this fallback.
3. Open a new browser tab, paste into the address bar, and press Enter. Use a tab
   that can access the same sample instance; the link does not upload photographs.
4. Confirm the same reference/candidate, percentage and current pair rotation/zoom
   reopen.

Pass: either copy path gives a usable link that restores the current comparison.
The manual fallback is expected behavior when clipboard access is unavailable.

## Small-image review

<a id="size-review"></a>

**Record:** Historical checklist; no new validation requested.

Manual review before merging: choose On and Off on separate fresh catalogs, review
mixed-size delivered photos, verify a useful small photo disappears only from Small
images after Mark reviewed, and verify unwanted photos follow the existing Reject
confirmation. Inspect the workspace and first-run Files at desktop zoom. This branch
uses the current schema and requires a fresh development catalog; it does not migrate older catalogs.

## Review workspace

<a id="review-workspace"></a>

**Record:** Historical checklist; no new validation requested.

Manual batch check: switch Library → Not organized with a photo open; open a source
preview and close it to restore the summary; toggle each filter twice; open Review
photo… and check the reason, action row, compact viewing controls and the Similar photos count/link. Open all matches in the
existing Similar photos tab; browser Back must restore the same review photo and queue
position without changing gallery filters or checked photos.
A successful Mark reviewed clears only the size reminder. Unreadable-only source
results should point to failures rather than offering an ineligible transfer.

## Review controls by location

<a id="location-review"></a>

**Record:** Historical checklist; no new validation requested.

Manual check after first-run setup: Index, open a source file (information only), Copy,
open a Library photo (review and similarity available), Reject it and check Return is
offered without review actions. Check Index-summary ready/failure counts and failure
links, Stats scope explanations, and the shared job labels in banners and Logs.

## Alignment and filter persistence

<a id="alignment"></a>

**Record:** Accepted: Tests 1a–4a and 5a–5b passed, including the source-navigation correction.

These are new spot-checks; previously accepted metadata tests do not need repeating.

1. **Logs**
   - **1a.** Open Logs. CSV/JSON belong beside the heading under **Export filtered log**;
     the search and From/To fields have aligned edges.
   - **1b.** Choose **Failed → only**, then **All statuses**. Filters and job-list controls
     stay in position after the results settle. Export still follows the chosen filters.
2. **Settings**
   - **2a.** Open Settings → Files. Toggle Small-image reminders On, Off, then On.
     The minimum stays visible, disabled while Off; the explanation and controls below
     do not jump. Close Settings without saving to retain the original setting.
   - **2b.** Check the file-type input/Add file type row and the Backups tab: buttons and
     supporting text align and wrap without stretched buttons. No backup is needed.
3. **Comparison**
   - **3a.** In Library → Has similar photos, open any matching photo (search
     `scn-orientation` in the demo scenarios), choose Similar photos, then Review side
     by side. Change the reference zoom from 1× to 2×: position sliders enable without
     moving dimensions or Keep. Rotate, then Reset view: the same rows stay in place.
   - **3b.** The minimum-similarity/Refresh controls stay separate from the photo's
     Keep and Reject actions. Rotation/zoom apply only to the preview.
4. **Reflow**
   - **4a.** Repeat the visual checks in light/dark mode and at 200% browser zoom or a
     narrower desktop window. Controls may wrap; labels/buttons should not overlap or
     clip. Reference/candidate headings and previews align when displayed side by side.

5. **Files needing verification**
   - **5a.** In Library, confirm the renamed filter has a count (including zero).
     Choose it, then switch to Needs review: the same organized files/count appear.
   - **5b.** Pin Files needing verification. Visit Not organized, Source folders, and
     Needs attention: the filter and pin highlight are inactive, with no destination
     filter restricting source results. Return to Library or Needs review: the filter
     and pin return. Repeat with an unpinned Small images filter; its choice also returns.
     A source-page refresh keeps that remembered choice. Clear all filters cancels it.
     Shared search/date filters retain their existing behavior. Source import failures
     remain under Not organized → Needs attention. Zero is valid; do not create a failure.

Maintainer accepted alignment checks 1a–4a, verification check 5a, and revised
source-navigation check 5b. Manual validation is complete for this batch.

## Notification bell and selection stability

<a id="notifications"></a>

**Record:** Historical checklist; no new validation requested.

Manual: open the bell after Index/Copy; verify each job, result and links; close/reload
and confirm the unread count stays cleared. Run another job and check that it creates
one new unread notice. Select 1, 9, 10 and more photos: the adjacent actions should stay
in place. Opening the bell must not move the gallery. Check Logs/Stats and desktop zoom.

## Filter pins and tab navigation

<a id="filter-pins"></a>

**Record:** Historical checklist; no new validation requested.

Manual: in Library, click No usable capture date then Suspicious dates; only the latter stays
active. Pin Small images and try those date filters again: Small images stays applied.
Review later should show its count immediately in Library, including zero. Filter by
it, switch to Needs review and back, and confirm the same reminder remains applied.
Refresh, then check the Small images/Review later restriction in both places and
its unpin explanation. Clear all filters, beside Look into, should remove saved pins,
search and folder/date/type restrictions without clearing photo selection or changing
place. The filter rows should stay still when that action appears or disappears. No Index or Copy
is needed when the demo is already populated. Open a photo, choose Similar photos,
then click a different gallery photo: Photo information should open. Check this in
Library and Has similar photos; reloading an explicit Similar photos tab should retain it.

## Move after an embedded edit

<a id="edited-source-move"></a>

**Record:** Accepted: M1–M3 passed, 2026-10-14.

Maintainer validation: **M1, M2a–c and M3a–b passed (2026-10-14).** The M2c
feedback requests a clearly visible Refresh Move preview button; it uses the shared
filled primary style. During M3a the source original was verified to retain its
2019 EXIF date and the Library copy its 2021 date. A false missing-EXIF-date message
and unclear source/destination Inspector context were reported and corrected;
The maintainer passed the remaining checks after these corrections. The API and
Move browser regressions cover these cases.
Use a disposable generated source with a writable
mount for Move, never the shared sample library. The metadata scenario builder supplies
these searchable names; the EXIF-only case must use embedded JPEG writes, not a forced
new XMP sidecar. Keep the ordinary JPEG/XMP setting off for this check.

1. **Test M1 — setup and the job-level choice.**
   a. Complete setup, create the catalog, Scan/Index and Copy the generated library.
      Existing deliberately broken-sidecar cases can remain at source.
   b. In Library, search **md-exif-only.jpg**. Open Metadata → primary EXIF → Edit
      metadata date. Change the date from 2019 to **2020-06-15T12:00:00**, preview and save.
   c. Jobs → Move → Move all: verify one affected original, its expandable source name,
      the exact-original-bytes warning and disabled Move until Include/Leave is chosen.
   d. Choose Include, cancel, reopen: neither choice should be remembered. Check at
      200% and a narrow window; Cancel/Move must remain reachable. Cancel afterward.
2. **Test M2 — scope and stale confirmation (before moving files).**
   a. Select **md-exif-only.jpg** and choose Move. Verify the same choice, then cancel.
      Select it together with **md-embedded-xmp-only.jpg**, enter the Move review,
      then Move these photos: the confirmation should still identify only the edited
      original. Cancel and clear the selection.
   b. Source folders → Still in source: select the **exif_only** folder. Move this
      folder must offer the same edited original. Cancel.
   c. Open Move all. In another tab, change **md-exif-only.jpg** to
      **2021-06-15T12:00:00** and finish saving. Submit the older Move confirmation:
      it must refuse without moving photos. Refresh Move preview must require the
      Include/Leave choice again. Cancel afterward.
3. **Test M3 — Leave, then Include.**
   a. Jobs → Move → Move all, choose Leave these originals at source, then Move.
      Ordinary eligible photos move; deliberately broken/held fixtures may remain.
      **md-exif-only.jpg** must remain under Source folders → Still in source, and
      its edited Library copy must retain the 2021 date. Opening the source entry
      displays a notice that the Inspector shows the Library copy; it must not
      falsely claim that this edited EXIF has no date taken.
   b. Start Move all again: choose Include and confirm once. That original is removed
      only after verification; its edited Library copy and metadata history remain.
      Source folders must no longer list it as still in source. Check the job's log.
      Do not interpret the fixture library's intentionally broken files as a new failure.

## Initial metadata editor acceptance

<a id="metadata-initial-acceptance"></a>

**Record:** Accepted: source viewer and date editor; original release scope retained below.

The agreed first web editor changes only Date taken; broad metadata viewing does not
imply general field editing. The date editor is built and accepted; coverage includes:

- Separate sidecar XMP, embedded XMP and EXIF fixtures; mixed/conflicting sources and
  alternate versions. Primary remains visibly identified when another tab is selected.
- Compare with primary and differences-only show the two captured values; explicit
  Empty and absent Not recorded remain distinct. Read/request failures expose recovery.
- Viewing, tab changes and comparison do not change bytes, primary, paths or history.
- Date copying/manual edits preserve untouched fields and date companions, never
  prefill missing XMP from fallback values, and clearly preview clears and destinations.
- Unsupported writer values cannot save or trigger an automatic primary switch. Save
  uses one confirmation for the date and any refiling; failures retain actionable details.
- Keyboard tabs, focus, stable layout, both themes and desktop zoom follow shared checks.

Read-only viewing, date editing and save checks passed maintainer acceptance, including
the final presentation follow-ups below. Saved rotation and general composition remain
separate scope.

## Metadata scenario viewer

<a id="metadata-viewer-cases"></a>

**Record:** Accepted: viewer and broken-sidecar follow-up passed; historical case paths need current filename verification before reuse.

For manual acceptance, use Source folders to locate these generated cases, open Photo
information, and scroll to Metadata sources:

| Case | What to verify |
| --- | --- |
| `conflict/date_three_way` | Primary sidecar date is 2021; embedded XMP is 2020; EXIF is 2019. Compare on either alternative tab, then filter to date. |
| `agree/all_three_agree` | Embedded XMP compared with primary has no differing fields. Default-language wrapping alone is not a difference. |
| `conflict/sidecar_clears_title` | Primary title is Empty; embedded XMP has Beach day. |
| `agree/complementary` | EXIF has a date; the sidecar does not. Comparison says Not recorded; it does not fill the sidecar with EXIF data. |
| `agree/exif_only` | EXIF is Primary; the sidecar tab reports no metadata recorded. |
| `sidecar_broken/malformed_xml` | Remains Not organized; the sidecar tab explains the read problem and links to photo logs without crashing. |

## Original date-editor walkthrough

<a id="date-walkthrough"></a>

**Record:** Accepted through the later numbered date-editor checks; retained as earlier instructions.

For maintainer acceptance, use disposable destination copies:

1. Open a Library photo, Metadata → Edit Date taken (or Photo information → Edit date).
   Verify the target and its own recorded date. Change a date; Cancel → Keep editing
   must preserve the draft, while Discard must leave the file unchanged.
2. Preview a different date. Check before/after values and current/resulting paths.
   Save once; wait for Date saved, then verify the date, folder and refreshed metadata.
3. On a nonprimary source with Date taken, choose Copy Date taken to primary.
   Preview its date and confirm primary stays the same; Save and inspect the result.
4. On an XMP target, explicitly clear the date. Preview must say Undated. After Save,
   the primary date is Empty, rather than silently borrowing the embedded date.
5. Reopen the editor. An unchanged date/location disables Save. Invalid calendar dates
   cannot preview; a qualified EXIF target refuses empty/partial values without switching.
6. Check light/dark, keyboard access and resized/zoomed layout. A draft must survive reflow.

## Calendar and sidecar-version layout

<a id="date-picker-layout"></a>

**Record:** Historical checklist; no new validation requested.

Maintainer checks: use the
calendar, confirm the full timestamp keeps its time/offset, and switch source tabs on
a photo with multiple sidecar versions without the fields shifting vertically.

## Inspector Metadata tab

<a id="metadata-tabs"></a>

**Record:** Accepted through the final date-editor branch walkthrough below.

1. Open a Library photo. Photo information shows actions, warnings and basic file/date
   facts. Technical details starts collapsed; expand it to find hashes and file tags.
2. Open Metadata. The primary source is marked, source tabs and sidecar versions work,
   and Compare with primary / Show differences only apply to fields and expanded tags.
3. Return to Photo information and choose Edit date. Metadata becomes selected behind
   the editor. Choose a calendar day, check the preserved time/offset, then preview and
   cancel/discard. Repeat and Save once; confirm the displayed date and filing location
   refresh. Copy a date from another source and explicitly clear an XMP date separately.
4. Choose Metadata or Similar photos, then use previous/next: the selected tab stays
   open. Click another gallery photo: Photo information opens. Refresh a URL with
   tab=metadata: Metadata is restored.
5. Source photos and Rejects still offer read-only Metadata; source issues remain on
   File information. Neither offers date-edit controls. Similar photos remains available
   for Library and Rejects only.
6. Check light/dark modes, resized panels and desktop zoom; source tabs, controls and
   comparisons stay readable. Enlarging a photo retains compact information and its
   View metadata shortcut returns to the Metadata tab.

## Full demo and metadata scenario walkthrough

<a id="combined-library"></a>

**Record:** Accepted through final date-editor checks; historical setup recipe, not a request to reset the current instance.

Use a fresh disposable catalog/destination with the full demo library and the metadata
scenario library mounted read-only under separate source subfolders. Keep the scenario
manifest alongside the deployment, outside Git. The full demo includes thousands of
photos plus intentional edge cases; the metadata builder adds focused source/date cases.
Source files, catalog photos and organized Library photos are different counts: sidecars,
exact duplicates and import holds mean they will not match. This walkthrough validates
real browsing and editing behavior; it is not a 200k/500k performance benchmark.

1. **Setup and Index.** Start from the base URL, create the catalog, finish setup and
   choose On or Off for small-image reminders. Run Index and wait for completion.
   Inspect Not organized and the summary; Library remains empty until Copy. Needs
   attention should explain intentional malformed/unreadable scenarios and link to logs.
2. **Copy.** Run Copy all photos and wait for completion. Use Copy for read-only test
   sources. Library should contain thousands of photos; duplicates are organized once,
   and unsafe/unreadable cases remain at source with explanations. Check notification
   details and Not organized → Needs attention; record unexpected failures by their
   generated case, rather than assuming every failure is expected.
3. **Browse at volume.** In Library, scroll through several loads, use the year scrubber,
   search, select/unselect photos, and try Look into filters and Clear all filters. Open
   photos with clicks and previous/next. Gallery clicks reset to Photo information;
   previous/next retains Metadata/Similar selection, including across page boundaries.
   Explicit metadata-tab URLs restore on reload.
4. **Find a metadata case.** Search Library by its unique `md-` case token,
   for example `md-date-three-way` or `md-exif-only`. Demo scenarios use `scn-`.
   These tokens remain searchable if a destination collision adds a numbered suffix.
   For source inspection, use Not organized → Source folders → Still in source.
   Confirm the case against the manifest. Never reuse photo IDs or a `case-ids.json`
   mapping from a previous catalog; regenerate mappings after Index if needed.

| Case folder inside metadata fixtures | Expected before editing |
| :--- | :--- |
| `conflict/date_three_way` | Sidecar primary date 2021-08-01 09:30:00; embedded XMP 2020-05-01 10:00:00; EXIF 2019-06-15 12:00:00. |
| `agree/complementary` | Sidecar primary has no date; date editor starts blank, while filing uses the EXIF date 2019-06-15. |
| `agree/sidecar_only` | Sidecar primary with date 2019-06-15 12:00:00; useful for explicit-clear testing. |
| `agree/exif_only` | EXIF primary; date 2019-06-15 12:00:00. |
| `agree/embedded_xmp_only` | Embedded XMP primary; date 2019-06-15 12:00:00. |
| `sidecar_broken/malformed_xml` | Remains in Not organized; metadata warning identifies its sidecar and gives external repair/reindex guidance. |

5. **Information and comparison.** On the three-way case, Photo information shows a
   short filing-date summary and its source. Technical details starts collapsed and
   exposes hashes/file tags when opened. Metadata shows the three captured sources,
   identifies Primary independently of the selected tab, and defaults to primary.
   Compare EXIF/embedded XMP against primary, then enable differences-only and search.
   Expand recorded tags: they follow both controls and distinguish Empty from Not
   recorded. Raw names/structures can differ across formats even for equivalent common
   fields. Clear the search and switch source tabs without controls shifting vertically.
6. **Cancel then save.** From Photo information choose Edit date; Metadata is selected
   behind the editor. Pick an unused calendar day, checking time/fraction/offset remain
   unchanged. Preview shows write target, old/new date and old/new destination. Cancel →
   Keep editing preserves the draft; Cancel → Discard leaves files/date unchanged.
   Repeat, Save once and wait for Date saved. Clear restrictive date filters if needed
   to find the refiled photo. Confirm date, destination, primary source, other fields and
   photo logs. A photo-name collision should offer a numbered filename in Preview,
   never overwrite. Save must use the confirmed filename; a changed target needs a new preview.
7. **Copy and clear.** On a nonprimary EXIF tab choose Copy Date taken to primary;
   preview/save and verify the sidecar stays primary and the donor is unchanged. On
   the sidecar-only case, explicitly clear Date taken; preview/save should show Undated
   and Empty. On the complementary case, the initial editor must be blank rather than
   prefilled from EXIF; its explicit-clear explanation describes suppressing fallback.
   Keep these tests separate so earlier edits do not invalidate later expectations.
8. **Other targets and guards.** Test a complete date change on EXIF-only and
   embedded-XMP-only cases. Invalid dates cannot proceed; EXIF partial/empty values
   are refused rather than changing primary. No-change previews cannot save. Source
   photos and Rejects have read-only Metadata, with no date-save controls. Source
   warnings remain on File information and Similar photos is absent there.
9. **Layout and accessibility.** Repeat tab switching and a comparison in light/dark
   mode, with a resized Inspector and 200% desktop zoom. Check labels, buttons, tables
   and scrolling. Keyboard arrows switch focused tabs without changing the photo.
   Enlarge a photo; View metadata returns to its Metadata tab. Similar-photo browsing
   and side-by-side comparison still work on the full demo's matching sets.

Report the step/case, expected versus actual result and screenshot for any issue.
These manual checks precede commit/push and GitHub validation of the final editor branch;
they do not establish support for every intentionally unsupported builder scenario.

## Source and destination navigation

<a id="source-navigation"></a>

**Record:** Accepted: metadata and navigation checks, including follow-ups.

- Needs attention is indented under Not organized beside Source folders, has a count
  including zero in Library, Logs and Stats, and opens all affected source files.
  It has no pin; choosing Not organized leaves attention filtering.
- Source folders owns the only folder tree. Select a folder and switch Waiting /
  Still in source: the folder stays selected. Choose Library, Needs review or Rejects:
  the source-folder restriction disappears, including from the URL.
- Filters contains file types and Dates in each gallery. Date checkboxes narrow results;
  the date scrubber jumps within them. No second folder selector remains.
- Refresh and browser Back restore source scope; old destination folder URLs cannot
  leave an invisible filter. Source scope controls must not cover folder rows at desktop
  size or narrow reflow. Checkbox photo selections remain independent of navigation.

Maintainer reports Create, Index and Copy passed on the combined demo/scenario library.
Metadata and navigation acceptance subsequently passed, including all follow-ups below.

## Filter pin and gallery count follow-up

<a id="pin-count-followup"></a>

**Record:** Accepted as Test 1 in the date-editor branch.

Manual acceptance: in Library, pin Has similar photos and Suspicious dates; unpin each
in turn and confirm the gallery/counts broaden, then refresh. Verify Library keeps its
sidebar total, and only filtered results show “Showing N of M photos” above the gallery.

## Date-editor branch and follow-ups

<a id="date-editor"></a>

**Record:** Accepted: Tests 1–6 and follow-ups, 2026-10-13. Original IDs retained.

**Acceptance complete (2026-10-13).** Tests 1–6 and follow-up checks 3b, 4f,
5a, 5c, 5d and 5e passed. No further manual checks are requested for this batch.
The numbered steps below remain as the regression checklist.

**Maintainer results (latest review):**

| Test | Status |
| :--- | :--- |
| 1 | Passed. |
| 2 | Passed, including comparison tags layout. |
| 3 | Passed, including folder layout/actions follow-up 3b. |
| 4 | Passed, including corrected job counts and lineage follow-up 4f. |
| 5 | Passed, including follow-ups 5a, 5c, 5d and 5e. |
| 6 | Passed. |

The searchable-fixture refresh passed both Docker builder suites (9 metadata tests
and 10 demo-scenario tests). It includes 60 metadata cases. The maintainer completed
the follow-up validation after the refresh. Do not reuse IDs from an older catalog.

The maintainer authorized the reported-fix batch after finishing the other tests.
The searchable scenario update requires freshly generated fixtures and a fresh catalog;
keep previous validation data separately. Do not run retry/edit jobs on the maintainer's
behalf. Earlier acceptance results remain recorded above.

Search by the filename tokens below in the refreshed scenario library. Dates are the
initial values, before editing. A collision can add a filename suffix, so searching
without the extension is useful. Clear Library filters before searching.

| Steps | Destination filename to search | Initial filing date | Metadata case |
| :--- | :--- | :--- | :--- |
| 3e, 4a–f, 5a–b | `md-date-three-way.jpg` | 2021-08-01 | Three sources; sidecar primary |
| 5c–d | `md-sidecar-only.jpg` | 2019-06-15 | Sidecar-only |
| 5e–f | `md-complementary.jpg` | 2019-06-15 | Sidecar missing date; EXIF fallback |
| 6a, 6c–e, 6g | `md-exif-only.jpg` | 2019-06-15 | EXIF-only |
| 6b | `md-embedded-xmp-only.jpg` | 2019-06-15 | Embedded-XMP-only |

Create, Index and Copy have passed maintainer validation. A fresh fixture catalog
needs its own Index and Copy before these checks; earlier viewer acceptance still stands. These checks cover the remaining
layout/navigation changes and date-save workflow. Automated checks do not replace
maintainer acceptance.

**All Tests 1–6 and the following comment follow-ups passed maintainer validation:**

- **Test 3b:** Selecting/unselecting folders keeps the tree in place. Copy/Move stay
  visible but disabled with guidance unless exactly one folder is chosen.
- **Test 4f:** Lineage omits repeated selection-job links already represented in the
  tree; jobs without a recorded file step remain in a collapsed disclosure.
- **Test 5a:** On an alternative source's Date taken row, Copy date to primary is a
  link beside the date. It opens the same preview/save workflow, never copies all fields.
- **Test 5c:** The primary date and Photo information shortcut read Edit metadata date.
  A repeated clear of an already-empty primary date in Undated previews No changes
  needed with Save disabled. An absent date and an explicit empty are still distinct.
- **Test 5d:** The Date saved dialog has one heading and a shared footer containing
  View job details and Close, with consistent spacing.
- **Test 5e:** A primary missing Date taken points to another source with a recorded
  date; its link opens that source for review. No value is copied automatically.
  An explicitly cleared primary date does not get this suggestion.

Two non-blocking discussion items were recorded with the final passes: whether folder
handling can happen behind the scenes (3b; behavior still to define), and whether
the existing photo-filtered Open in the log link could have a clearer label (4f).
It already shows associated operations across jobs; no new log filtering is needed. Neither
requires another validation pass now. Copying all metadata also remains a separate
post-validation discussion, not part of this batch.

##### Test 1 — Filters and totals

- **a.** Hard-refresh Library, then Clear all filters. The whole-library count should
  appear in the sidebar without being repeated above the gallery or beside pagination.
- **b.** Pin Has similar photos and Suspicious dates. Both should be active, with one
  “Showing N of M photos” summary reflecting their intersection.
- **c.** Unpin each in turn. Each filter should turn off, and the photos, counts and URL
  should update. Refresh; both should remain off.
- **d.** Choose Newest first or Oldest first, then No usable capture date. The year controls
  should disappear without making the gallery jump.
- **e.** Pin No usable capture date and enable another available filter. The year controls
  should remain hidden, including after refreshing.
- **f.** Unpin No usable capture date. The other filter should remain active, and the year
  controls should return while sorted by date. Clear all filters before Test 2.

##### Test 2 — Inspection and comparison

- **a.** Open a Library photo with a review reason. Its action row should read Inspect
  photo, Review later and Reject, with consistent button styling.
- **b.** Choose Inspect photo. It should open the existing review workspace. Return
  to the gallery afterward.
- **c.** Open a photo with matches, choose Similar photos, then Review side by side.
  Refresh comparison should be outlined and aligned with the Minimum similarity
  dropdown. Keep should be beneath the reference preview's controls and dimensions.
- **d.** Choose Keep. The existing rejection-review screen should identify the correct
  keeper and other photos. Cancel/back out without rejecting any photos.
- **e.** Reopen the comparison and choose Use as reference on a candidate. Keep should
  now name that photo. Refresh comparison should retain the current reference.
- **f.** Check these controls in both themes and at 200% desktop zoom. They should
  remain readable and reachable. The recorded-tags layout recheck has passed.

##### Test 3 — Navigation and metadata viewing

- **a.** Open Not organized → Needs attention. It should have a sidebar count and show
  the affected source files.
- **b.** Open Source folders and select a folder. Switch Waiting / Still in source:
  the selection should remain, and the scope controls must not overlap folder rows.
  Please check at the window size where you originally saw the overlap.
- **c.** Choose Library. The source-folder restriction should disappear from results
  and the URL. Types and Dates should remain available in Filters, with no folder tree.
- **d.** Click a gallery photo, choose Metadata, then use previous/next. The Metadata
  tab should stay selected. Clicking a different gallery card should instead select
  Photo information. Repeat with Similar photos.
- **e.** On `md-date-three-way.jpg` (three-source case), switch among
  XMP Sidecar, Embedded XMP and EXIF. Primary should remain clearly identified even
  when another source is selected. Find the case by its supplied destination
  filename and date; filenames alone may not be unique across the generated fixtures.
- **f.** Enable Compare with primary, differences-only and a field search. Expand
  recorded source tags in the Metadata tab: those controls should also apply there.
  Empty and Not recorded must remain distinct. The separate side-by-side layout recheck has passed.
- **g.** Repeat tab switching in light/dark mode and at 200% desktop zoom. Labels and
  controls should stay readable and stable.

##### Test 4 — Cancel and save a date

- **a.** On `md-date-three-way.jpg`, note the current primary, date, destination and
  another recorded field. Open Edit date and pick an unused calendar day. Any recorded
  time and timezone offset should remain unchanged.
- **b.** Preview. Confirm the primary write target, old/new date and old/new destination
  before saving. No file change should have happened yet.
- **c.** Choose Cancel → Keep editing. Your draft should remain. Then Cancel → Discard:
  the saved date and destination should be unchanged.
- **d.** Repeat the edit, preview and Save once. Wait for Date saved.
- **e.** Check Photo information and Metadata: date/path should match the preview;
  primary identity and unrelated fields should be unchanged. Clear any restrictive
  date filters if the photo leaves the current view.
- **f.** Open its log and confirm the date-edit operation is recorded. Refresh the
  page and confirm the saved date remains.

##### Test 5 — Copy and clear a date

- **a.** On `md-date-three-way.jpg`, select its nonprimary EXIF source tab.
  Choose Copy Date taken to primary. Preview must name the primary as the write target
  and show an available numbered filename if the proposed photo name is occupied.
- **b.** Save once. The primary date should match the chosen donor date; the donor
  and primary identity must remain unchanged.
- **c.** On `md-sidecar-only.jpg` (sidecar-only), open Edit date and explicitly
  clear Date taken. Preview should show the clear and an Undated destination.
- **d.** Save. Confirm Empty in the primary metadata and Undated in the destination.
- **e.** On `md-complementary.jpg` (complementary), the sidecar has no date
  while EXIF has one. Its editor should start blank, even if the filing date used EXIF.
- **f.** Explicitly clear that missing sidecar date, preview and save. This should
  suppress fallback and file the photo under Undated. Earlier edits can change a case's
  starting state; use an unmodified case or report that it is no longer suitable.

##### Test 6 — Other writers and guards

- **a.** On `md-exif-only.jpg` (EXIF-only), save a complete Date taken value. Confirm the resulting
  date/path and that EXIF remains primary.
- **b.** On `md-embedded-xmp-only.jpg` (embedded-XMP-only), do the same. Embedded XMP should remain primary.
- **c.** On `md-exif-only.jpg`, enter an invalid date, such as February 31. It should not proceed to saving.
- **d.** On `md-exif-only.jpg`, preview an unchanged date. Saving should be disabled with no changes needed.
- **e.** Search Library for `md-exif-only.jpg`, open Metadata, and confirm EXIF is marked
  Primary. Choose Edit Date taken, enter `2020` in the Date taken text field (not the
  calendar), and attempt Preview change if enabled. It must refuse the partial date
  with an explanation and must not switch primary. Cancel without saving.
- **f.** Open a source photo in Not organized and a photo in Rejects, if one is present.
  Their Metadata tabs should be read-only for date editing. Report Rejects as not
  exercised if empty; no need to reject a photo just for this check.
- **g.** On `md-exif-only.jpg`, repeat an edit/preview at 200% desktop zoom. All confirmation and cancel
  controls should remain reachable; cancel if you do not want another date change.

After acceptance: reconcile docs/backlog, commit and push this branch, require GitHub
checks to pass, then review and merge. The reported-fix batch also changes engine preview
name selection and API outcomes; metadata/API regressions supplement the browser checks.

## Incomplete photo/XMP transfer retry

<a id="pair-retry"></a>

**Record:** Accepted: R1–R3 and delivery-status follow-ups, 2026-10-15.

Manual visual acceptance: **R1–R3 passed**, confirmed by the maintainer on 2026-10-15.
The steps below remain the regression checklist; S1–S3 also passed. To repeat,
use only the prepared generated-failure fixture.
Do not damage a real library to manufacture an error.

1. **R1 — Inspect and cancel.**
   a. In Not organized, search `photo-000.jpg` and open its information pane after
      the fixture's first Copy has failed publishing XMP.
   b. Confirm **Photo/XMP transfer incomplete** includes the recorded failure.
      Open **Retry photo/XMP transfers**. For the fresh generated XMP failure, expect
      **Transferring XMP**, a green destination photo labelled **Verified at destination**,
      and an amber destination XMP labelled **Delivery incomplete — file may be partial**.
      Source originals stay neutral. All four paths are visible; Source and Destination
      have headings and a divider. The explanation says destination paths are intended
      locations and results come from the last recorded job, not a fresh check.
      Older records without delivery evidence show amber unconfirmed results rather than
      invented success. Check the same Source/Destination separation in Photo information
      and Logs.
   c. Choose **Retry Copy**, then Cancel. Both source files and the failure remain.
      Check the dialog at normal size, 200% zoom and a narrow window.
2. **R2 — Retry Copy.**
   a. Select that photo in the gallery; the selection bar offers a separate retry
      count, while ordinary Copy/Move eligibility remains unchanged.
   b. Confirm Retry Copy. Follow the new job to completion; the photo enters Library
      and its pair issue disappears. Both originals remain in the generated source.
3. **R3 — Retry Move.**
   a. On `photo-001.jpg`, use the fixture's initial failed Move. The retry must say
      **Move**, explain removal after both destination files verify, and offer Cancel.
   b. Confirm Retry Move. The pair enters Library and both generated source files
      disappear only after verified completion. Earlier failure history stays in Logs.

## Metadata setup and Settings

<a id="metadata-settings"></a>

**Record:** Accepted: S1–S3. Later Metadata tab/setup improvements also passed under readability below.

Manual Settings acceptance **S1–S3 passed**; the later warning
classification check **W1** below also passed. R1–R3 and S1–S2 passed on
2026-10-15; no repeat of those tests is required for current-build acceptance. S1 feedback:
metadata questions now have their own Metadata setup step and Settings tab. The
six-step layout and message readability changes need separate acceptance below. For a future S1 regression run, use a separate fresh generated
catalog. Do not reset a working library.

1. **S1 — Setup choice and defaults.**
   a. In the fresh setup's Files step, choose small-image reminders On or Off and select
      Next. On the Metadata step, leave the shared-XMP choice empty. Next must identify the required choice and focus it.
   b. Choose Ask me. Confirm the visible source priority, explicit-empty rule, RAW XMP
      default, and JPEG-only embedded limit. Move Next then Back: your choice remains.
   c. Finish setup; open Settings → Metadata. The same choice and explanations remain.
2. **S2 — Settings drafts and running jobs.** Maintainer passed on 2026-10-15,
   confirming the saved-settings notice during a running job.
   a. Change the shared-XMP preference, switch tabs and return. The draft and unsaved
      dot remain. Reset restores the saved choice.
   b. With an Index or Copy running on generated photos, open Settings. The notice at
      the top says saved processing changes affect future jobs, not this one, on every tab.
   c. Save a preference while the job runs. The confirmation repeats the boundary.
      When the job completes, the notice changes in place without shifting controls or
      losing unsaved drafts. Appearance/review reminders still apply immediately.
3. **S3 — Scope and layout.** Maintainer passed; retained as a regression checklist.
   a. Save a different shared-XMP preference and reopen Settings to verify persistence.
      This does not switch a photo's existing primary or rewrite recorded ownership.
   b. Confirm unresolved files are described as source attention and the per-file choice
      limitation is explicit. Embedded RAW cannot be enabled from this screen.
   c. Check Files and the job notice at normal width, 200% zoom and a narrow window:
      labels, explanations and Save/Close remain reachable without horizontal overflow.

## Informational metadata warnings

<a id="reader-warnings"></a>

**Record:** Accepted: W1 passed.

Manual **W1 — Warning-only photo can be organized** (maintainer passed; retained as
a regression checklist):

a. Reindex an existing warning-only photo, then locate it in Not organized. A reader
   warning alone should no longer put it in Needs attention or prevent Copy.
b. Open Metadata: the MakerNotes explanation appears under Metadata notes; expand
   Technical details for the exact diagnostic.
c. Copy that photo. Confirm it reaches Library and still shows the note. An unrelated
   suspicious-date warning remains separate; no metadata values are repaired or edited.

R1–R3, S1–S3, D1 and W1 acceptance passed. No manual checks remain for this batch.

## Date information and source attention

<a id="date-source-attention"></a>

**Record:** Accepted: D1, including D1c, passed.

Manual **D1 — Date information and source blockers** (maintainer passed all steps,
including D1.c; retained as a regression checklist):

a. Confirm the filter now reads **No usable capture date**. Select it and check the
   guidance explains that missing dates alone do not prevent Copy or Move.
b. Open a source photo with a date issue from **Needs attention**. Its File information
   pane should explain the specific issue once under **Needs attention before
   organizing**, identify the affected file and give the resolution. If it also appears
   under No usable capture date, that is the same photo with two applicable properties.
c. Open a photo with a usable XMP filing date but no EXIF Date taken. Its date should
   appear without an incorrect missing-EXIF warning. Automated coverage also checks
   this case; no need to manufacture a new fixture if none is in the current catalog.

R1–R3 and S1–S2 remain accepted; do not repeat them for this wording change.

## Settings grouping and message readability

<a id="readability"></a>

**Record:** Accepted: Tests 1–4, all steps, 2026-10-16.

**Manual acceptance passed (2026-10-16): Tests 1, 2, 3 and 4, all steps.** No manual
checks remain for this batch. The steps below are retained for future regression checks.
Use the existing review demo for Tests 1, 3 and 4 and a separate fresh-setup instance
for Test 2. Do not reset the existing library.
The prepared demo has `photo-000.jpg` in Library with XMP Date taken
`2005-03-04T05:06:07`; the filename and location were verified before requesting checks.

1. **Test 1 — Settings.**
   a. Open Settings. Expect Appearance, Files, Metadata, Backups, Performance and
      Access. Metadata controls no longer appear in Files.
   b. Open Metadata. Read the source priority, shared-sidecar choice and edit defaults.
      Confirm the text is understandable and clearly separated.
   c. Change a preference without saving, switch tabs and return. The draft remains
      and Metadata shows an unsaved dot. Use Reset to restore the saved settings.
2. **Test 2 — Fresh setup.**
   a. On the separate setup instance, choose Create new catalog and Next. Choose
      small-image reminders On or Off in Files, then Next.
   b. Expect Step 3 of 6 Metadata. Leave the required sidecar choice empty and select
      Next: the choice is identified and focused, with no advance.
   c. Choose Ask me, go Next then Back. Your choice remains. Finish setup if desired;
      no Index or Copy is needed for this check.
3. **Test 3 — Photo and job explanations.**
   a. In the existing demo's Library, search `photo-000.jpg`. Open Metadata, then
      Edit metadata date beside Date taken. Read the source/date/location guidance;
      cancel without saving. Check the Similar photos tab's explanation as well.
   b. Open Logs, choose Failed only and expand the latest Index job with failures.
      Check that the guidance explains why old failures remain and when retry helps.
      Open the notification bell's Details to confirm recorded causes remain readable.
4. **Test 4 — Formatting.**
   a. Repeat Settings → Metadata and the date dialog at 200% browser zoom and in
      dark mode. Text should wrap, paragraphs have clear gaps, and controls remain usable.
   b. In Logs, switch between All status and Failed only. The filter controls should
      stay in place despite the different explanation.

No destructive or file-editing acceptance actions are required for this readability batch.

## Expanded photo Inspector

<a id="expanded-inspector"></a>

**Record:** Accepted: Tests 1a–3b passed.

**Manual acceptance complete:** the maintainer confirmed all posted steps, Test 1a
through Test 3b, passed. No manual checks remain for this batch. Use the existing demo; no reset, Index or Copy is needed.
`photo-000.jpg` was verified in Library, Copied, with XMP Date taken
`2005-03-04T05:06:07` and three recorded matches at 75% before requesting these checks.

1. **Test 1 — Two panes.**
   a. In Library, search `photo-000.jpg`, open its card, then click the large preview.
      Expect the photo on the left and information/Metadata/Similar photos on the
      right, without the gallery or another details section beneath the image.
   b. Switch all three tabs and drag the divider. Similar photos identifies the
      large image as Reference photo and keeps its matching controls on the right.
      Choose 75% to see the three recorded candidates for this generated photo.
   c. Press Escape. Expect the normal gallery Inspector with the last tab retained.
2. **Test 2 — Browse photos.**
   a. With `photo-000.jpg` still open, clear the filename search so the gallery has
      other photos. Choose Metadata and enlarge the preview again.
   b. Use Next photo, then Previous photo. The expanded view stays open, Metadata
      stays selected, and Previous returns to `photo-000.jpg`.
3. **Test 3 — Dialogs and reflow.**
   a. On `photo-000.jpg`, expanded Metadata → XMP Sidecar Primary, choose Edit metadata
      date, then Cancel without saving. Expect to return to expanded Metadata.
   b. Check the expanded view at 200% browser zoom and in dark mode. Panes may stack
      at narrow widths; text and controls remain reachable. Close returns to the gallery.

## XMP import choices and history

<a id="xmp-choices"></a>

**Record:** Accepted as recorded below; corrected 2b has automated coverage and its source-only state was not required to be recreated.

Maintainer acceptance: Tests 1a–1c, 3b and 4a–4d passed. The fixtures have already
been copied; no repeat Copy, reset or Index is needed. Corrected Test 2b has automated
browser coverage; its original source-only state no longer needs manual recreation.
Maintainer Tests 5 and 6 also passed. Earlier checks remain accepted.
Maintainer Tests 7a/7b and all Tests 8a–8g passed. The proposed compact single-photo exit prompt is separate UI polish, not an outstanding validation step.

**Test 1 — Shared sidecar ownership**

- **1a.** In Not organized → Needs attention, search `choice-shared.jpg`, open it, and
  choose **Resolve XMP choices…**. Expect `choice-shared.jpg` and `choice-shared.png`
  as unchecked candidates for `choice-shared.xmp`.
- **1b.** Select only `choice-shared.jpg`, then Preview choice. Confirm that the owner
  list contains only that photo. Resize the window; the confirmation must remain open.
  Choose Decide later, reopen, and confirm nothing was saved.
- **1c.** Choose the JPG again, preview and Save choice. Expect confirmation that source
  files are unchanged and Copy/Move applies the choice. Close and reopen: ownership is saved.

**Test 2 — Competing XMP versions**

- **2a.** Search `choice-versions.jpg` in Not organized → Needs attention. Open Resolve
  XMP choices. Compare recorded fields: `choice-versions.xmp` has Date taken
  `2011-03-04T05:06:07`; `choice-versions.XMP` has `2012-04-05T06:07:08`.
- **2b.** Choose the uppercase `.XMP` version and preview. Expect the 2012 filing date,
  a reminder that no file moves now, and a separate Save choice action. After saving,
  expect **XMP choices saved**, the chosen version and 2012 date, with no radio choices
  or further Save prompt. Close and reopen: the saved summary should remain. For a photo
  already saved during testing, reopening is sufficient; do not save again. Optional
  **Change XMP version…** opens editing deliberately; closing it leaves the saved choice intact.
  After closing the dialog, Proposed destination should contain
  `library/2012/04/05/choice-versions.jpg`, not Undated. No Copy or repeat save is needed.

**Test 3 — Apply through Copy**

- **3a.** In Not organized, select `choice-shared.jpg`, `choice-shared.png` and
  `choice-versions.jpg`, then Copy selected. Expect all three to reach Library.
  `choice-shared.jpg` uses 2010-02-03; `choice-versions.jpg` uses 2012-04-05.
- **3b.** In Library, open each JPG's Metadata tab. Expect its imported XMP to be Primary;
  the choice warning is gone. The PNG has no sidecar primary. Originals remain in the
  source because this was Copy. No existing Library photo should acquire import controls.

**Test 4 — Saved choices and applied history**

- **4a.** In Not organized, open `choice-versions.jpg` (or Library if already copied).
  In File information, use **View lineage tree**, then expand **Metadata choices**. Expect
  **Saved primary for import**, `choice-versions.XMP`, its 2012 date, save time and
  choice number. The saved entry says **No files changed**, even after a later Copy.
- **4b.** Choose **Open in the log**. The photo-filtered Logs page shows the same
  saved choice after expanding **Metadata choices**. After Test 3, it also shows **Applied metadata
  during import**, the choice number and a link to the Copy job. Open that link: it
  filters to that job and explains why saved choices are excluded by the job filter.
- **4c.** Open `choice-shared.png` (Not organized or Library). Its lineage's Metadata
  choices, when expanded, should show the saved ownership of `choice-shared.xmp` for
  `choice-shared.jpg` only. After Test 3, the PNG has no applied-XMP entry; the JPG
  has an applied entry linking to its Copy job. Earlier choices remain history if revised.

- **4d.** In Library, open `choice-versions.jpg` → **View lineage tree**. Metadata
  choices starts collapsed. Expand it to see the same saved/applied history. Close and
  reopen the lineage: it starts collapsed again. Use **Open in the log**; Metadata choices
  also starts collapsed there and remains available to expand. Tests 4a/4b stay passed.

## Saved-choice metadata comparison

<a id="choice-comparison"></a>

**Record:** Accepted: Test 5 passed; visibility feedback was separate.

**Test 5 — Compare a saved choice without changing ownership**

- **5a.** In Library, search `choice-shared.png`. Open File information → View lineage
  tree → expand Metadata choices → Compare metadata… on its saved ownership entry.
  Expect the PNG name, the recorded `choice-shared.xmp`, and a clear statement that
  it was assigned only to `choice-shared.jpg`, not applied to this PNG.
- **5b.** Compare Current primary against Recorded XMP. The recorded XMP Date taken
  is `2010-02-03 04:05:06`. Toggle Show differences only; differing fields stay visible,
  equal fields disappear. Missing values say Not recorded, not Empty. No editing or
  Save action appears. Resize or use 200% zoom; the dialog remains usable.
- **5c.** Close the comparison, then choose Open in the log from lineage. Expand
  Metadata choices and reopen Compare metadata…. It still compares the PNG, not the
  JPG. Close it and inspect the PNG's Metadata tab: no sidecar has been associated.
  Earlier Tests 1–4 remain accepted; no repeat import is required.

## Portrait sizing, choice visibility and inline rotation

<a id="portrait-and-rotation"></a>

**Record:** Accepted: Tests 6, 7 and 8a–8g passed; the compact unsaved-turn redesign remains separate.

**Test 6 — Enlarged portrait fits the window**

- **6a.** In Library, search `orientation-7.jpg` and click the large preview to enlarge
  it. Confirm the entire photo is visible, including its top and bottom, without cropping.
- **6b.** Scroll the information pane. The full photo should remain visible in the
  wide layout. Resize the window and try the divider; it should scale to fit its area.
- **6c.** Close the enlarged view. Confirm the normal preview also shows the whole photo.
  This changes viewing only; no photo files or orientation metadata are modified.


**Test 7 — Find Metadata choices**

- **7a.** In Library search `choice-versions.jpg`, open its lineage, then Open in the log.
  Metadata choices should be easy to spot as a distinct section, collapsed initially.
- **7b.** Expand it with a click or Enter. Saved/applied entries and Compare metadata…
  should work as before. Collapse it again; try a narrow window.

**Test 8 — Inline rotation (8a–8g passed)**

Use Library photos `choice-versions.jpg` and `orientation-7.jpg`. Tests 1–7 remain
accepted. These steps save Orientation only; no reset, Index or Copy is needed when
these files are already organized.

- **8a.** Open `choice-versions.jpg` in Library. Click the curved **Rotate right** arrow
  beside the large preview. The photo turns in place, without another popup. Save rotation
  and Reset appear, and the target says XMP Sidecar. Reset restores the starting view.
- **8b.** Turn right again, click the large preview to enlarge it, then Save rotation.
  Wait for Rotation saved. Close the enlarged view and reload: the preview and thumbnail
  retain the turn. Metadata shows Orientation in the same primary source; the date and
  filing location stay unchanged. Turn left and save to restore the starting orientation.
- **8c.** Make an unsaved turn on `choice-versions.jpg`, then Next photo. Return to photo
  preserves the turn. Try clicking another gallery photo, then Discard viewing turns and
  leave. It opens that photo without saving. The same decision protects close/Back.
- **8d.** On `choice-versions.jpg`, open Similar photos → Review side by side. Each preview
  has curved arrows and its own Save rotation/Reset. Save a right turn on the reference,
  then save a left turn to restore it. Turn reference and candidate without saving,
  navigate to another candidate, then Back or Escape: both turned photos appear in the
  exit decision. Discard viewing turns and leave; neither temporary turn is saved.
- **8e.** Select `choice-versions.jpg` and `orientation-7.jpg` in Library. Rotate… still
  opens a bulk dialog. Uncheck one before turning; only the checked preview should turn.
  Reset should affect only checked photos too. Uncheck both: turn/reset/save should be
  disabled. Recheck one and save; only that photo changes. Restore it with the opposite turn.
- **8f.** On `orientation-7.jpg`, repeat viewing turns in the normal and enlarged preview
  at 200% zoom or a narrow window. The whole image fits; arrows, Save/Reset, target and
  results remain accessible. Reset without saving. Open View job details from a saved
  rotation and confirm the job reports its result.

## Rotation history follow-up

<a id="rotation-history"></a>

**Record:** Accepted: 8g passed.

Rotation history follow-up **8g**: open `choice-versions.jpg` after a saved rotation.
In **File information → History**, **View lineage tree**, and **Open in the log**,
confirm the successful rotation says **Rotation saved**, not Moved. Existing saved
rotations also use this wording; no fresh Index or Copy is needed.

## Edits that create identical photos

<a id="edit-duplicates"></a>

**Record:** Accepted: 9a–9d passed.

**Test 9 — Confirm an edit that creates an identical photo (9a–9d passed)**

Use the generated `dedup-rotate-edit.jpg`, `dedup-rotate-keep.jpg`,
`dedup-date-edit.jpg` and `dedup-date-keep.jpg` fixtures. These are generated JPEGs;
whole-file equality is intentional only after the requested edit. Do not substitute
ordinary look-alikes. Earlier Tests 8a–8g remain passed.

- **9a — Prepare:** Index and Copy the new fixtures. In Library, search
  `dedup-rotate-` and confirm both filenames appear. Repeat with `dedup-date-`.
- **9b — Rotation:** Open `dedup-rotate-edit.jpg`, rotate right once, then choose
  **Save rotation**. The inline confirmation must name `dedup-rotate-keep.jpg`,
  explain which copy is removed and state that histories/XMP are preserved. Cancel
  first: both photos must remain. Save again and choose **Save and keep existing
  photo**. The existing photo opens and keeps its original name/location. Library
  search `dedup-rotate-` now has one organized photo. The confirmation stays beside
  the rotation controls; no separate rotation dialog should open.
- **9c — Date:** Open `dedup-date-edit.jpg` → Metadata → **Edit metadata date…**.
  Enter `2010-02-03T04:05:06` and preview. It must name `dedup-date-keep.jpg` as the
  survivor and show that file's location. Nothing is removed during preview. Confirm
  **Save and keep existing photo**. Open the surviving photo from the result;
  Library search `dedup-date-` must show one organized photo.
- **9d — History:** For each surviving `dedup-…-keep.jpg`, open Logs and lineage.
  The saved action must say Rotation saved or Date saved and explain which existing
  photo was kept. Both source histories remain accessible. The job's **Show these
  photos** link must include the survivor. Source originals remain; do not run Move
  as part of this manual check.

## Changing an organized photo’s primary source

<a id="primary-source"></a>

**Record:** Accepted: 10a–10e passed.

Maintainer confirmed all Test 10 steps (10a–10e) passed. Tests 8a–8g and 9a–9d
remain passed. No manual checks remain for this primary-source batch.
The generated `primary-sources.jpg` fixture has three deliberately different dates:
XMP Sidecar **2021-02-03 04:05:06**, Embedded XMP **2022-02-03 04:05:06**,
and EXIF **2023-01-15 09:30:00**. Search by that exact filename, not a source path.
It is prepared with `tests/browser/import_choices_fixture.py <owned-output> --primary-only`.

- **10a — Prepare and inspect:** Run Index, then Copy. In Library, search
  `primary-sources.jpg`, open it and select Metadata. XMP Sidecar initially has the
  Primary badge. Viewing EXIF or Embedded XMP does not move that badge. On either
  alternative tab, Use as primary appears above the fields; the primary tab has no
  active link. Date copying remains a separate link beside Date taken.
- **10b — Preview and cancel:** On EXIF, choose Use as primary. Confirm the preview
  shows 2021 → 2023 and a resulting folder ending `2023/01/15/primary-sources.jpg`.
  Cancel. XMP Sidecar remains primary and the photo stays in its 2021 folder.
- **10c — Confirm EXIF:** Repeat 10b and choose Change primary and move file. Wait
  for Primary source changed, then Close. EXIF has the Primary badge; Photo information
  shows the 2023 date and destination. Reopen Metadata: Edit metadata date belongs to
  EXIF. Other source values remain readable.
- **10d — Other sources and return:** Choose Embedded XMP → Use as primary and confirm.
  Check the 2022 date/folder. Then choose XMP Sidecar → Use as primary and confirm.
  Check the 2021 date/folder and Primary badge. Refresh: Sidecar remains primary.
- **10e — History and layout:** Open this photo's Logs and expand its metadata jobs.
  Each operation says Metadata source changed. Reopen a primary preview; resize the
  window or use 200% text scaling. Read all differences/paths and reach Cancel/Save
  without horizontal clipping. Cancel to leave the photo as it is.

## Low-detail matches

<a id="low-detail"></a>

**Record:** Accepted: Tests 1a–1c and 2a–2b passed. Counts apply to its prepared fixture only.

Maintainer validation passed (Tests 1a–1c and 2a–2b). To repeat it on a fresh review
instance, after its Index/Copy:

**Test 1 — Notes without hidden matches**

- **1a.** In Library search `scn-low-detail-moon.png`, open it and choose Similar photos.
  At 90%, expect two matches: `scn-low-detail-moon-brighter.png` and
  `scn-low-detail-lamp.png`. Both show 100% and the muted mostly-dark-or-plain note.
- **1b.** Open the lamp match side by side. Confirm the note appears in the review's
  status line, the full photos remain visible, and next/previous still works.
- **1c.** Increase browser zoom to 200%. Confirm the note and controls remain readable;
  return to normal zoom afterward.

**Test 2 — Catalog health**

- **2a.** Open Stats → Catalog health. Confirm Low-detail photos shows **5** in the
  prepared generated review library.
- **2b.** Search `scn-low-detail-city.png` and `scn-low-detail-flat.png` in Library.
  Both are still ordinary photos you can open; neither is automatically rejected.

The generated moon versions depict the same scene. The streetlight is a different
scene with the same coarse hash; 100% is not proof of identical photos. Expected
counts here assume the generated scenario library prepared for this review.

## Similarity acceptance, 2026-09-29

<a id="similarity-2026-09-29"></a>

**Record:** Accepted historical functional results; not a scale-performance sign-off.

Reported against the validation branch after the destination and UI updates:

| Check | Reported result |
| --- | --- |
| Index and Copy | Completed without errors |
| Destination files | Present |
| Similar threshold filtering | Adjusts results as expected |
| Page refresh | Selection remained |

These are manual functional results, not measurements of match accuracy or query
performance. These checks preceded the 75% floor. Destination-query performance at
250,000 records remains unvalidated.

## Similarity acceptance, 2026-10-01

<a id="similarity-2026-10-01"></a>

**Record:** Accepted historical functional results; not a scale-performance sign-off.

The maintainer reports all steps validated for defaults/preferences, identical and
partially overlapping sets, filtering/counts, comparison and restoration, and
selection. Previous/next set and Show this set in gallery also work.
After receiving the detailed instructions, the maintainer confirmed all Copy review
link steps validated.
The maintainer reports recovery/logging passes: logs now explain what failed and
why. Desktop zoom/reflow also passes: the screen scales to 200% and windows adapt.
This completes the agreed manual functional checklist. Automated results above
remain separate evidence. Representative 200,000+ photo capacity, dense matching
and long-session performance remain outstanding; this sign-off does not establish
those limits. The maintainer subsequently authorized documentation cleanup, merge
into main and push.
