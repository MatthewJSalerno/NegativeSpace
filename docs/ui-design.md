# NegativeSpace UI design standard

This document defines the shared appearance and interaction contract for the web
interface. The target is WCAG 2.2 Level AA. Automated regression checks cover the
behaviors listed below; full conformance additionally requires assistive-technology
and manual review. This document does not claim certification.

## Visual language

Keep photographs prominent, with neutral surfaces, restrained borders, and one blue
accent. Use semantic CSS custom properties in `webui/frontend/src/styles.css` rather
than choosing new colors in a screen. Error text and destructive button fills have
separate foreground/background pairs in both themes.

- Spacing: 4, 8, 12, 16 and 24px tokens for shared controls and panels.
- Controls: 36px minimum height, increasing to 44px for coarse pointers; compact
  information and disclosure buttons remain distinct from primary actions.
- Typography: system font at the user's default root size, with relative text sizes.
- Controls share borders, corner radius, native disabled states and visible focus.
- Native checkboxes use 24px glyph targets; labels expand the selectable area.
- Focus must remain visible below sticky headers. Forced colors retain outlines and
  borders; reduced motion suppresses nonessential animated progress effects.
- On narrow screens the toolbar scrolls with the page, so its wrapped controls
  cannot cover the gallery; command menus stay within the viewport.
- Normal enabled text needs 4.5:1 contrast; inspect nontext controls and state
  indicators separately. Disabled controls are not a reason to weaken enabled ones.

These are product choices within an accessibility target, not a claim that every
control must have the same shape or that every target must be exactly 44px.

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

## Keyboard and focus

A modal moves focus inside, wraps Tab/Shift+Tab, and restores the opener on close
(or a logical surviving control). Nested dialogs close one at a time. Destructive
confirmations start on Cancel. Settings and confirmation cannot be dismissed while
their submission is pending. Closing a window is not cancellation of a running job;
use the job's Cancel command for that. Settings drafts are discarded on close;
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

## Validation and feedback

Settings validates whole positive worker/retention counts and a nonempty extension
selection before saving. It keeps drafts, marks affected fields, describes their
errors and focuses the first invalid control. Server errors remain visible. Success
uses a polite status, not an urgent alert. Loading failures offer an explicit retry.

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

Before making a full WCAG conformance claim, review all screens with a screen reader,
keyboard alone, text scaling/zoom, and real touch devices; include browser coverage
beyond Chromium. Automated checks are regression guards, not that claim.

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
