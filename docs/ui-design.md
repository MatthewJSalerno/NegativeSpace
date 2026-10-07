# NegativeSpace UI design standard

This document defines the shared appearance and interaction contract for the web
interface. The target is WCAG 2.2 Level AA. Automated regression checks cover the
behaviors listed below; full conformance additionally requires assistive-technology
and manual review. This document does not claim certification.

Desktop browsers are the required product target. Mobile support and real
touch-device validation are optional and do not block release. Existing responsive
behavior may remain, but it does not establish a mobile support commitment.
Desktop zoom, text scaling, keyboard access and reflow remain accessibility concerns,
including when zoom or a resized desktop window activates a narrow layout.

## Visual language

Keep photographs prominent, with neutral surfaces, restrained borders, and one blue
accent. Use semantic CSS custom properties in `webui/frontend/src/styles.css` rather
than choosing new colors in a screen. Error text and destructive button fills have
separate foreground/background pairs in both themes.

- Spacing: 4, 8, 12, 16, 24, 32 and 48px tokens for controls, panels and section gaps.
- Controls: 36px minimum height, increasing to 44px below 800px and for coarse pointers; compact
  information and disclosure buttons remain distinct from primary actions.
- The toolbar selection summary fits the existing row height when its content
  fits on one line, retaining full-height button targets. Longer content may wrap.
- Typography: locally bundled Inter with 400/600 weights; 12, 14, 16 and 20px sizes
  expressed in rem against the user's default root size. Counts use tabular numerals.
- Controls use 6px corners; panels use 10px corners. Inputs retain distinct outlines;
  secondary buttons use neutral hover surfaces. Keep hairlines for content divisions
  rather than framing each label, filter or metadata row. Native disabled states and
  visible focus remain intact.
- Native checkboxes use 24px glyph targets; labels expand the selectable area.
- Focus must remain visible below sticky headers. Forced colors retain outlines and
  borders; reduced motion suppresses nonessential animated progress effects.
- On narrow screens the toolbar scrolls with the page, so its wrapped controls
  cannot cover the gallery; command menus stay within the viewport.
- Normal enabled text needs 4.5:1 contrast; inspect nontext controls and state
  indicators separately. Disabled controls are not a reason to weaken enabled ones.

These are product choices within an accessibility target, not a claim that every
control must have the same shape or that every target must be exactly 44px.

Use the same text roles on every screen:

| Role | Size and weight |
| :--- | :--- |
| Page and dialog titles | 20px / 600 |
| Section titles, including filter trees | 16px / 600; compact subsections and Inspector headers use 14px / 600 |
| Body, labels and standalone controls | 14px / 400; emphasis uses 600 |
| Supporting details, badges and counts | 12px / 400; emphasis uses 600 |

Text buttons embedded in a sentence inherit its size and line height, just like
anchors. A file path inherits its surrounding text size rather than introducing a
second font or larger text into a compact history line. Adjacent navigation and
action links share alignment and target height even when one is an anchor and the
other is a button. Preserve these roles at desktop zoom and narrow widths; do not
add screen-specific font sizes to repair a shared control.

Tabs are one shared control (`ui/Tabs.tsx`, WAI-ARIA "Tabs with automatic activation"):
one tab stop, ← → move and choose, Home/End go to the ends. The Inspector and Settings
use it. Settings' tabs and first-run steps are the same four groups (`webui-spec.md` §3);
a tab with unsaved changes shows a dot, named "unsaved changes" to assistive technology.

The first Settings tab, Appearance, offers Cool neutral (default) and Warm neutral palettes. The choice applies
immediately, is stored per browser under `ns.palette`, and follows across tabs;
it is independent of catalog settings and does not require Save settings. System
light/dark preference applies to either palette. If browser storage is unavailable,
the choice still works for the current page. All colors come from the shared root
tokens; the font is served with the app, with no external font request.

Help popups use the subdued `--surface-2` background and normal text color in both
themes. They occupy the browser's top layer so sticky sidebars and adjacent photos
cannot clip or cover the text.

## Shared controls

