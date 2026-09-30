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

The first Settings section, Appearance, offers Cool neutral (default) and Warm neutral palettes. The choice applies
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
| Buttons | Native buttons, primary/secondary/quiet/destructive CSS variants; verb labels. Disable submission while pending. |
| Selects | Native select for sort and page size. Menus execute commands and are not substitutes for form selects. |
| Fields | `ui/Field.tsx`: persistent label, hint and field error linked to the input, plus invalid state. Keep server validation. |
| Checkboxes | Native input and label, Space activation, actual indeterminate state for partial parents. Selecting photos differs from filtering the view. |
| Filter trees | Consistent rows, counts and focus. Folder/type labels filter; date-name buttons jump and carry an arrow cue. Parent/child inclusion rules remain those in the web spec. |
| Menus | `ui/MenuButton.tsx` manages focus, item traversal, nested scopes and dismissal. Domain components provide labels, counts, reasons and callbacks. |
| Dialogs | `ui/Modal.tsx` uses native modal dialogs and top-layer inertness. Desktop Inspector stays nonmodal; on narrow screens its covering panel becomes modal. |
| Supplemental help | `Tip.tsx`: hover/focus plus an explicit information button for touch; real text, a description relationship, Escape dismissal and pointer-accessible content. Essential guidance stays in the page. |
| Paged loading | `ui/PageBoundary.tsx` and `paged.ts`: idle/load, pending, failed/retry and end states. Keep already-loaded photos and selection on failure. |

## Similarity belongs in the gallery

Review destination photos in the ordinary gallery and its Inspector. Do not add a
separate Similar navigation button or a second gallery of matching groups.
**Has similar photos** sits alongside All photos, Organized and No capture date;
it includes photos with at least one recorded destination match at the gallery's
chosen percentage (75% initially). It combines with existing search, date, type and
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
while that scope is open. Leaving Has similar photos resets its special sort to
Newest first. Clicking a gallery card carries the gallery percentage into Inspector
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
review. Match browsing does not designate files for deletion or metadata edits.
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
retry for request failures, and incomplete comparison states explicitly. Missing-hash
repair remains unfinished as recorded in TODO.md.

### Expanded review workspace

**Built:** opening a candidate from the Inspector expands into a comparison
workspace with an explicit reference, a browsable candidate, a paged thumbnail strip,
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
retains the threshold, and resets to All candidates on page one. The previous
reference becomes the displayed candidate, even if it is outside the new first
page. Viewing transforms follow photo identities and saved judgments stay with
their content pairs. Focus moves to the new reference. Disable promotion during
saving or after a failed/stale pair request until refreshed. This action assigns
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

The Information tab starts with **File and image properties**: recorded format,
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

The Saved review tab shows the latest judgment for this content pair. All,
Unreviewed and Reviewed filters apply before server pagination. Progress counts
reviewed pairs at the chosen threshold, not photos in the entire catalog. Each
thumbnail shows its pair judgment. Saving is explicit, survives reopening, and
never marks other pairs reviewed. Moving on without a judgment leaves the pair
unreviewed. Busy saves prevent candidate/filter navigation; failures retain the
comparison and require refresh before another judgment. Candidate loads cannot
replace a newer navigation choice. Deferred queues and restoring an open workspace
across reload remain future work.

**Next stage:** metadata edits/copy and deletion with explicit target selection,
per-file previews and results. The reference, metadata donor and photographs to
keep are separate roles: a smaller copy can supply metadata for a larger keeper.
Opening or comparing a photo does not assign those roles. Future action targets
must remain separate from gallery selection and pair judgments; changing the
reference or offered match set must not leave hidden targets armed. Show proposed
metadata changes or deletion targets before execution and record each result.
Do not show nonfunctional edit/delete controls while those actions are unbuilt.

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

Continuous scrolling keeps the existing page and URL model. An appended/prepended
failure stops announcing loading, shows a readable error and waits for Retry. Retry
must preserve selection and the visible anchor; old requests must not join a new
filter or navigation range. Refresh failures also expose retry. Explicit page jumps
and load buttons remain available alongside scroll-triggered loading.

## Verification and remaining scope

`tests/ui_browser_checks.py` runs through the isolated browser harness after the
existing product scenario. It exercises dialog focus and nested restoration, menus,
field errors, help, both-theme destructive contrast, failed loading, narrow-screen
layout and forced-color focus. `tests/webui_browser_test.sh` is the entry point.

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
