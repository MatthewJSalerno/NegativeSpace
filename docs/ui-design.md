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
it includes photos with at least one recorded destination match at 75% or higher.
It combines with existing search, date, type and folder filters.

Opening a photo shows cumulative counts at **75%, 80%, 85%, 90%, 95% and 100%**
in its information pane. Label thresholds as “at or above”: these are overlapping
counts, not separate buckets or confidence estimates. Choosing one reveals a small,
paged list of direct matches in the same pane, leaving the reference photo, gallery
filters and explicit checkbox selection intact. Opening a match offers side-by-side
review. Match browsing does not designate files for deletion or metadata edits.
Association may help identify dates, events or other information, but proves none
of them. A 100% visual score still does not mean identical bytes.

Persist the open photo, chosen threshold and match page in the gallery URL. Keep
counts folded from their results initially; load candidate images only when asked.
A failed or unavailable hash lookup must never appear as zero matches. Show loading,
retry for request failures, and incomplete comparison states explicitly. Missing-hash
repair remains unfinished as recorded in TODO.md.

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