| Element | Contract and implementation |
| :--- | :--- |
| Navigation | Real anchors with destinations and modified-click support; current page indicated. A skip link reaches the main region. |
| Buttons | Native buttons, primary/secondary/quiet/destructive CSS variants; verb labels. Disable submission while pending. A photo's own action standing alone on a white panel (the Inspector's **Reject…** and **Return to library…**) is outlined with `--control-border`, as fields are: quiet, it read as plain text and was missed. |
| Selects | Native select for sort and page size. Menus execute commands and are not substitutes for form selects. |
| Search fields | `ui/SearchField.tsx` for every search and filter box: a **Clear search** button (×, with the field's own name where it filters something else) appears once there is text, clears it and keeps focus in the box; Esc does the same before reaching the dialog or panel around it. The browser's own clear button is hidden, since only some browsers draw one. *From:* [Carbon search](https://carbondesignsystem.com/components/search/usage/). |
| Fields | `ui/Field.tsx`: persistent label, hint and field error linked to the input, plus invalid state. Required choices say **(required)** in the visible label and use native `required` semantics; do not wait for an error to reveal the requirement. Keep server validation. |
| Checkboxes | Native input and label, Space activation, actual indeterminate state for partial parents. Selecting photos differs from filtering the view. |
| Filter trees | Consistent rows, counts and focus. Folder/type labels filter; date-name buttons jump and carry an arrow cue. Parent/child inclusion rules remain those in the web spec. |
| Menus | `ui/MenuButton.tsx` manages focus, item traversal, nested scopes and dismissal. Domain components provide labels, counts, reasons and callbacks. |
| Dialogs | `ui/Modal.tsx` uses native modal dialogs and top-layer inertness. Desktop Inspector stays nonmodal; on narrow screens its covering panel becomes modal. |
| Supplemental help | `Tip.tsx`: hover/focus plus an explicit information button for touch; real text, a description relationship, Escape dismissal and pointer-accessible content. Essential guidance stays in the page. |
| Paged loading | `ui/PageBoundary.tsx` and `paged.ts`: idle/load, pending, failed/retry and end states. Keep already-loaded photos and selection on failure. |

## Workspaces

The Library is for finding photos; a **workspace** is for working on them. Deep tasks
(comparison now; EXIF editing, copying details, bulk edits and Needs review later) use
the shared frame in `ui/Workspace.tsx`, never a screen-specific layout. *Why a full window
rather than a large dialog:* a task too big for a modal belongs on a page of its own
([Carbon](https://carbondesignsystem.com/patterns/dialog-pattern/)), and photo tools give
their editing view the whole window (Lightroom's Develop, Immich's viewer).

- **One frame.** A header with **← Back to gallery**, the task title (20px / 600) and its
  subject in supporting text, a **‹ n of N ›** step control naming the position, and the
  task's main actions on the right; then the task's content; then a status line for
  progress, counts, unsaved changes and errors, with the keyboard hint at its end. The
  task supplies only the content, the subject, the step labels and the status.
- **Full window, one scroll.** The frame fills the window with no gutter and scrolls as a
  single container; the header and status line stay in view (sticky), with scroll padding
  so focused controls never hide behind them. No inner vertical scroller is added for the
  content.
- **Over the Library, not instead of it.** The frame is a native modal (`ui/Modal.tsx`) over
  the mounted Library, so Back returns to exactly the filters, scroll position and
  selection the user left, the Library is inert while the workspace is open, and focus
  returns to the control that opened it. Its state belongs in the address so reload and
  links restore it (the comparison's `review` state).
- **Keyboard, in every workspace:** Esc goes back, as Back does. ← → step through the
  task's items (candidates in comparison), stop at the ends, and never act while focus is
  in a control that uses the arrows itself (fields, selects, tabs, sliders, dividers,
  menus) or while a dialog over the workspace is open. Step buttons carry the item's name
  ("Previous candidate") and the shortcut in their tooltip. *From:* Immich's viewer (Esc
  leaves, arrows step and stop at the ends) and Lightroom's single key back to the grid.
- **Leaving with unsaved changes** (with the first editing workspace): "Leave without
  saving?" / "All unsaved changes will be lost." / **Keep editing** (initial focus) ·
  **Discard**. Never save automatically.
- **Narrow windows:** the header wraps (title and subject, then the step control and
  actions); the frame never scrolls sideways.

## Rejecting while comparing

Decided with the maintainer (2026-10-01) and drawn in the PR 3 mockup. A photo's own
action sits under that photo (`photo-action`, outlined), never in a shared header, so it
is clear which one goes. Asking once per comparison (**Don't ask again while comparing**,
reset when it closes) keeps culling quick; leaving none of the compared photos in the
library always asks, because that is the one reject a person may not intend. The photo
kept in **Keep this one, reject the rest** is marked **Keeping** in `--good` with a check
and is shown full size first in the review: the photo kept must be easy to check, never the
smallest thing on screen. No keyboard shortcut for reject (maintainer's choice).

**A photo's history has three views, each with its own job** (confirmed 2026-10-05; not
duplicates): the photo panel shows the photo's information and leads to everything about
it; the **lineage tree** traces the photo back to its origin through every file and copy;
the **log** shows the jobs and the work each did. Keep each to its job rather than merging
them.

**One "Reject?" dialog everywhere** (decided 2026-10-05). Every reject question, from the
gallery, the photo panel, the comparison or Needs review, is the same dialog with the same
wording, spacing and button order: the title names the photo ("Reject IMG_0412.jpg?", or
"Reject 12 photos?"), then "It moves to the Rejects folder and leaves your library. You can
bring it back any time until you manually empty Rejects.", Cancel focused first. Two parts
appear only where they apply: **Don't ask again while comparing** in the comparison, and
the last-photo warning ("None of these photos would be left in the library") with **Reject
it too** as the button. *Why not a dialog per screen:* two separate ones already drifted
and had to be reworded in both places.

## Similarity belongs in the gallery

Review destination photos in the ordinary gallery and its Inspector. Do not add a
separate Similar navigation button or a second gallery of matching groups.
**Has similar photos** is a filter chip within the current place;
it includes photos with at least one recorded destination match at the gallery's
chosen percentage (90% initially). It combines with existing search, date, type and
folder filters. **Most matches first** in the existing sort control ranks direct
match counts highest first; ties use ascending photo ID. **Matches at or above**
in the gallery summary offers 75/80/85/90/95/100%, also available with the other gallery sorts.
A visible **Most matches first** shortcut applies the same sort. Cards show compact
match-count badges over the preview, with the percentage in their tooltip. Count matches across the whole destination
library, including outside gallery filters, and explain that scope in the shared help beside results.
Photos with no qualifying recorded match are excluded; incomplete comparisons and
unavailable hashes are reported separately, not presented as proof of uniqueness.

Keep the same card geometry and shared summary row in All photos, Has similar
photos and No capture date. Match badges must not add a metadata row to cards.
Use the same active-view surface for No capture date. Put long filter descriptions
and count-scope explanations in shared help, keeping filter-reset/selection actions
visible. Similarity controls and essential below-90% guidance may wrap at smaller
widths; never hide them behind a help control or clip them for a fixed row height.

Persist gallery percentage as `match_min` and ordering as `sort=matches` in the URL.
Changing either starts at page one and preserves explicit selection. Sidebar counts,
Select all and photo positioning use the same percentage. Show only selected retains
all chosen files, including those without matches; disable the gallery percentage
while that scope is open. Has similar photos initially uses Most matches first. Remember explicit sort choices
per view in browser storage (`ns.sort.<view>`); switching views restores that view’s
last order. An explicit URL sort wins without rewriting the saved preference. Clicking a gallery card carries the gallery percentage into Inspector
matches and opens the **Similar photos** tab. Users can subsequently
choose another Inspector percentage without changing gallery order; previous/next
photo navigation retains that Inspector choice.

The Inspector has **Photo information** and **Similar photos** tabs. Default to
Photo information outside Has similar photos; remember the active tab and threshold
when using previous/next. A gallery-card click in Has similar photos always opens
Similar photos, even after the user switched to Photo information.
The preview and its resize divider are shared by both tabs. Tab arrow keys and
Home/End switch tabs without triggering previous/next photo navigation.

The Similar photos tab shows cumulative counts at **75%, 80%, 85%, 90%, 95% and 100%**
in its information pane. Label thresholds as “at or above”: these are overlapping
counts, not separate buckets or confidence estimates. Choosing one reveals a small,
paged thumbnail grid of direct matches in the same pane, leaving the reference photo, gallery
filters and explicit checkbox selection intact. Opening a match offers side-by-side
review. Match browsing does not designate files for rejecting or metadata edits; only
an explicit Reject or Keep this one, reject the rest does.
Association may help identify dates, events or other information, but proves none
of them. A 100% visual score still does not mean identical bytes.
Keep guidance beside the threshold controls explaining that results below 90% are
more likely to be unrelated and need side-by-side review before being used as
metadata clues. Repeat it in the comparison dialog for a pair scoring below 90%.
This is review guidance, not a measured error rate or a guarantee above 90%.

Persist the open photo, tab, chosen threshold and match page in the gallery URL.
Outside Has similar photos, opening Similar photos initially uses 90%; subsequently retain the chosen threshold
for other reference photos and reset their match page to one. Information-only
browsing does not load matching data. Match thumbnails use more columns as the
details area widens, and scroll separately so the reference preview stays visible.
A failed or unavailable hash lookup must never appear as zero matches. Show loading,
retry for request failures, and incomplete comparison states explicitly. **Review matching status** opens a paged recovery dialog from coverage notices
or the Inspector. Show affected destination photos with photo links and distinct
missing/read/decode/changed-file reasons. Offer Generate missing hashes only for files without a recorded failure, and
a separate Resume comparisons action. Known failures require the stated external
correction before an explicit Recheck file after external fix; bulk generation
must skip those failures. Explain prerequisites
for retrying changed/missing/unreadable files; unsupported formats have no futile
retry. Actions wait while another job runs. Show progress, cancellation and verified
remaining issues; resolving a warning must not close its open results dialog.
Recovery reads verified destination originals and changes only matching data.

### Expanded review workspace

**Built:** opening a candidate from the Inspector expands into a comparison
workspace (the shared workspace frame, "Workspaces" above) with an explicit reference, a browsable candidate, a paged thumbnail strip,
and a resizable information panel. It starts at the Inspector's threshold and
page. Back to gallery restores its threshold/page (page one after filtering by
review status), leaves gallery selection intact, and restores focus to the opener
when it remains present. The reference is the photo the user opened, not a donor
or a file chosen to keep.
Identify the reference with a plain bold **Reference photo** heading and an accent border
around its preview. Keep the candidate treatment neutral and the previews aligned.
The heading is informational: do not give it a button-like fill or rounded badge.
The explicit label accompanies color so the distinction survives forced colors
and does not imply the reference is a source-folder file, donor or keeper.

The candidate offers **Use as reference**. It loads direct matches for that photo,
retains the threshold, and resets to page one. The previous
reference becomes the displayed candidate, even if it is outside the new first
page. Viewing transforms follow photo identities. Focus moves to the new reference.
Disable promotion after a failed/stale pair request until refreshed. This action assigns
no keeper, donor or edit targets. Back to gallery returns to the original Inspector
photo and its entry page after exploring another reference; gallery selection
stays intact. Changing the reference is local to the open workspace.

Each preview has independent viewing rotation in 90° steps, zoom, position and
Reset view. A visible note identifies temporary rotation. Rotation fits inside
the preview even for portrait photos. Link zoom and position is optional; it never
links rotation. Viewing transforms stay associated with their photo during the
open workspace and reset on closing; they never write files, EXIF or hash scores.
A saved orientation correction remains a separate future edit.
Dimensions beneath a preview follow its viewing rotation: swap width and height
at 90° and 270°, and label rotated dimensions **Displayed**. The information pane
continues to show recorded dimensions; zoom does not change either value.

The two-photo comparison grows to fit its controls, resolution, file sizes and
linked-zoom option. Do not add an inner vertical scroller or clip those details to
reserve space for the candidate strip. When the content exceeds the window height,
scroll the review window as a whole, with the shared More above/below cues. The
metadata panel may scroll independently for long tag lists.

The information panel starts with **File and image properties**: recorded format,
extension, pixel dimensions, megapixels, file size and aspect ratio. Prefer the
recorded file type; label a filename-only fallback as extension only. Missing
dimensions stay unknown. Compare exact values before display rounding and show
exact byte counts beside rounded sizes. Mark differences neutrally, without
choosing a winner or implying larger files or dimensions guarantee quality.
**Capture information** follows, with **All recorded metadata** available below.
Differences only applies to every section; the tag search filters only the full tag
list. File-modification fallback dates are labelled; unknown timezones are not
invented. Metadata errors have a retry and do not appear as missing values.
Keep each table's **Field**, **Reference**, and **Candidate** headings visible while
its rows scroll, with an opaque theme surface. In narrow layouts they follow the
review window's scroll instead of introducing another scroll area.

The status line counts the look-alikes at the chosen threshold; each thumbnail shows
its similarity. Deciding is **Reject…** or **Keep this one, reject the rest** (see
Rejecting while comparing); there are no same / related / unrelated labels, which
changed nothing. Candidate loads cannot replace a newer navigation choice.

The gallery URL's validated `review` state restores the comparison reference and
candidate, threshold, page, divider share, linked zoom and current-pair viewing
transforms. Keep the original Inspector
context separately so Back to gallery returns there after reference promotion.
Only the current pair's transforms are bookmarked; other candidate transforms last
for the open session. Reload restores controls but fetches photo data again.
Malformed bookmarks are ignored, unavailable photos
show errors, and excessive candidate pages clamp to the current last page. Closing
removes the workspace state and discards viewing transforms. Return keyboard focus
to the opener, or a surviving match thumbnail when restoring from a bookmark.
Photo links to another Inspector photo clear the prior comparison state.

**Separate workstream (not a dependency of similarity matching):** metadata edits/copy with explicit target selection,
per-file previews and results. The reference, metadata donor and photographs to
keep are separate roles: a smaller copy can supply metadata for a larger keeper.
Opening or comparing a photo does not assign those roles. Future action targets
must remain separate from gallery selection; changing the reference or offered
match set must not leave hidden targets armed. Show proposed metadata changes
before execution and record each result. Do not show nonfunctional edit controls
while those actions are unbuilt.

**Future orientation-save interaction:** rotation remains temporary throughout
comparison. Once verified orientation writes exist, offer one decision at the end
of review for photos whose final orientation differs from their starting state.
Identify the affected reference/candidates by photo and show their final orientation;
allow saving selected changes, discarding them, or returning to review. Never save
or prompt on each Rotate click. General EXIF editing uses the shared editor rather
than turning this comparison into an inline editor. The current workspace has no
rotation-save prompt and closing it discards viewing transforms.


## Keyboard and focus

A modal shows subdued More above/More below cues at its edges when its content can
scroll in those directions. Cues are noninteractive and disappear at the corresponding end.
A modal moves focus inside, wraps Tab/Shift+Tab, and restores the opener on close
(or a logical surviving control). Nested dialogs close one at a time. Destructive
confirmations start on Cancel. Settings and confirmation cannot be dismissed while
their submission is pending. Closing a window is not cancellation of a running job;
use the job's Cancel command for that. Engine settings drafts are discarded on close;
Reset restores the saved values. Saving preserves server revision checks.

Menu Enter/Space opens on the first command. Arrow keys, Home/End and initial-letter
navigation move within a menu; Right enters a submenu, Left/Escape returns to its
parent. Escape at the top level returns to the trigger. Tab closes the menu and
continues the page's tab order. Disabled commands remain arrow-focusable to expose
reasons, but cannot execute. Pointer dismissal does not steal focus back from the
control the user clicked.

Photo navigation shortcuts must not run behind a dialog or menu. Help's Escape is
handled before its enclosing dialog. Native controls retain their normal keyboard
behavior.

Job-result explanations use plain summary text with the shared More information
button; they do not underline non-navigable text like a link. Hover and keyboard
access to the explanation remain available through the shared help control.

The Inspector's inner preview/details divider has a visible grip, pointer dragging
and keyboard resizing. Arrow keys follow its orientation; Home/End select its limits.
It announces and remembers the preview share independently of the outer panel width.
The outer divider reserves the filters' chosen width and at least 420px for the
photo grid; the Inspector retains at least 320px. Saved widths and desktop window
resizing obey those limits. Very narrow desktop windows scroll horizontally rather
than compressing these areas below their minimums.

## Validation and feedback

Settings validates whole positive worker/retention counts and a nonempty extension
selection before saving. It keeps drafts, marks affected fields, describes their
errors and focuses the first invalid control. Server errors remain visible. Success
uses a polite status, not an urgent alert. Loading failures offer an explicit retry.

Warnings that require user action must have a working resolution path. Say what is
affected, what the user can do, and provide the action or a direct link to the
relevant filtered view. A count alone is not a completed workflow. While another
job prevents the action, keep the explanation visible and explain when the action
becomes available. If the condition cannot be fixed by the app, state the limitation
instead of offering a retry that cannot help. Verify the remedy changes the reported
state; refreshing the message alone does not count as recovery.

**Say where details came from, without cluttering** (maintainer's standing preference,
2026-10-05). Where metadata is displayed, one source line per block ("Details from: XMP
sidecar · file's EXIF"), not a label on every field; mark only the values that matter: a
small **XMP** tag on a value taken from the sidecar, a file-time date marked as such, and
every suggestion with its source.

**Offer hints wherever the catalog has them** (maintainer's standing preference,
2026-10-05). When the user must decide something, show the clues NegativeSpace already
holds, each with where it came from: a date suggested from the filename, the folder or a
dated look-alike; a larger look-alike beside a small image; the reject a new photo
resembles; the original path and name a file arrived with. A hint is a suggestion the
user accepts, never a change made for them, and it names its source ("from the
filename") so it can be judged. Where no hint exists, say so rather than leaving a blank.

Continuous scrolling keeps the existing page and URL model. An appended/prepended
failure stops announcing loading, shows a readable error and waits for Retry. Retry
must preserve selection and the visible anchor; old requests must not join a new
filter or navigation range. Refresh failures also expose retry. Explicit page jumps
and load buttons remain available alongside scroll-triggered loading.

## Verification and remaining scope

`tests/browser/ui_browser_checks.py` runs through the isolated browser harness after the
existing product scenario. It exercises dialog focus and nested restoration, menus,
field errors, help, both-theme destructive contrast, failed loading, narrow-screen
layout and forced-color focus. `tests/browser/webui_browser_test.sh` is the entry point.

Before making a WCAG conformance claim for the supported desktop experience, review
all screens with a screen reader, keyboard alone and text scaling/zoom; include
desktop browser coverage beyond Chromium. Real touch-device checks are optional.
Automated checks are regression guards, not a conformance claim.

The gallery still retains its loaded pages. Long-session DOM/memory measurements and
accessible virtualization need separate work; a large SQL catalog benchmark alone
cannot validate browser performance. Navigation/query synchronization and uncertain
job-start response recovery remain separate behavioral work, not hidden by this
visual standard. Engine transfer safety and filesystem behavior are unchanged.

## References

- [WCAG 2.2](https://www.w3.org/TR/WCAG22/)
- [ARIA Authoring Practices](https://www.w3.org/WAI/ARIA/apg/)
- [Modal dialogs](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/)
- [Menu buttons](https://www.w3.org/WAI/ARIA/apg/patterns/menu-button/)
- [Native dialog behavior](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/dialog)
- [Design tokens](https://designsystem.digital.gov/design-tokens/)

## Suspicious dates

The **Suspicious dates** gallery view flags the recorded gallery date when its year
is before 1800 or more than one year ahead of the current UTC year. This is a
conservative review heuristic, not proof of an error. It includes EXIF-derived dates
and file-modification fallbacks, with their source identified in the Inspector and
comparison pane. Missing dates remain covered by No capture date; raw malformed or
conflicting EXIF tags are outside this first policy. Never infer an offset or replace
a recorded value. Legitimate historical material may still be flagged.

Use existing gallery controls, card geometry, selection, pagination and URL state
(`view=suspicious`). Counts, sidebar filters and Select all use the same membership.
Explain the policy beside results. The Inspector shows the reason, recorded value,
source and a link to the affected view. Similar photos offer clues, not automatic
corrections. The comparison Capture information table includes a Date review row
when either photo is flagged. State clearly that date editing is not yet available.
No schema changes, reindex or file writes are needed; the upper bound advances with
the server's UTC year when the catalog is read.

### Reference-based sets

Offer optional grouping within Has similar photos, retaining the ordinary per-photo
view. A set consists of its reference and every direct match at the chosen percentage.
If A matches B and B matches C but A does not match C, A's set contains A/B and B's
set contains B/A/C. A representative is a navigation reference, never a keeper.

Show inline overlap notices: A's set can say “B has additional matches outside this
set”; B's can say “Overlaps with A's set.” Offer **Review this set** to open its
reference and direct matches in comparison, and **Explore related sets** to display
related sets with their references and membership intact. Avoid repeated decision
prompts. Within exploration, **Show together** combines only sets the user chooses,
showing each photo once while preserving its relationship to the references.
Clearly distinguish indirect photos, for example “Related through B · below your
threshold for A”; never present C as a qualifying direct match to A.

These are session-only display choices, not saved groups or tags. **Group similar
photos** adds set counts and actions to the existing reference cards. Sets with exactly the same full destination membership appear once in the gallery.
Compare each closed neighborhood (reference plus direct matches) at the selected
percentage, never just match counts or a transitive component. Choose the lowest
canonical photo ID satisfying active filters as the stable representative; it is
not a keeper or the highest-quality photo. Sort the resulting representatives and
collapse before pagination. Search can choose another member as representative.
Gallery totals and paging count sets when grouping is on. Select all and card
checkboxes select only displayed representatives, not every member. Existing
explicit selection remains intact, including hidden members; Show only selected
still displays individual photos. View-button counts remain library photo counts.
Sidebar counts remain individual photos so filters can find members hidden by
collapsed sets; date-jump positioning uses grouped representatives. A set's members come from the full destination
library. Turning grouping off returns the ordinary cards without clearing selection.
Grouping defaults on and the toggle is remembered per browser (`ns.groupSets`). Selected expansions reset on closing exploration
or changing its percentage, and survive a visit to side-by-side review and back.

Explore related sets offers only the starting reference's direct-match references.
Choose up to six explicitly, then Show together. This unions their sets, deduplicates
byte identities, and shows every photo's membership in the displayed sets. Members
and related references have independent pagination (12 per page). The starting
reference sorts first, then minimum recorded distance to a chosen reference and ID;
related references sort by direct distance then ID. Counts include the reference;
match counts elsewhere exclude it. Broader graph intersections remain future work. No automatic traversal follows a newly exposed photo.

An indirect member's Compare button uses its supporting reference, not the starting
reference it does not directly match. The comparison remains the existing direct
match workspace. Returning reopens the same exploration; no comparison save is
implied. At narrow widths the covering exploration owns modality instead of opening
a second Inspector dialog over it. Failed requests expose Retry sets and Reset to
this set; stale expansions are rejected rather than silently dropped. Incomplete
coverage links to matching information and recovery. No persisted group membership,
keeper inference, EXIF editing or rejecting is introduced by exploring sets.

Review later belongs to the planned Needs review in-tray (`webui-spec.md` §7.9).
Its notes record decisions awaiting a person, with reason-specific actions and
resolved decisions retained in history. This is not a general tagging system;
computed similar-photo sets remain live queries rather than stored review notes.

### Failed visual processing

A visual-hash failure does not prove a file is not an image; absent EXIF alone is
not evidence of damage. Keep unsupported decoders, failed decoding, unreadable or
missing files, and changed content distinct. Hash-recovery failures write per-photo
Logs entries with the category and actionable reason; the Inspector and recovery
list expose the recorded issue. Decode failures ask for external viewing/repair and
retry only after fixing the cause. Known unsupported formats have no futile retry.
Keep delivered file status and photo bytes intact; missing hashes exclude files from
visual matching without hiding them from the ordinary catalog. A broader import
completion summary and catalog-wide external-review view remain pending.

The gallery similarity percentage defaults to 90% and remembers explicit user
changes in browser storage (`ns.matchMin`). An explicit `match_min` URL value wins
without overwriting that preference. Gallery and reference-set threshold controls
update the preference; Inspector/comparison thresholds remain local to their review.
The 75% floor remains available. Identical-set collapsing is implemented for the grouped gallery.

### Review links and set navigation

Copy review link serializes the current comparison directly, including reference,
candidate, threshold, current-pair viewing transforms and linked
zoom. It does not depend on a pending URL update. Report
success only after the clipboard write succeeds. If clipboard access is unavailable
or rejected (including local-network HTTP), expose a labelled, selectable read-only
link for manual copy. Recipients need access to the same instance and catalog.

Previous set / Next set in review follows the grouped gallery's percentage, filters
and sort, anchored on the entry reference even after Use as reference. Disable
unavailable boundaries and loading navigation; request failures offer Retry set
navigation. Entering another set starts a fresh comparison with temporary viewing
transforms reset.
Navigation is offered only from the grouped gallery, not an expanded union or a
set-member scope whose ordering has a different meaning.

Show this set in gallery is available from comparison and each reference in set
exploration. It shows the reference and direct members at that set's percentage as
ordinary, individually selectable cards, with server paging and normal sort controls.
This temporary scope bypasses the saved gallery filters and does not auto-select,
expand or clear the existing selection. Filters are disabled while it is open;
Back to results restores the previous gallery filters/page. Reload leaves this
session-only scope. Browsing is not limited in members. No EXIF edit, reject, image
processing or persisted group is implied.

## Places, filters and the review inbox

The navigation follows the workflow: Not organized, Library, Needs review, Rejects.
Not organized, Library and Rejects name locations; Needs review is an overlapping inbox, not a fourth physical place.
Label locations on review cards and in the Inspector/workspace. Counts count distinct
photos and must not imply the inbox adds files to the library. A new unscoped visit
starts at Not organized while Library is empty; explicit links retain their view.
Once Library exists, an unscoped visit remembers the last place in this browser.
Not organized starts with Index source. After Index, its neutral Index summary describes
remaining indexed photos, identical extra copies, size and date facts, plus a clear
Copy/Move next step using the existing confirmation. Counts cover the whole location,
not gallery filters; disabled size rules and uncalculated similarity are explicit.
An empty Library explains how to populate it and links to Not organized.

Library contains delivered, active photos only. Cards with unresolved reasons show a
Needs review link and concise reason labels. Opening it selects the relevant inbox
reason (All reasons for multiple reasons), focuses that photo in the review workspace,
and clears unrelated browsing filters so the photo cannot be hidden. Checkboxes stay
unchanged. Back to Library restores the entry filters, sort and visible photo position
for this visit. Mark reviewed clears the reminder, not the Library photo.

Place controls and filter chips have different roles. Similar photos, Suspicious dates
and No capture date are combinable filter chips beneath navigation. Needs review reason
chips select one reason or All reasons. Use native buttons with aria-pressed, shared
text roles, visible focus and wrapping at desktop zoom. Folders and Dates remain in the
sidebar. Name active restrictions visibly and provide Clear filters without changing
place or selection. Search offers a route to filename matches in other locations.

Small-image review is destination cleanup, never a Copy/Move restriction. First-run
Files labels the on/off choice **(required)**, offering an editable 800-pixel shorter-side
minimum if enabled. Settings can adjust or disable it. Mark reviewed acknowledges one
photo's size concern; it is not Keep, selection, relocation or approval of other reasons.
Checkboxes continue to select photos to Reject. Never untick photos because the app
found a larger look-alike. Review later has an optional note and Done clears it.

Use the shared Workspace for one-by-one review, with reason-specific evidence/actions,
Previous/Next, and Back to gallery. Next leaves the decision unresolved. Advance only
on an acknowledged decision or confirmed Reject outcome. Keep errors and retry paths
visible. Return to the same gallery context and preserve explicit selections.

Small-image gallery cards use the concise reason **Below minimum image size**. Keep
the detailed dimensions and configured rule in the Inspector and review workspace.
The short card reason also exposes that rule through shared `Tip` help on hover,
keyboard focus or the information button.

Keep a **Small images** shortcut beside **No capture date** in the gallery toolbar.
It opens Needs review with the Small images reason selected, preserving search,
other filters and explicit photo selection. Concise card text must not remove this
entry point; the reason chips remain available inside Needs review.
