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

## Feature proposals and scope

Every suggested feature must state a concrete user use case: who needs it, what they
are trying to do, and why the existing workflow does not meet that need. Review the
use case and proposed scope with the maintainer before treating the suggestion as a
requirement or implementing it. A backlog or specification entry alone does not
establish that this review happened; distinguish proposals, approved work and deferred
discussion. Put additional assistant-suggested features, with their use cases, in the
discussion-only section at the end of TODO; do not add them to implementation batches
before maintainer approval. Record decisions and deferrals in the relevant spec and TODO.

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
  cannot cover the gallery; command menus stay within the viewport, opening leftwards
  from controls near the right edge.
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
use it. The setup wizard places the shared logo and NegativeSpace name at the top left of
its header on every step, with the step title below; do not repeat a welcome heading.
In first-run Files, Small-image review and Suspicious dates stay visible. File types
and Rejects reminder start collapsed in native disclosures; validation opens the affected
section before focusing its field. Back/Next stay visible. Settings after setup keeps
these sections expanded.

Settings' tabs and first-run steps are the same six groups (`webui-spec.md` §3);
a tab with unsaved changes shows a dot, named "unsaved changes" to assistive technology.

The first Settings tab, Appearance, offers Cool neutral (default) and Warm neutral palettes. The choice applies
immediately, is stored per browser under `ns.palette`, and follows across tabs;
it is independent of catalog settings and does not require Save settings. **Color mode** offers System (default), Light and Dark, remembered per browser
under `ns.theme` and synchronized across tabs. System follows live device changes;
explicit Light/Dark overrides them. A shared **Dark mode** switch sits beside Settings
in the top bar of Library, Logs and Stats, setting an explicit mode: a labelled track and
knob ([WAI-ARIA Switch](https://www.w3.org/WAI/ARIA/apg/patterns/switch/), `role="switch"`
with `aria-checked`), the knob right on the accent when dark is on. While System applies,
it shows the mode in effect. *Why a switch, not a pressed button:* on/off reads at a
glance; the label stays, since a bare sun/moon slider leaves its meaning to guesswork. Both palettes
work in every mode, including setup, dialogs and workspaces. If browser storage is unavailable,
the choice still works for the current page. All colors come from the shared root
tokens; the font is served with the app, with no external font request.

Help popups use the subdued `--surface-2` background and normal text color in both
themes. They occupy the browser's top layer so sticky sidebars and adjacent photos
cannot clip or cover the text. Help is positioned using its rendered size, stays within
the viewport when it resizes or scrolls, and scrolls internally if needed at larger text
sizes. Its content is keyboard-focusable so arrow keys can scroll it; Home/End reach
the top/bottom of the focused help, and Escape dismisses it.
When an information icon is present, only that icon opens the help by hover, focus or
click; the surrounding text and row are not hover targets. Moving onto the open help
keeps it available for reading. Help without an information icon keeps its existing
hover/focus behavior, including native filename and control tooltips.

Stats warning and failure tiles retain their semantic colored left borders so
problems are easy to notice. Folder-table cells retain the shared spacing, including
8px left padding. Keep this geometry consistent in both themes and at desktop reflow.

Index summary figures are real links to an exact source scope, including zero results.
Links clear unrelated filters without selecting files. The additional-copies link opens
representative photos, not duplicate cards. **By file type** uses a native disclosure,
closed initially, shared with the expanded Index job in Logs. Its extension totals
describe that recorded walk; mark incomplete discovery visibly. Keep file-changing
Copy/Move controls separate from this informational disclosure.

## Shared controls

Consistency applies across the whole app. Reuse shared controls for the same action,
including labels, visual style, keyboard behavior and ordering. Different contexts
may offer different actions, but must not invent a second treatment of the same action.
Top-level page tools share one component; review and comparison share the workspace,
preview and confirmation controls. Navigation goes to its named destination/tab.

| Element | Contract and implementation |
| :--- | :--- |
| Navigation | Real anchors with destinations and modified-click support; current page indicated. A skip link reaches the main region. |
| Buttons | Native buttons, primary/secondary/quiet/destructive CSS variants; verb labels. Disable submission while pending. A photo's own action standing alone on a white panel (the Inspector's **Reject…** and **Return to library…**) is outlined with `--control-border`, as fields are: quiet, it read as plain text and was missed. Standalone actions in a Settings panel (**Back up now**, the thumbnail cache actions) are outlined the same way, each with its explanation beside it. |
| Selects | Native select for sort and page size. Menus execute commands and are not substitutes for form selects. |
| Search fields | `ui/SearchField.tsx` for every search and filter box: a **Clear search** button (×, with the field's own name where it filters something else) appears once there is text, clears it and keeps focus in the box; Esc does the same before reaching the dialog or panel around it. The browser's own clear button is hidden, since only some browsers draw one. *From:* [Carbon search](https://carbondesignsystem.com/components/search/usage/). |
| Fields | `ui/Field.tsx`: persistent label, hint and field error linked to the input, plus invalid state. Required choices say **(required)** in the visible label and use native `required` semantics; do not wait for an error to reveal the requirement. Keep server validation. |
| Checkboxes | Native input and label, Space activation, actual indeterminate state for partial parents. Selecting photos differs from filtering the view. |
| Filter trees | Consistent rows, counts and focus. Folder/type labels filter; date-name buttons jump and carry an arrow cue. Parent/child inclusion rules remain those in the web spec. |
| Menus | `ui/MenuButton.tsx` manages focus, item traversal, nested scopes and dismissal. Domain components provide labels, counts, reasons and callbacks. |
| Dialogs | `ui/Modal.tsx` uses native modal dialogs and top-layer inertness. Desktop Inspector stays nonmodal; on narrow screens its covering panel becomes modal. |
| Supplemental help | `Tip.tsx`: the information icon is the hover/focus/click target when present; without an icon, retain label hover/focus; real text, a description relationship, Escape dismissal and pointer-accessible content. Essential guidance stays in the page. Richer help, such as a small diagram drawn with theme tokens, uses `content` with `wide`; `text` stays its plain form. |
| Paged loading | `ui/PageBoundary.tsx` and `paged.ts`: idle/load, pending, failed/retry and end states. Keep already-loaded photos and selection on failure. |

History and Logs use the action and outcome together: **Rotation saved** or **Date
saved**, rather than calling every completed operation a Move. Failed or skipped
attempts must retain their outcome. Use the shared operation label in every timeline.
The log keeps stable Time/Status widths and shares the remaining space between File
and Details, so paths cannot squeeze change details into a narrow strip.
A date edit's Logs Details column shows its write target and exact Before/After values
from the verified saved receipt. Keep fractions and offsets as recorded; distinguish
Not recorded from Explicitly cleared. Later edits must not rewrite this history.
A verified write may appear beside a failed refiling outcome; an unverified proposal
must never be presented as a saved change.

Keep filters and viewing controls in their own groups. File-changing actions (Keep,
Reject, edits) belong with the affected photo; exports belong in the page action group,
not among search/date/status filters. Refresh comparison is a viewing control. The Logs
heading carries a labelled **Export filtered log** group; both export formats retain
all active filters. Shared `page-heading`/`page-actions` rows wrap and align their targets.
Logs job headings and expanded entries reflow to the available content width, including
at 200% text. Indent the expanded job body, including nested disclosures such as
**By file type**, so its controls read as children of the job heading. The job heading
and its outer caret remain the control for collapsing the whole job. Date fields retain enough space to display their value.

File locations share labelled **Source** and **Destination** groups with a token-colored
hairline and spacing between them (`ui/FileLocations.tsx`). Apply this to information
panes, retry details and Logs; never leave two adjacent bare paths distinguished only
by an arrow. Preserve proposed-versus-recorded destination wording. In retry details,
show the recorded failed step and filenames, followed by the file locations without
requiring a disclosure. Destination paths are intended locations, not proof of arrival.
Give each destination file a text status and shared semantic color: green **Verified at
destination** only for recorded verification; amber **Delivery incomplete — file may be
partial** when its attempt did not finish; amber **Delivery not confirmed — no recorded
result** otherwise. Color its path to match. Keep source originals neutral: a failed
copy does not make the source file damaged. Explain that these are the last job's
recorded results, not a live check; Retry verifies again. Older records without delivery
or file/step evidence say so explicitly; never guess from a generic error.

A photo's incomplete-transfer notice shows the latest failure once, without repeating
the heading or boilerplate around its cause. Earlier attempts stay in photo Logs;
a log operation shows its own failure. The shared notice links there and offers Retry.
Confirmation says the retry **resumes** the original Copy or Move.

Inline field/action rows center their contents and wrap without stretching a button
against multiline supporting text. Confirmation footers use the shared `settings-actions`
row, including nested confirmations; do not invent an unstyled action container.

## Page frame

Decided with the maintainer (2026-10-08), after Immich's web app and drawn in the
"Navigation like Immich" mockup. Library, Logs and Stats share one frame (`AppFrame.tsx`):

- **Top bar**, sticky: the logo and name (a link to the Library's last place), the
  filename search on the Library, **Jobs ▾** on the Library, then the **Dark mode** switch and
  Settings and **Notifications**. On narrow layouts the Menu button stays at the
  top padding even when other controls wrap. The bell remains available during selection. Logs and Stats have neither search nor Jobs, and no disabled stand-in for
  them. Active progress, safety questions and Rejects reminders sit under the top bar.
- **Sidebar** (`Sidebar.tsx`, 17rem): Not organized, Source folders beneath it,
  Library, Similar photos and Rejects. Activity (Logs and Stats) sits at the bottom,
  directly above the version label, with flexible space separating it from photo places.
  On short windows or enlarged text the sidebar scrolls; the Activity links remain reachable.
  Places use real links, full visible labels and whole-place counts. Do not repeat an
  unfiltered place total above the gallery. Filtered results show Showing N of M;
  sets and job/source scopes retain their own labelled totals. Keep the result-summary
  geometry stable when filters change. Navigation clears search and optional filters;
  Similar photos retains its similarity requirement. Back/Forward restores the prior
  URL state; explicit photo/job/warning links name their exact scope.
- **Sidebar and refinements** (implemented on the feature branch; replaces Look into, its pins
  and its dimmed rows). The sidebar holds only where photos are; what narrows them sits
  above the photos, and shows only what works in the place shown, so nothing is dimmed.
  - **Sidebar:** Not organized (with Source folders under it), Library, **Similar
    photos**, Rejects; then Activity (Logs, Stats). Similar photos stays a top-level row
    because it changes the gallery (sets, percentage, its sort), not just its contents.
    Rows whose problems moved into refinements keep a one-line note so they stay in
    sight from every page: "⚠ 7 need attention" under Not organized, "12 to review" under
    Library.
  - **Refinements:** a row of toggle buttons under the page title, in the place's own
    order, each with its count; they always combine, so pins go. Library: **Needs
    review**, **Odd dates**, **No date**. Similar photos: **Needs review**, **Odd dates**, **No date** and the
    percentage. Not organized: **Needs attention** (warning colour), **Small**, **Odd
    dates**, **No date** (Small is a fact of the file there, as the rule below says). Rejects: **Odd dates**, **No date**.
  - **Needs review becomes a Library refinement, not a place.** Turned on, it adds a
    **Reason** switch (All, Small, Bookmarked, Needs verification) that picks one reason
    at a time, since each brings its own answers; the date toggles still combine with it.
  - **Needs attention and Needs verification** appear when their count is above 0
    or they are selected. A selected warning remains clearable at zero, with an
    explanatory empty state. Sidebar warning notes count the whole relevant place;
    clicking one clears unrelated filters. Refinement counts reflect the current search
    and other active restrictions, with Reason choices replacing only that reason.
  - **Short labels:** Odd dates (Suspicious dates), No date (No usable capture date),
    Small (Small images), with the full names in accessible labels and on hover.
  - *Why a row above the photos again:* the 2026-10-09 removal of the chip row was right
    while the sidebar also listed the filters; here the sidebar no longer does, so
    nothing repeats. *Why not grouped headings or nested sidebar filters:* both were
    mocked; headings still dim what does not apply, and nesting repeats the date filters
    under every place.
- **Bookmarks** (implemented on the feature branch; renames Review later, since "review"
  already names Needs review and Review one by one). **Bookmark…** beside **Reject…**
  opens a small window: **Why?**, one of Check the date, Compare versions, Fix rotation,
  Check the details, Decide whether to keep it, Ask someone, Other (the first is
  preselected), and an optional **Note** of at most 60 characters with a live counter.
  Cards show the reason in bold, then the note; the Bookmarked list sorts by reason, with
  no per-reason filter. **Review one by one** opens each bookmark with its tool ready,
  from Bookmarked or All (another chosen reason keeps its own tools first):
  the recorded dates with the existing **Edit metadata date…** link beside the primary
  Date taken value focused, without a duplicate standalone button (the editor opens only
  when chosen, so the reason and note stay in view), the side-by-side comparison, the rotation controls, the
  Metadata tab, Keep it or Reject…, or just the photo with its note. **Remove bookmark**
  clears one bookmark. *Why preset reasons and no custom ones:*
  free text alone gets inconsistent, and user-made reasons would become the tagging that
  belongs to gallery applications.
  Saving an edit never clears a bookmark automatically. Remove bookmark leaves other
  review reasons unchanged. For Decide whether to keep it, Keep it records that explicit
  decision, retaining the reason/note in history, and removes only the bookmark.
  Reject uses normal confirmation. Compare versions uses the existing match picker,
  without choosing a counterpart; no matches leaves a truthful explanation and the
  threshold controls. Check the date uses the existing editor and recorded metadata;
  future automatic evidence is not a dependency. Unavailable editing explains why.
  Presets sort in picker order, then photo ID, consistently across pages and navigation.
  Bulk bookmark removal and Keep these photos use the selection bar when all selected
  photos share that action. Keep applies only to keep-decision bookmarks.
- **Independent size browsing:** Filters offers a shorter-side cutoff in Not organized,
  Library, Similar photos and Rejects. It includes previously reviewed photos and works
  with reminders off; it never changes Settings or creates review items. Needs review
  → Small remains unacknowledged reminders under the configured reminder threshold.
  Changing that threshold does not reopen reviewed concerns for unchanged content.

- **The selection takes the top bar.** While photos are selected the selection bar
  replaces the top bar's contents (`.topbar.selecting`, on `--surface-2`), grouped at its
  start so the count and what can be done with it are read together: **✕** (Clear
  selection), the count in the accent at 16px, **Show only selected** or **Back to
  results**, the actions, then the search. Clearing gives the top bar back. *From:*
  Immich's "n selected" bar. *Why grouped:* spread across the bar, the count blended into
  the page and the actions sat at the far edge, easy to miss. *Why the search stays,
  unlike Immich's:* a selection is built across searches ("n outside this view").
- **Bulk review answers** sit with actions in the selection bar, while Needs review
  has one reason selected (including Bookmarked). Offer Mark reviewed, These dates are
  correct, Remove bookmarks and Keep these photos only when the answer applies to every
  selected photo, including photos outside the current view. One shared modal confirms
  the eligible count and what will clear; Cancel has initial focus. Photo files never
  change. A busy job disables saving with an explanation. Up to 50,000 photos can receive
  one answer; larger selections explain the limit. Source and Rejects never offer these
  answers. Mixed selections expose only shared answers; existing Reject previews remain.
  After acknowledgment, show saved and unchanged counts, listing stale photos by name
  with a reason. Closing removes only successful IDs from selection; other IDs stay
  selected. Retry an uncertain response with the same request, never a new answer.
  Selection, search and date navigation keep their established spacing and behavior.
- **Filters** beside Sort, at the end of the place heading row, opens Size, Types, then
  Dates, in a panel under it over the photos (`FiltersButton.tsx`). It is a
  disclosure (`aria-expanded`), not a dialog: the gallery updates behind it; Esc, Close
  or a click outside closes it and focus returns to the button. Its label counts active
  size, type and date filters: **Filters (2)**. Each tree's "Showing … · Show all" line
  sits under its heading, and the panel's own heading stays in view as it scrolls, so
  neither is a scroll away. *Why not a second column:* the sidebar holds the left edge,
  and two columns of controls before the photos crowded the gallery.
- **Date scrubber** (`YearScrubber.tsx`), down the gallery's right edge and in view as it
  scrolls, while the gallery is sorted by date (not in Show only selected, a review, or
  grouped similar photos, or while **No usable capture date** is active, including combined refinements). Clearing No usable capture date restores it when the sort allows it.
  Keep its empty gutter to prevent gallery reflow; no year controls remain focusable.
  Non-date sorting also retains this empty gutter: switching All ↔ Bookmarked or
  enabling Has other names must not resize cards or the Inspector. The existing narrow-screen rule hides both
  the scrubber and its empty gutter.
  This changes presentation only, not dates, ordering or filing. Otherwise its column
  stays while it loads or a filter leaves one year,
  so the gallery never shifts sideways: the years in the gallery's order, each
  given room by how many photos it holds, "No date" last. Labels go to the years holding
  the most photos first, where they have room, so a large year is never unlabelled beside
  a near-empty one. Pointing shows the month under the pointer; a click, or a drag's
  release, goes there; a year label is a button that goes to that year. A marker shows
  where the screen is. Subtle, non-interactive ticks fill the gaps, with clear space
  around the year labels. They are visual guides, not equal calendar intervals: year
  positions still follow photo counts. It uses the Dates tree's jump, so a date the filters hide says so.
  *From:* Immich's timeline scrubber. Keyboard users reach the year labels, and any
  month through Filters › Dates.
- **Source folders** (maintainer, 2026-10-09), indented under Not organized in the sidebar:
  Not organized with the source's folder tree beside the gallery (the Folders tree, in a
  pane, in view as it scrolls), and a switch, **Waiting | Still in source** ("Everything
  still in the source": what is waiting, plus the originals of photos already copied or
  rejected after a Copy). Every catalogued folder stays listed, dimmed at 0 when nothing in
  it is shown, so the tree keeps its shape as photos are organized. With one folder
  ticked, the heading names it, its last full Index sits beside it in muted text, and
  **Index this folder**, **Copy this folder (n)…** and **Move this folder (n)…** sit under it, counted as the Jobs menu counts them (with zero or multiple folders,
  the buttons remain visible but disabled with an explanation): a Move also removes the originals of
  photos already copied, each once its copy is verified again. In this view the Filters
  panel holds Types and Dates only. Empty states offer the next step as a button (**Show
  everything still in the source**, **Go to Library**). *Why under Not organized:* source
  folders matter while photos wait to be organized or their originals wait to be removed;
  the Library and the destination are laid out by date, which the date scrubber navigates.
  Opening an already copied photo here uses its destination Inspector. A visible
  notice above the tabs identifies the preview, metadata and actions as belonging
  to the Library or Rejects copy, whose metadata may differ from the source original.
  Source folders is the only folder selector; Library, Needs review and Rejects have
  no source-folder filter. Leaving Source folders for a place clears its folder scope;
  switching Waiting / Still in source retains it. Old source-folder URLs open the tree;
  folder parameters on destination URLs are discarded, so they cannot silently hide
  photos. Dates and file types remain available in every gallery. The date scrubber
  jumps within results, while the Dates checkboxes narrow them.
- **Narrow windows (800px and below):** the sidebar hides behind a **☰ Menu** button at
  the start of the top bar and opens over the page; Esc, a click outside or choosing a
  link closes it. The date scrubber hides. At 700px and below the Filters panel spans the
  window, as menus do.
  Desktop is the target; this keeps a half-screen window usable.

### Notifications

The bell is shared by Library, Logs and Stats and remains available during selection.
It displays an unread count (99+ visually, exact count in its accessible name). Its
labelled disclosure overlays content without moving the gallery; Escape and Close return
focus to the bell, and clicking outside closes it. The list scrolls within the viewport
and loads older jobs explicitly, 20 at a time. Every card uses the shared job title,
semantic outcome border, counts, time and links to its photos, failures and log.
Long failure/original-kept reasons expand in a native **Details** disclosure below
the links, never in a hover that covers the actions. Opening Details stays within
the scrolling panel and leaves that card's action row in place.

Opening the panel marks only the loaded notices read, after server acknowledgment.
Loading older notices marks that loaded batch read. The catalog stores independent,
additive receipts per job, so two browsers cannot undo each other's reads. A read is
not a dismissal of the job's failure or a response to a safety question. Failed writes
keep the unread status and offer Retry marking read. Ordinary completed-job banners
are replaced by the bell. Active progress, connection loss, submission failures, safety
questions, Rejects reminders and contextual file warnings stay visible where actionable.
The bell fetches its count on initial load, job completion and window focus; detailed
outcomes load only while the panel is used. Page navigation does not repeat count reads.

Selection counts reserve text space based on catalog capacity, including the outside-view
count and each offered action count. Numbers use tabular digits. Selecting additional
photos must not move adjacent actions; this adds no selection limit. Different available
actions and narrow-window wrapping may still change the layout.

## Copy/Move destination folders

Inside the existing transfer confirmation, after its warnings and before its footer,
show **Destination folders**, with source-file counts and native expandable disclosures.
Counts include identical source files; identify duplicates in the expanded list so
they are not mistaken for additional destination photos.
Use actual destination-relative paths, including numeric date components, never
translated month names or a different folder structure. Explain the path base.
Expanded details identify source filenames and source-relative paths, distinguishing
new deliveries, existing destination photos, duplicate originals and Rejects.
Photos without a proposed delivery remain available in a separate disclosure with
reasons. Page folders and filenames in groups of 20 so large selections do not render
an unbounded list. Keep view controls separate from Cancel/Copy/Move; Cancel starts
focused. Loading/failure blocks submission, and a stale preview offers an explicit
refresh before another confirmation. Move retains its Include/Leave decision for
edited originals. The CSV idea is deferred in TODO, not part of this confirmation.

## Move confirmation after embedded edits

Use the shared transfer confirmation for single-photo, selected, folder and whole-source
Move. Freeze the catalogued scope in a read-only preview. When edited originals are
present, show their count and an expandable paged list of filenames/source-relative
paths, followed by a required Include/Leave radio group. No preselected choice, per-photo
prompts or remembered consent. Explain that the edited copies and recorded metadata
history remain, but exact original photo bytes do not. Identify copies in Rejects and
explain their last-copy consequence. Keep the existing Cancel/Move footer and focus
Cancel initially. Loading/failure cannot enable Move; stale state offers Refresh Move
preview and clears the choice. Render **Refresh Move preview** as the shared filled
primary button so the recovery action is clearly distinguishable from explanatory text.
View/list controls remain separate from the action footer.

## Stable navigation and filtering

Ordinary job submission stays on the initiating control/dialog; the central Index
button replaces its label with **Starting…** and disables repeat submission. A brief
global submission banner must not push down the page. Uncertain/failed submission
recovery stays immediately visible, and real job progress still appears in the drawer.

Safety-question banner dismissal is an acknowledged action: keep the banner and replace Dismiss
with disabled **Saving…** while saving. On failure keep the result visible with a
plain error and **Retry dismissal**. Share that state across pages; never hide a
banner optimistically or rely on a browser-only copy of the dismissal.

Routine filter guidance swaps in place, rather than inserting a paragraph above
controls/results. Use `ui/StableContent.tsx` for known alternative explanations: all
variants share a naturally sized grid cell, with only the active variant visible,
focusable and exposed to assistive technology. The tallest wrapped variant reserves
space at the current width/font size. Do not clip text or impose fixed pixel heights.
Needs review reason explanations, gallery date/group guidance and Logs failure guidance
use this shared pattern.

Logs always has a filter-summary row; unavailable status **only** shortcuts retain
their space without remaining interactive. Job-list summaries reserve control height
when Expand all disappears. Gallery counts and filter actions share a stable summary
row; grouping controls have their own wrapping row when similarity is active. Reserve
space beside the refinements for Clear all filters, even when hidden. Longer user-entered
filters may wrap naturally; do not hide meaningful restrictions to force a height.

Dependent controls that will be used repeatedly stay mounted when unavailable:
Settings keeps the small-image minimum visible but disabled while reminders are off.
Preview position sliders stay visible but disabled at 1×; zoom and rotation keep the
recorded dimensions and photo decisions stationary. The rotation note always shows
the current viewing rotation, including 0°, and says it does not save to the file.
Preview heading space accounts for the action button at the current text size, so
reference and candidate images align at 200% text scaling too. These controls size
naturally and wrap at narrow widths; no fixed-height clipping.

Adding substantive controls (such as similarity tools), opening a job or Inspector,
and revealing an error can legitimately change content. Routine helper text alone
must not move the controls the user is operating. Verify before/after positions after
the server response at desktop and narrow desktop widths, and inspect screenshots to
avoid reserving excessive blank space. `layout_stability_browser_drive.py` guards the
shared navigation, Logs status filtering, and Library/Needs review reason toggles.

Gallery cards allow dates, status badges and review text to wrap without clipping.
Review links sit at the bottom of each card so their baselines align across a row
when other cards have longer date labels or more badges. Use flexible space, not a
fixed card height or a permanently reserved empty text row.

### Same-named photos on cards

Only cards whose names clash within the current result carry a muted line with the
shortest distinguishing part of the original source folder, in the supporting-detail text
role; the line is decided when results load and never appears while viewing. Hover on any
card name shows the full original path; a collision-renamed name says why. Pattern:
editors labelling same-named tabs with their folder
([VS Code](https://zenn.dev/bmth/articles/vscode-tab-display-name-alias?locale=en),
[Sublime Text](https://forum.sublimetext.com/t/tab-name-with-multiple-files-of-same-name-open/3619)).
Behaviour: `webui-spec.md`, Telling same-named photos apart.

Pagination keeps Go to page and the page-size control together at the trailing edge.
Ellipses between page numbers must not act as layout spacers; filtering from many
pages to a few must not move those controls across the row. Narrow layouts may wrap.

### Photo filenames

For organized Library photos, place **Rename…** beside the preview header filename
and beside the destination filename in Photo information. Both open the same dialog.
Keep a collapsed **Also arrived as** list directly below the destination. Load that list
only when opened. Each recorded alternative shows its source paths and **Use this name**;
both controls open the same rename dialog. Keep the real extension and date folder,
preview an available numbered name on collision, and require explicit confirmation.
Disable writes during a job with an explanation. No rename controls in source-only
or Rejects information. **Has other names** is a Library checkbox inside Filters;
turning it on selects Most duplicates first. It combines with other filters and clears
on place navigation or Clear all filters. It is not a review reason.

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
- **Responsive panels:** when resizing turns an underlying Inspector into a modal,
  defer its activation until covering Settings/dialogs close. It must not steal focus
  or cover the active task.
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

**The lineage timeline** (built; decided 2026-10-21; replaces the lineage tree's nested
list in its window, `webui-spec.md` §6.3). It answers, in order: where the photo is now,
what happened to it, and where its identical copies went.

- **Related history at the top:** collapsed Metadata choices and View photo logs
  sit below the title, before the timeline. They scroll away; they never interrupt
  the path from events to Now. The four lane headings have subtle vertical separators
  and use the shared strong text weight to read as column headings.
- **A summary sentence above the events**, generated from the events: "Found in 5 places on 12 Oct:
  identical copies. Moved to your library by Move #3 on 14 Oct; the other 4 were recorded,
  not copied, and their originals removed from the source. Now: in Library." It covers
  the whole history, collapsed parts included, and is the text equivalent of the graph.
- **A vertical timeline below it, one row per event** in recorded order (`operations.id`):
  date and local time (exact time on hover), the job (**Index #1**, **Copy #6**…), what it
  did in plain words with the paths involved, and **View in log**. The existing behaviours
  stay: a duplicate's path opens that photo, a job opens the log on that job for this
  photo, a failed step shows its reason and **Retry this photo**, and the information
  icon beside a path shows its size, content fingerprint, whether it matches and when
  it was recorded. Only the icon triggers this help (hover, keyboard focus or click);
  hovering the filename does not open it.
  Use the shared wide help for file details, with each detail on a separate line. A
  final **Now** row says where the photo is and what is left in the source.
- **Beside the rows, four fixed lanes, one per place, never one per file:** Source (the
  photo's own source file), Identical copies (every other file with the same content),
  Library and Rejects. Twenty copies still make four columns; a lane is drawn only while
  something is there. Dots mark events; a copy or move curves from its source lane into
  Library; identical copies join with a dashed line (recorded, not copied); a Reject
  branches out to Rejects and a Return back, the Library line dashed while the photo is
  away; a Move ends the source line with an end mark; a ring marks where the photo is now.
  Colours use the tokens (muted source, accent Library, warning Rejects) and never stand
  alone: every lane is labelled and every event is written in its row. The graph is
  decorative for assistive technology; the rows and the summary carry the content.
- **Relationships belong to the event's time** (confirmed 2026-10-21). Later edits
  never reclassify earlier identical discoveries using today's hash. Use original
  Index fingerprints and recorded duplicate decisions. Sources with different
  original content remain separate entries in Source, labelled **Separate source
  file**. If an edit later consolidates them, that edit says **Became identical;
  kept [filename]**, linking the survivor. Only that event joins their histories.
- **Copies found by the same Index are one row** with a count on its dot ("and 4 identical
  copies") and their paths listed under it, the first few then **Show all N**. **Copies
  found by different Indexes are separate rows** ("Found an identical copy (3rd)…"),
  because when they arrived is part of the story. The left timestamp identifies the
  first recorded discovery in the row, not the Index job start. Each file's exact
  first-recorded time stays in its path help; do not repeat dates beside filenames.
- **Long histories:** the window scrolls inside itself with the summary and lane headings
  pinned at the top and the Now row pinned at the bottom, using the shared More above /
  More below cues. Three or more consecutive events of one kind collapse into one row
  ("5 more identical copies found between 2 Nov and 3 Jan · Show"), with a counted dot. At
  1440 × 900 about ten rows fit; most photos have three to ten (Index, Copy, Now, plus
  edits, rejects or later copies). A re-Index of an unchanged photo adds no row (measured).
- *Why this layout:* W3C PROV is the established provenance model (files as entities,
  jobs as activities, the user or the app as agents) and its diagram conventions note that
  a drawing conveys the gist, not the record ([PROV diagrams](https://www.w3.org/2011/prov/wiki/Diagrams));
  preservation systems show PREMIS events as a per-object trail with a summary by type;
  asset-management products use a vertical, chronological timeline; Git clients use
  lanes for branching; and provenance research shows flow (merges) as a Sankey because a
  plain graph loses it ([PROV-O-Viz](https://www.scitepress.org/Papers/2024/123547/123547.pdf)).
  *Why not a horizontal lane graph:* compact for short histories, but it grows sideways
  and hides the event details behind hovers. *Why not one lane per file:* four copies
  already make six columns. *Undecided:* exporting a history as PROV-JSON.

**One "Reject?" dialog everywhere** (built; decided 2026-10-05). Every reject question, from the
gallery, the photo panel, the comparison or Needs review, is the same dialog with the same
wording, spacing and button order: the title names the photo ("Reject IMG_0412.jpg?", or
"Reject 12 photos?"), then "It moves to the Rejects folder and leaves your library. You can
bring it back any time until you manually empty Rejects.", Cancel focused first. Two parts
appear only where they apply: **Don't ask again while comparing** in the comparison, and
the last-photo warning ("None of these photos would be left in the library") with **Reject
it too** as the button. *Why not a dialog per screen:* two separate ones already drifted
and had to be reworded in both places. `ConfirmDialog` and `rejectConfirm` share the
question across these entry points; comparison-only controls are contextual options.
Bulk selection and Keep/reject-rest retain their photo-review step, then open this
same confirmation. Cancelling returns to the reviewed selection without changing it.

## Similarity belongs in the gallery

Review destination photos in the ordinary gallery and its Inspector. Do not add a
separate Similar view or a second gallery of matching groups.
**Similar photos** opens the shared gallery with similarity enabled. Needs review,
date, type, search and size refinements can narrow it. It is not a second gallery
implementation. Keep its percentage, grouping and match-sort controls together.

Keep the same card geometry and shared summary row in All photos, Has similar
photos and No usable capture date. Match badges must not add a metadata row to cards.
Use the same active-view surface for No usable capture date. Its filter has no adjacent
information icon. Put long filter descriptions
and count-scope explanations in shared help, keeping filter-reset/selection actions
visible. Similarity controls and essential below-90% guidance may wrap at smaller
widths; never hide them behind a help control or clip them for a fixed row height.

Persist gallery percentage as `match_min` and ordering as `sort=matches` in the URL.
Changing either starts at page one and preserves explicit selection. Filter-panel and
sidebar counts, Select all and photo positioning use the same percentage. Show only selected retains
all chosen files, including those without matches; disable the gallery percentage
while that scope is open. Has similar photos initially uses Most matches first. Remember explicit sort choices
per view in browser storage (`ns.sort.<view>`); switching views restores that view’s
last order. An explicit URL sort wins without rewriting the saved preference. Clicking a gallery card carries the gallery percentage into Inspector
matches and opens **Photo information**. Users can subsequently
choose another Inspector percentage without changing gallery order; previous/next
photo navigation retains that Inspector choice.

The Library Inspector has **Photo information**, **Metadata** and **Similar photos** tabs. Rejects has **File information**, **Metadata** and **Similar photos in Library**; Not organized has File information and read-only Metadata. Default to
Photo information on every gallery-card click, including Has similar photos, even if
Similar photos was open on the previous photo. Previous/next photo controls retain the active outer tab and chosen matching
threshold, including when navigation crosses a loaded page boundary. Explicit similar-photo links and
comparison actions still open their requested view; reload and history restore the URL tab.
While photo details load, use the gallery’s known status to keep the tab labels and
widths stable. If status is unknown, reserve the tab row without showing a guessed
single tab. Only loaded details determine available photo actions.
The preview and its resize divider are shared by all tabs. In Similar photos, the
large preview has a plain **Reference photo** heading and an accent border. Do not
repeat its thumbnail in the matches pane: put **Keep reference, reject n matches…**
above the candidates. Reference identifies the comparison anchor; **Keeping** appears
only after the user explicitly chooses Keep and enters the rejection review. Users
resize the panes themselves; narrow layouts do not add another reference thumbnail.
The reference heading is informational, with no button-like fill or badge.
Tab arrow keys and
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
page. Back to gallery restores its threshold/page, leaves gallery selection
intact, and restores focus to the opener
when it remains present. The reference is the photo the user opened, not a donor
or a file chosen to keep.
Identify the reference with a plain bold **Reference photo** heading and an accent border
around its preview. Keep the candidate treatment neutral and the previews aligned.
The heading is informational: do not give it a button-like fill or rounded badge.
The explicit label accompanies color so the distinction survives forced colors
and does not imply the reference is a source-folder file, donor or keeper.

The Minimum similarity dropdown and outlined **Refresh comparison** button share
bottom alignment. Keep file decisions out of this filter row. **Keep this photo,
reject the others** (with its filename and count) belongs beneath the reference
preview’s controls and dimensions; it still opens the existing confirmation review.

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
Saving a correction uses the explicit Orientation action below.
Dimensions beneath a preview follow its viewing rotation: swap width and height
at 90° and 270°, and label rotated dimensions **Displayed**. The information pane
continues to show recorded dimensions; zoom does not change either value.

The two-photo comparison grows to fit its controls, resolution, file sizes and
linked-zoom option. Do not add an inner vertical scroller or clip those details to
reserve space for the candidate strip. When the content exceeds the window height,
scroll the review window as a whole, with the shared More above/below cues. The
metadata panel may scroll independently for long tag lists. On a side-by-side desktop
layout its contents must not size the preview row: expanding All recorded tags keeps
candidate navigation in place. Narrow stacked layouts use the review window's scroll.

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
removes workspace state after the save/discard decision for unsaved turns. Return keyboard focus
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

**Single-photo rotation exit:** when only one photo has a pending turn, use a compact
**Save rotation before leaving?** dialog with **Keep reviewing** (initial focus),
**Discard and continue**, and **Save and continue**. Name the photo and metadata target;
show required duplicate-removal confirmation or refusal in the same dialog. A successful,
verified save resumes the requested navigation. A failed or uncertain save keeps the
photo and explanation visible. More than one turned photo keeps the existing per-photo
save selection. Bulk Rotate remains unchanged.

**Orientation-save interaction:** turns remain temporary during comparison. Back,
Escape and navigation offer one exit decision covering every photo turned in
that review, including candidates no longer displayed and promoted references. Use
the compact prompt for one pending photo and Save rotations for more than one.
Save selected changes, discard viewing turns and leave, or return to the photo.
Reset to zero needs no save. The Inspector (including its enlarged view), Photo Review
and each comparison preview show curved-arrow icon buttons for Rotate left and Rotate
right, with tooltips and accessible names. Turns act on the existing large preview,
fit the entire photo inside its bounds without changing its aspect ratio, and never
open a separate rotation editor. Recalculate the fit when the preview pane is resized. After a turn, show
**Save rotation** and **Reset** beside it, reserving their space when hidden so the
photo does not jump. Show the metadata write target or refusal before enabling Save;
saving is explicit and progress/results remain inline. If the verified edit would create
an exact duplicate, show a compact confirmation beside these controls naming the existing
photo, preserved history and redundant-copy removal. Use **Save and keep existing photo**
and Cancel. The date editor uses the same notice in its existing preview, beside Save;
bulk rotation identifies affected rows before its existing confirmation. Rejects and
metadata conflicts show a refusal, never an automatic primary change.
Preserve pending turns through
enlarging/resizing; photo navigation and close offer save/discard/return. The selection
bar keeps **Rotate…** and its multi-photo confirmation with per-photo targets/refusals.
Bulk left/right/180° and Reset affect only checked, eligible photos, across all pages.
Unchecked previews retain their existing turns and are not saved. Zero-turn photos
remain selectable before turning; with no eligible photos checked, turn/reset/save
controls are disabled with a selection hint. No thumbnail-card rotation controls. Save is separate from
viewing/filter controls and never triggered by an individual turn. Partial failures
retain unsaved turns; verified saves refresh previews and clear the corresponding
viewing turns. Ordinary jobs, verification and logs provide save progress and failures.

Metadata choices in Logs and lineage remains collapsed by default. A shared bordered
section with a strong label and “Saved and applied import decisions” supporting text
makes the disclosure distinguishable from ordinary log text. It still uses native
summary keyboard behavior, without fetching its entries until opened.


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
The outer divider reserves at least 420px for the photo grid; the Inspector retains
at least 320px. Saved widths and desktop window
resizing obey those limits. Very narrow desktop windows scroll horizontally rather
than compressing these areas below their minimums.

## Writing messages

Apply this contract to every user-facing message: screens, dialogs, help, job results,
logs, API errors shown in the app, and command-line guidance.

- Lead with what happened or what the user needs to decide. For a problem, say what is
  affected and what can be done next. Use short, direct sentences and familiar words.
- Keep one idea per paragraph. Use a list for multiple problems, choices or steps;
  give each affected file or reason its own readable entry. Avoid semicolon chains.
- Explain a warning once. Do not repeat its heading, cause and next step in adjacent
  notices. Preserve precise counts, filenames, source/destination labels and outcomes.
- Keep safety consequences and required actions visible. Put supporting technical
  evidence in labelled details when it is lengthy; never hide the only explanation
  of a failure or make hover the only way to read it.
- Keep raw diagnostic evidence intact. Improve the explanation around it rather than
  guessing a cause, suppressing errors or changing recorded history. Machine-readable
  codes and refusal rules are independent of prose.
- Use the shared body/supporting text roles and spacing. Messages wrap naturally;
  do not clip them or reduce their type size to fit. Shared dialog grid gaps provide
  paragraph/heading spacing without stacking native margins; related explanation
  paragraphs use the shared message-copy spacing. Reserve space for predictable
  state changes using the existing stable-content control.
- A successful save uses a calm status. Do not promise recovery, a successful transfer,
  or deletion safety beyond what the recorded verification actually establishes.

Export-sidecar guidance stays brief: identify the export evidence, explain the
Copy/Move choices, and link to external conversion tools with a short preparation
workflow. Use a clean source of photos plus converted XMP, then reindex. Removing old
export sidecars is an optional external user action after checking conversion.
Do not turn this help into a converter, tool-specific tutorial or troubleshooting flow.

## Validation and feedback

The shared job drawer reports two minutes without recorded progress as an observation,
not a diagnosis. Use the shared notice treatment and Keep waiting/Cancel actions. Waiting
only postpones the reminder; cancellation is explicit. Keep the accepted-cancel message
and disabled Cancel visible until work has stopped, including an explanation when blocked
storage may delay it. Never add a file-skipping timer.

Settings validates whole positive worker/retention counts and a nonempty extension
selection before saving. It keeps drafts, marks affected fields, describes their
errors and focuses the first invalid control. Server errors remain visible. Success
uses a polite status, not an urgent alert. Loading failures offer an explicit retry.

Settings' save result appears in its footer, beside **Reset** and **Save settings**, so a
one-line message never moves the buttons. A button names its action; an amount it
affects belongs in its explanation, in emphasis so it stands out from the muted text
(**Free up previews**, "Removes **1.2 GB** of detail previews…").

Settings active-job notice: use the shared neutral informational treatment near
the top, outside tab panels, to explain that saved processing settings affect future
jobs only. It is not an error, requires no dismissal, and does not disable Save. Keep
job-active/idle/unknown explanations in a shared stable-content area so background completion
cannot move form controls. Preserve the immediate behavior of appearance and review
reminders/access. Near Save, explain that it saves changes from every tab (`webui-spec.md` §3). Use the shared
job feed without reloading form drafts or adding a separate poll. Setup and Settings use
the same metadata preference controls and visible read-priority guidance. First run marks
the shared-sidecar choice required; unsupported embedded writers remain visibly unavailable.

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
is before the catalog’s **Earliest expected year** (default 1800) or more than one
year ahead of the current UTC year. Setup and Settings › Files offer this year
(whole number 1–9999); the chosen year itself is allowed. For example, 2000 flags
1999 and earlier. Allow for older scans and family photos. This is a
conservative review heuristic, not proof of an error. It includes EXIF-derived dates
and file-modification fallbacks, with their source identified in the Inspector and
comparison pane. Missing dates remain covered by No usable capture date; raw malformed or
conflicting EXIF tags are outside this first policy. Never infer an offset or replace
a recorded value. Legitimate historical material may still be flagged.

Use existing gallery controls, card geometry, selection, pagination and URL state
(`view=suspicious`). Counts, the Filters panel and Select all use the same membership.
Explain the policy beside results. The Inspector shows the reason, recorded value,
source and a link to the affected view. Similar photos offer clues, not automatic
corrections. The comparison Capture information table includes a Date review row
when either photo is flagged. Direct corrections to Edit Date taken in the Library
photo’s Metadata sources section; the comparison itself does not edit dates.
Changing the rule updates counts, filters and inspection immediately without
reindexing or changing photo bytes/metadata. The gallery names the saved boundary
and links to Settings. The setting is revision-checked and backed up with the catalog.
The upper bound advances with
the server's UTC year when the catalog is read.

### Reference-based sets

Library and Needs review expose the same Similar photos controls: Group similar photos,
percentage, Most matches first and set comparison. A group's representative
must belong to the current location/inbox before identical sets collapse.

Grouping is available when Has similar photos is the only explicit filter. Adding
Suspicious dates, No usable capture date, Needs review, size browsing, search, dates or
file types shows every photo satisfying all active filters individually. Leave the
checkbox visible, unchecked and disabled, with a visible explanation and description
relationship: clear the other filters to group. Clearing them restores the user's
explicit grouping preference; automatic ungrouping does not overwrite it. Percentage
and sort changes do not disable grouping. Preserve checkbox selections. URL
`group_sets=1|0` records the chosen preference and wins over browser storage on links.

Offer optional grouping within Has similar photos, retaining the ordinary per-photo
view. A set consists of its reference and every direct match at the chosen percentage.
If A matches B and B matches C but A does not match C, A's set contains A/B and B's
set contains B/A/C. A representative is a navigation reference, never a keeper.

One line above the sets says what a set is: “Each card is a set: a reference photo and
every photo that matches it. Sets can share photos.” Hovering it, focusing it or its ⓘ
shows the shared help with a small diagram (`SetsDiagram.tsx`): the set of A holding A
and B, the set of C holding B and C, B in both, and why sets are never joined. Explain
that these are two of three sets: B's own set holds A, B and C. The same
line says that checkboxes select only the reference photo. Cards carry no repeated
explanation, only their set size and **Review this set**, which opens the reference and
its direct matches in comparison; **Use as reference** there walks into a neighbouring
set. Use “set” and “reference” consistently on every screen.

*Removed: Explore related sets* (decided 2026-10-05, removed 2026-10-17), a window that
listed a set's neighbouring sets and showed up to six together. Its purpose was hard to
read from the screen, and on the demo library its chains with new photos were almost all
low-detail false matches. *Skipped option:* a single line in a photo's Similar photos tab
such as “2 more photos connect through this one · Show”, if neighbouring sets are missed
on a real library.

These are session-only display choices, not saved groups or tags. **Group similar
photos** adds set counts and actions to the existing reference cards. Sets with exactly the same full destination membership appear once in the gallery.
Compare each closed neighborhood (reference plus direct matches) at the selected
percentage, never just match counts or a transitive component. Choose the lowest
canonical photo ID inside the current location/inbox as the stable representative;
it is not a keeper or the highest-quality photo. Sort the resulting representatives
and collapse before pagination. Search displays matching photos individually.
Gallery totals and paging count sets when grouping is on. Select all and card
checkboxes select only displayed representatives, not every member. Existing
explicit selection remains intact, including hidden members; Show only selected
still displays individual photos. Sidebar place counts remain library photo counts.
Filter-panel counts remain individual photos so filters can find members hidden by
collapsed sets; date-jump positioning uses grouped representatives. A set's members come from the full destination
library. Turning grouping off returns the ordinary cards without clearing selection.
Grouping defaults on and the toggle is remembered per browser (`ns.groupSets`).

Bookmarked belongs to the Needs review refinement (`webui-spec.md` §7.9).
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
Navigation is offered only from the grouped gallery, not a set-member scope whose
ordering has a different meaning.

Show this set in gallery is available from comparison. It shows the reference and direct members at that set's percentage as
ordinary, individually selectable cards, with server paging and normal sort controls.
This temporary scope bypasses the saved gallery filters and does not auto-select,
expand or clear the existing selection. Filters are disabled while it is open;
Back to results restores the previous gallery filters/page. Reload leaves this
session-only scope. Browsing is not limited in members. No EXIF edit, reject, image
processing or persisted group is implied.

## Places, filters and the review inbox

The sidebar contains Not organized, Library, Similar photos and Rejects.
Needs review is a refinement over organized Library photos, not a physical place.
Label locations on review cards and in the Inspector/workspace. Counts count distinct
photos and must not imply the inbox adds files to the library. A new unscoped visit
starts at Not organized while Library is empty; explicit links retain their view.
Once Library exists, an unscoped visit remembers the last place in this browser.
**Which filters apply where** (built): filters about facts of a
file, known from the Index (its dates, its size, whether it has identical copies), work in
every place; filters about comparisons or decisions (look-alikes, review reminders,
verification) work only on organized photos. The 2026-10-19 sidebar design expresses
this by showing each place only its own refinements, instead of dimming. *Dropped
(2026-10-19): a Has identical copies filter.* In the Library it offers nothing to do,
and the overlap it would show before organizing is the Index summary's clickable
"Additional identical copies" figure.

Not organized starts with Index source. While Index runs, hide its summary so partial
counts cannot claim indexing has finished. After Index, its neutral Index summary describes
remaining indexed photos, identical extra copies, size and date facts, plus a clear
Copy/Move next step using the existing confirmation. Counts cover the whole location,
not gallery filters; disabled size rules and uncalculated similarity are explicit.
The Index summary has **Close index summary** and a compact **Show index summary**
control to reopen it. Dismissal is remembered in this browser across refreshes and
navigation for that finished Index; the next finished Index reveals the updated
summary. Copy/Move and other jobs do not reopen it. Closing changes no photos or
selection, and Jobs retains Copy/Move. Focus follows the close/show control.
Opening a source preview temporarily collapses the summary to **Show index summary**;
closing the preview restores its prior state. Explicit Show can expand it while the
preview is open. If only failed source files remain, say
**n files need attention**, link directly to failures and omit misleading Copy/Move actions. Use a compact failure notice only: omit the photo-statistics grid and source-photo/similarity guidance. Copy/Move completion updates this in place without a reload. If nothing remains, hide both the summary and its Show control.
Switching location closes the Inspector and comparison context, preserving checkboxes.
Changing the search or filters closes the Inspector only once its photo no longer matches;
a photo that still matches stays open where it is, as when leaving a review.
Explicit links to a photo still open that photo in their specified context.
An empty Library explains how to populate it and links to Not organized.

Library contains delivered, active photos only. Cards with unresolved reasons show a
Needs review link and concise reason labels. Opening it selects the relevant inbox
reason (no reason filter for multiple reasons), focuses that photo in the review workspace,
and clears unrelated browsing filters so the photo cannot be hidden. Checkboxes stay
unchanged. Back to Library restores the entry filters, sort and visible photo position
for this visit. Mark reviewed clears the reminder, not the Library photo.

Places and refinements have different roles: sidebar places are links; refinement
buttons combine above the photos. Needs review uses one Reason selector. Bookmarked
is a personal reminder; Small is an unacknowledged size concern. Independent size
browsing is a fact filter in every place. Choosing a sidebar place clears optional
filters; explicit URLs and Back/Forward restore their specified state.

Small-image review is destination cleanup, never a Copy/Move restriction. First-run
Files places the required on/off choice first in an accent-bordered notice, with a bold
**(required)** label and **Choose On or Off to continue**. Both choices are valid; nothing
is preselected. It offers an editable 800-pixel shorter-side
minimum if enabled. Settings can adjust or disable it. Mark reviewed acknowledges one
photo's size concern; it is not Keep, selection, relocation or approval of other reasons.
Checkboxes continue to select photos to Reject. Never untick photos because the app
found a larger look-alike. Bookmark has a preset reason and optional note; Remove bookmark clears it explicitly.

Use the shared Workspace for one-by-one review, with reason-specific evidence/actions,
Previous/Next, and Back to gallery. Next leaves the decision unresolved. Advance only
on an acknowledged decision or confirmed Reject outcome. Keep errors and retry paths
visible. Return to the same gallery context and preserve explicit selections.

Small-image gallery cards use the concise reason **Below minimum image size**. Keep
the detailed dimensions and configured rule in the Inspector and review workspace.
The short card reason also exposes that rule through shared `Tip` help on hover,
keyboard focus or the information button.

Keep **Small images** beside **No usable capture date** as a filter toggle in Library and
Needs review. It preserves location, search, pinned filters and checkbox selection.
**Inspect photo…** opens the dedicated review workspace; filtering never opens it.

The current gallery location is a section heading above its content, consistently across
views. Active restrictions sit beside it in supporting text; an
unfiltered view does not repeat its name in a small muted breadcrumb.
The Index summary labels absent positive width/height as **Image size unavailable**.
Shared help explains that unsupported formats, unreadable files or incomplete processing
can cause this; it does not diagnose corruption or a non-photo. These files are not counted
as small. Processing failures remain a separate count with a route to job details.

Switching Needs review reasons must not move the place heading or results summary.
Reason explanations share an automatically sized grid area that accommodates the longest
wrapped text at the current width/text size; do not use fixed heights or clip guidance.
Only the current explanation is visible, focusable or exposed to assistive technology.
Clear all filters remains available for active search, refinements, size, date, type
or source-folder restrictions. It preserves the place and explicit selection; clearing
Needs review returns to unrestricted Library (or Similar photos). No pins are stored.

The selection bar reserves the width of its outside-this-view message for the
catalog capacity. Filtering must not make this message appear/disappear in a
way that wraps the toolbar and shifts the gallery. The sizing copy is hidden from
view and assistive technology; a zero outside count is not announced as a warning.

Keep the outside-selection count on the same line as the selected-photo count, after it,
in supporting text: on two lines the count sat above the centre line of the links and
buttons beside it. At viewport heights of 600px or less the main toolbar
scrolls with the page, as it does in narrow windows, so a wrapped header cannot cover
the review filters or prevent their activation at desktop zoom.

Sidebar counts sit in their own right-aligned column with tabular digits, so changing
from many matches to zero never moves a label.

### Consistent review decisions

Actions are visible native buttons with the shared outlined secondary treatment;
Reject retains its explicit confirmation. Navigation is a link, explanatory facts
are plain text. Opening Settings is a dialog action and uses a button. Keep related
actions in one wrapping row with consistent control height, text and spacing.

The Inspector starts with one Photo actions row: Inspect photo…, Bookmark… and
Reject… for eligible Library photos, or Return to library… in Rejects. It precedes
location/review reasons and File/capture details, so moving through photos does not
require scrolling to reach a decision. Detailed Mark reviewed/Remove bookmark decisions belong
in the workspace beside their reason. Move the small-image Settings action out of
the Inspector; the inbox's size guidance retains it. History and full metadata
remain available without crowding the decision controls.

The dedicated review workspace names its task (Small-image review, Bookmarked photos,
or the date filter), queue position and Previous/Next in the shared header. A large
photo and compact rotation/zoom controls occupy the main area. A side panel groups
why the photo needs review, relevant facts and one action row. Explain that Mark
reviewed clears only the size reminder; Remove bookmark clears only the bookmark.
For a suspicious date, **Edit date…** and **This date is correct** sit together beside
that reason in the workspace. The Inspector keeps Inspect photo… as its route to this
answer. Confirming changes no date or file; a successfully saved date explicitly chosen
by the user also counts as correct, even outside the configured expected range. Settings
and unrelated edits do not ask again about an unchanged confirmed date. A different date
from another source must be assessed again. Odd dates remains a factual filter and can
still show confirmed dates; the Inspector labels these **Date confirmed** rather than
showing an unresolved date reminder.

Review history includes automatic date/size concern clearing with its cause, and chosen
date saves with their job link. A resolved concern does not remove a Bookmark or another
review reason. The Reason selector offers Suspicious dates for outstanding date decisions;
the existing Odd dates refinement continues to show all matching recorded dates.

When the current review queue becomes empty, return directly to the filtered gallery
with a completion message. Close its preview and remove stale photo/review URL state;
keep filters and checkbox selection. When leaving a nonempty review, retain the
preview only if it still belongs in the current gallery results. Check membership
without scrolling or changing a valid preview. A skipped earlier item is not a finished
queue: retain Previous and the end-of-position explanation while matching items remain.


Similarity shows a count and percentage with one **View all n matches →** link to the
existing Similar photos tab. Ordinary review uses this link instead of repeating candidate thumbnails. A Compare versions
bookmark opens the shared match picker here, then the existing side-by-side comparison. Browser Back restores the same photo and review queue position;
gallery filters and checkbox selection remain intact. With no matches, show one short
message and no match link. Incomplete coverage links to Review matching status; absence of evidence is
not proof of uniqueness. The panels reflow within the shared workspace; the whole
workspace scrolls, and the photo's controls do not get an inner vertical scroller.

### Review eligibility, failures and job labels

Only organized, active Library photos may receive review decisions. Similarity
comparison also accepts still-present rejected photos. Enforce this using the photo's current state in the API/catalog as well as the
UI; saved links must not bypass it. Existing review history remains readable. A reminder
on a photo outside Library does not contribute to the inbox. Not organized shows file
information, import status and failure details, with no Inspect photo, Bookmark,
Mark reviewed, Reject or Similar photos tab. Rejects shows file information/history and
Return to library and **Similar photos in Library**; it has no Bookmark or Mark
reviewed controls.

Library matches stay primary. At the chosen percentage, show rejected candidates in a
separate **Also matches n photos in Rejects** disclosure above the Library candidate
list, immediately after the threshold guidance/recovery notices, with its own pagination. They
never contribute to Library match counts, grouping, or Keep-reference targets. Source
files and emptied rejects cannot be references or candidates. Explain this scope beside
the controls. Gallery filters narrow references, not their Library candidates.

Cross-location comparison labels each preview **Location: Library / Rejects**. Each
Library photo offers Reject; each rejected photo offers Return to Library, confirmed
before running the existing verified relocation job. Similarity never automatically
rejects anything. Do not offer Keep-reference or Library set navigation for a rejected
reference or a Rejects candidate scope. Use as reference changes candidate scope to the
previous reference's location; retain that scope in review links and pagination.
Refreshing or completing a relocation reloads locations and actions. This does not add
rejected photos to Needs review or create an automatic similar-to-reject reminder.

The Index summary separates **Photos ready to organize**, **Files needing attention**
and **Unfinished processing**. Size/date facts cover successfully indexed source photos;
failed files are not ordinary missing-date photos. Failure details retain the actual
cause and a route to the recorded log. Never infer a non-image merely from missing EXIF
or a failed visual hash. Confirmed non-images/empty files and unreadable or unsupported
images need distinct explanations and external correction. Source bytes stay untouched. Undecodable source photos remain Failed in Not organized
and are excluded from Copy/Move, duplicate cleanup and Library matching. Missing EXIF,
a hash-only failure or cache-write failure on readable pixels does not block copying.
Do not call an unsupported/corrupt image a proven non-image. Already-organized files
are not automatically moved or removed.
Recheck after fixing is explicit: it repeats work and cannot repair content or add a
missing decoder. Interrupted work may resume once storage and files are available.

Stats labels its broad scope **Catalog photos / Catalog overview**, with **In Library**
as a separate subtotal. Failed source files are a separate count and are excluded from
photo trait/date statistics; Rejects has its own totals. Links specify their scope.
If a mixed source list includes failures, its total says files, not photos. Stats
Not organized identifies both photo and failure counts. Omit photo-total/format
drilldown links when the broader target would also include failed files.

Job headings use **Job #ID · Action status**: **Job #2 · Copy finished**. Apply the same
identity prefix to active/completed jobs, Logs, photo history, lineage, recovery and
job-photo scopes. The ID numbers jobs across all actions, not copies of an action.

Match cards align **Review side by side** at the bottom of the card across each row,
regardless of filename length. Let names wrap; use the shared flexible card content
layout in the Inspector and rejected matches. Do not truncate names
or fix card height merely to line up the action.

## Instance access settings

Access is the fifth shared Settings tab and setup step. Use the standard labelled
full-width field for comma-separated additional addresses, list protected local/deployment names,
and identify the current address. Save uses the common pending/error/success controls;
changes apply immediately. Explain that addresses survive rebuilding the catalog and
do not create DNS records or sign-in. Confirm removal of the current address in the
shared modal with Cancel initially focused; after saving, explain how to reconnect.
Revision conflicts and partial saves must say what happened and offer Reload settings.

Gallery grouping uses the shared `checkbox-row` geometry for vertical alignment and
label spacing. Failed-source Inspector notices display the recorded reason without
requiring hover. Review shows a match count and a count-labelled link
to the existing full match browser, without candidate thumbnails; following it retains
reference, percentage, filters and checkbox selection. Browser Back restores the same
photo and position in the review queue. This is navigation, not a photo action.


## Uncertain file outcomes

Incomplete photo/XMP imports use the same issue placement but a distinct action:
**Photo/XMP transfer incomplete**, recorded reason, then **Retry photo/XMP transfers**.
The shared dialog serves Inspector, Logs and eligible selections, showing recorded
paths on demand and blocked reasons. Confirm original Copy and Move groups separately;
never silently switch mode. Explain external correction and verification before
source deletion. Keep the dialog outside responsive panes so resizing cannot discard
its confirmation. Use shared Modal, ConfirmDialog, Pager and action styles; Cancel is
initially focused in the confirmation. Busy jobs disable retry with a reason.
A successful submission closes the dialog and follows normal job reporting; only
verified completion clears the issue. Uncertain submissions preserve their request ID.

Use one shared Files needing verification panel in the Inspector, the affected Logs operation and
Photo Review. It shows **File needs checking**, the recorded reason, expandable
**Recorded evidence**, and **Check it now**. Explain that the check updates the catalog
but never moves, overwrites or deletes photo files. Disable the action while a job runs,
with its reason; submission failures retain an idempotent retry. Report the actual check
result, not success merely because a job was accepted. Unresolved checks retain their
explanation and external correction guidance. There is no mark-resolved bypass.

Issues remain visible in Not organized and Rejects. Active Library photos also enter
**Needs review → Files needing verification** using the Needs review refinement and review workspace.
Other locations never enter the Library inbox. A successful check refreshes counts and
photo state; an emptied review queue follows the standard return-to-gallery behavior.
Checks with two remaining relocation names do not remove either name automatically.

An externally missing original with a verified Library copy is a normal observation,
not a failed Move. Keep it in Library, record what was observed in history, and update
Move counts. If the copy cannot be verified, use the shared Files needing verification explanation and
Check it now action. A disconnected/empty source retains the existing safety question.


## Metadata source tabs

Setup's Metadata step and Settings › Metadata share a visible **Which metadata is used?**
explanation beside the metadata questions. Use normal shared body/supporting text and
a short ordered list: XMP sidecar (separate file), embedded XMP (inside the photo), then
embedded EXIF (inside the photo). Keep this essential guidance out of tooltip-only help.
Explain missing versus explicitly empty fields, preservation of all sources and the
precedence of deliberate/existing source choices. Distinguish reading priority from
where edits are saved; no extra required choice or automatic primary change is implied.
Keep its layout stable when preferences change. The full planned copy and precedence
contract live in `xmp-metadata.md`; do not show it as current behavior before integration.

### First metadata UI: inspect broadly, edit Date taken

The agreed first UI supports photo organization, not general metadata editing.
Keep the common-field engine capabilities, but expose **Date taken** as the only
editable logical field in this first UI. Other captured fields remain readable and
comparable without edit/copy controls. Orientation has its own explicit save controls beside the preview;
turns remain temporary until saved. Broader field editors, bulk composition
and copying arbitrary tags are not prerequisites for this UI.

Within the dedicated **Metadata** tab, use the shared source tabs for **XMP Sidecar**,
**Embedded XMP** and **EXIF**. Photo information keeps actions, warnings, basic file
facts and a short filing-date summary with its recorded origin (EXIF or XMP; do not
infer a more specific source). **Edit metadata date…** opens the existing editor and selects
Metadata; **View metadata** opens that tab. Hide editing outside Library and disable
it during a job with the shared explanation. Fold hashes and additional file
properties under **Technical details** in Photo information. History remains directly
available. Place **View photo logs** and **View lineage tree** immediately below
the History heading, before the recent events, using the shared aligned link row. Enlarged photos use the same information, Metadata and eligible Similar
photos tabs beside the large preview, with the shared resize divider and navigation.
Do not duplicate the Inspector or put another details layout below the image. Keep
the active tab and matching threshold when opening/closing, retain gallery geometry
behind it, and restore focus to the preview on close. The full photo fits within the available preview height and width, including
portrait images; preserve its aspect ratio without cropping. Scrolling details in
the wide layout keeps the whole photo visible. Narrow desktop reflow stacks
the same panes; nested dialogs close before the expanded view. Each
source tab shows that source's captured values, not a merged effective view. Keep
missing, unreadable and failed-to-load sources distinct; do not present an error as
an empty source. Alternative sidecar versions remain inspectable without activation.
Use the primary source as the initial source tab when available. Mark its heading
with a persistent textual **Primary** badge and shared emphasis; color alone is
insufficient. The selected-tab indicator identifies the viewed source, not the primary.
When effective filing values fall back to another source, label that origin accurately
in the photo's filing information without filling gaps in a source tab.

On an alternative source tab, **Compare with primary** reveals the shared table:
**Field | Primary value | This source**. Keep row order stable and mark differences
neutrally. Offer **Show differences only** within comparison. Display **Empty** for
an explicitly empty field and **Not recorded** for an absent one. Compare source
values, not filename/file-time fallback dates. For title, caption and copyright,
plain default-language text compares equal to an otherwise identical single
`x-default` value; additional languages remain significant. Neither checkbox writes metadata or
changes primary. Reuse shared table headings, focus behavior and stable panel geometry. When a photo has multiple
sidecar versions, reserve the selector's naturally sized row on every source tab;
hide and disable it outside Sidecar XMP. Put **Copy date to primary…** beside the
Date taken value on eligible alternative source tabs, using the shared text-link style;
there is no separate copy/edit toolbar. Keep date guidance in place
across available sources. Hidden controls are neither focusable nor announced.

The expanded **All recorded source tags** disclosure follows Compare with primary,
Show differences only and the field filter. Show the union of recorded tag keys with
**Tag | Primary value | This source**, neutral difference markers and Empty versus
Not recorded. Compare exact recorded keys and structures without inventing equivalence
between EXIF and XMP names; explain that common-field comparison is above. Keep the
disclosure available when filters hide every row and show the filtered/total count.

Only Date taken offers **Copy to primary…**. Selecting it prepares a draft; it does
not write. Manual correction uses a shared **Edit metadata date…** text link beside the Date
taken value on the primary source tab, including Empty or Not recorded. Always show
that date row for available sources; alternate and inactive-version tabs do not offer
this edit link. The Photo information shortcut remains available. Disable the link
during a job with the shared explanation. Show the date's complete
recorded value, including any fraction/offset; preserve companion components unless
the user explicitly changes them. An absent donor field leaves the primary unchanged;
an explicitly empty donor date proposes a clear, visibly identified before Save.
Writer limitations still apply: an unrepresentable value cannot enable Save, and the
app never switches primary or silently substitutes another representation. Do not
show general Select all fields or wholesale replacement controls in this first UI.

The draft starts from the primary write target's own values, never inferred fallback
values. A native **Calendar date** picker changes only the calendar day,
preserving the existing time, fraction and timezone text without conversion. Keep the
full **Date taken** field for time/offset edits and partial dates. Choosing a date
without a recorded time must not invent one; EXIF's full-time requirement still applies.
Clearing the calendar helper alone is not permission to clear saved metadata.
Checking **Explicitly clear Date taken** blanks and disables both visible date inputs;
unchecking restores the unsaved draft. Nothing is written until preview and Save.
An absent XMP date still offers an explicit clear: explain that missing can fall back
to another source, while an explicitly empty date suppresses fallback and files under
Undated. Preview the source, write target, before/after date and current/resulting
location. If a photo already occupies that destination name, show the available numbered
filename and explain that existing files remain untouched. Save binds to that previewed
path; a changed target requires another preview, never a silent rename after consent.
Orphan sidecars and unsafe paths still refuse. Explain first-sidecar creation where applicable. One confirmation covers
saving and required refiling, including Undated filing after a deliberate clear.
A primary missing Date taken can point to recorded dates in other sources, with a
link to inspect each source before deliberately copying. Do not suggest replacing an
explicitly cleared value. A repeated clear with no metadata or filing change previews
No changes needed and disables Save. The completion dialog has one Date saved heading
and a shared action footer for View job details and Close. In the confirmation,
an unusual chosen year gets the shared yellow warning treatment, with its reason
and reassurance that it can still be saved. Use the catalog's expected-year policy;
do not block Save or add a second confirmation.
Other fields remain unchanged except required date companions. No permanent consent
or automatic save. Failure and recovery reuse the shared job/issue controls.

**Use as primary…** is a separate deliberate link at the top of each readable
non-primary source tab for organized Library photos. Reserve its row on primary and
unavailable source tabs so switching tabs does not shift the fields. Hide it outside
Library and disable it while a job runs, with the shared explanation. It opens the
shared confirmation dialog with a preview of all
effective-value differences, any refiling and future write target. Copy to primary
never activates the donor. Preserve all source versions and provenance. Import choices
still distinguish retaining an inactive alternative from activating it; rejected-photo
metadata and location choices remain independent (`xmp-metadata.md`). Broader import,
incoming-choice and recovery screens remain separately tracked work.
One confirmation covers the primary change and any date-based move. Cancel writes
nothing. Show actual job completion, then refresh the primary badge, metadata and
filing information; failures link to the job without claiming the switch completed.

**Built:** read-only source tabs, applied Primary badge, retained-version viewing,
comparison, differences-only, field filtering and recorded-tag disclosure. The photo
and file tag disclosure remains under Technical details → Additional file information. The viewer reads
catalog snapshots; it does not reread files or imply destination verification.
**Built:** single-photo Date taken editing and copying to primary from a recorded source
of that same photo. The shared modal preserves drafts across responsive layout changes,
validates calendar components, previews date/refiling and submits one verified engine job.
Unsupported writer values stop at preview; completed/failed jobs link to Logs.
**Built:** shared metadata guidance/preferences in setup and Settings, with a stable
live job notice. Incomplete first-import photo/XMP pairs have a separate confirmed retry.
**Built:** first-import shared-XMP ownership and competing-version controls in source attention.
**Built:** organized-photo primary changes over the verified engine job, including
returning to previously imported/saved sidecars without treating unassigned candidates
as owners. Incoming-alternative decision controls remain pending.
The engine's broader composition
and earlier-state reproduction capabilities remain built; exposing their general field
controls is deferred. Before merge, reconcile specs, backlog, validation evidence and
private handoff with implemented behavior and explicit remaining scope.

### Source metadata attention

**Needs attention** identifies a blocker to organizing a source photo. **No usable
capture date** describes its filing date; missing dates alone do not block Copy/Move.
A photo can appear in both. Show its specific date problem once in the source-attention
notice, with the Date taken row referring to it instead of repeating a generic missing
EXIF message. Group identical issues while retaining all affected file paths. Review
concerns use the effective filing date from any supported metadata source, not EXIF
presence alone. Do not invent a second problem for a usable XMP date.

Reader warnings such as unrecognized MakerNotes are informational **Metadata notes**,
not source-attention holds. Show a plain-language explanation once in the Metadata
viewer and retain the exact diagnostic under Technical details. State that these notes
alone do not prevent Copy/Move; transferring preserves original metadata bytes. Unknown
warning text stays available without claiming corruption or asking for unnecessary repair.
Actual reader errors, unstable files and unresolved/unreadable sidecar associations keep
their blocking guidance. Embedded-edit preservation checks remain separate from import.

A latest Index metadata issue on a Not organized photo gets a visible **Needs attention
· Metadata** card control opening Photo information. A shared notice at the top names
the affected source-relative sidecar, explains the issue in plain language, includes
recorded technical detail when available, and links to that photo's logs. Explain that
the pair remains at source; correcting metadata/access outside the app requires a new
Index. Unsupported formats and choices may be left at source pending support. These
are source import issues, separate from Library's Needs review. Do not label the photo
itself corrupt or provide an ineffective retry. A successful later Index clears the
notice; organized photos do not inherit this source-only hold. Index summary excludes
recorded metadata holds from Photos ready to organize and counts them under attention.

**Needs attention (count)** is a source refinement, with a warning link beneath Not organized on every screen,
showing processing failures, latest recorded metadata holds and earlier versions waiting for an answer, counting each photo once.
Its count covers all affected source files, independent of the current gallery filters.
It opens the full attention list and persists in the URL; choosing Not organized returns
to its full source scope. It combines with other source refinements. Search/date/type filters can narrow the list. Folder browsing lives in Source
folders; source issues never become a destination review reason.
The Index summary's attention count/shortcut opens the whole attention list, clearing
unrelated browsing restrictions but preserving checkbox selection.
Resolved files leave the list after a successful reindex. These source issues stay
separate from Library's Needs review; filtering makes no changes to source files.


Folder, date and type summaries keep a stable control-height row. Long selected names
truncate with their complete text available on hover; Show all reserves its place when
hidden, so filter selection never moves the tree below it. Source-folder Copy/Move
controls stay visible with eligibility guidance when zero or multiple folders are shown.
Lineage avoids repeating selection jobs already represented by a file step; selection
jobs without a recorded file step remain in a collapsed disclosure, never erased.

### Earlier versions

An earlier version of an edited Library photo (`engine-spec.md` §10) waiting for an answer
gets an **Earlier version · waiting for your answer** card control opening Photo
information, the same treatment as **Needs attention · Metadata**. Answered ones carry a
plain badge, **Earlier version · not kept** or **Earlier version**; the edited photo's card
carries **Has an earlier version**. These are relationship badges, never keywords.

Photo information opens with the shared notice: a link to the edited photo, "Only the
photo's details changed; the picture is the same" only when the recorded edit chain proves
it, and **Changes since this version**, one entry per recorded change labelled like History
(**Date saved**, **Rotation saved**, **Metadata saved**), its time, and its job as a link to
that job's log (**Job #N · Metadata**, the lineage dialog's job label), with a Before/After table using the
Metadata viewer's field names and a "Details from:" source line. Orientation values read
as words ("Turned 90° clockwise"); a changed tag with no named field shows its tag name.
**Don't keep it** answers immediately, since nothing changes on disk; **Keep it as its own
photo…** and **Keep it after all…** confirm first and name both photos' recorded filing
dates with their source (the Inspector's "filing date from EXIF/XMP"), or **Undated** with
the modification year when a file has no usable Date taken: the earlier version's, which
it files under, and the edited photo's. These come from each photo's catalog record, never
from the changed fields, so a rotation-only edit names the same date twice. Earlier answers stay listed under **Your answers**. The edited photo's
Photo information links each earlier version with its location and answer.
In the lineage dialog the split is marked with an accent rule: on the edited photo, the
edit that replaced the content carries **Version split:** naming and linking the earlier
version; on the earlier version, the line under the title says which edit it split off at,
and when. Each photo's timeline otherwise stays its own.

### First-import XMP choices

Not organized → Needs attention offers **Resolve XMP choices…** for recorded shared-sidecar
ownership or competing-XMP ambiguity. Use the shared modal, checkbox rows, metadata
comparison table and confirmation footer. Name each source sidecar and candidate photo.
No automatic selection: show the proposed owner list or effective-value differences before
**Save choice**. **Decide later** leaves everything unchanged. Keep drafts through reflow.

Saving records a choice for a later Copy/Move, not a completed import. Say that source
files stay unchanged and preserve repair guidance for unreadable evidence. The saved
choice remains visible when an old capture still reports ambiguity. After saving, show
**XMP choices saved**, the selected version/date and the next Copy/Move step. Reopening
shows this saved summary rather than the choice form. **Change XMP version…** deliberately
reopens editing; merely closing a draft preserves the saved choice. Disable while a job
runs with an explanation. Existing Library/Rejects primaries and incoming alternatives
are outside this first-import control; never offer an ineffective repair or primary switch.

The source Inspector’s **Proposed destination** reflects saved first-import XMP choices
using the engine’s filing rules. This is a catalog-only projection, not a completed
transfer or a reserved filename. Copy/Move verifies the source and final destination.
Unresolved or stale choices retain the last Index projection.

### Metadata choice history

Logs and photo lineage share a paged **Metadata choices** disclosure. Keep it collapsed
by default in every context, including photo-scoped Logs and newly opened lineage. Load
the history only when expanded. This is secondary decision history: shared-sidecar
candidates may share only a filename, not image content or a visual relationship. Show saved
ownership/primary choices with sidecar, owners or date, timestamp and choice number.
Explicit revisions remain separate entries; request replay and implicit ownership do not
create extra user decisions. A saved choice says **No files changed**. Applied entries
name the primary/date and link to the job that applied it after verified import. They
never turn a save into a processed photo or a fabricated job. Search/photo/date filters
apply; job/status filters show applied entries only and explain why saves are excluded.
Operation counts, retry controls and operation exports retain their file-operation scope.
Use shared history text, links and Pager, with loading, empty, error/retry states. Keep
source names as recorded history even if a later import or rename changes the live path.

Saved entries offer **Compare metadata…** for the current photo (or the entry's photo
in unscoped Logs). The read-only dialog compares that photo's current recorded primary
with the source values captured for the exact saved decision, never a newer sidecar
or live source file. Label the historical XMP and saved choice/time; show the recorded
owners and explicitly say when this choice did not apply the XMP to the current photo.
Shared filenames do not imply visual similarity. Reuse the Metadata source field table,
neutral difference markers, Empty versus Not recorded and **Show differences only**.
No primary means no invented comparison column; explain its absence. Unavailable
historical evidence, loading and retry are explicit. There are no edit, copy or
association actions. Closing restores focus to the history action; history still starts
collapsed. This inspection does not change ownership or primary metadata.


## Catalog backup status

The existing job-status area below the top navigation is shared by Library, Logs and
Stats. An operation stays busy through its final catalog backup: show its actual
result followed by **Backing up catalog…**, keeping file-changing actions disabled
until the engine releases its lock. Browsing remains available. No queue, remembered
next action or automatic submission after backup; the user starts the next action.

At idle, show one compact notice if catalog changes are unbacked or the latest backup
failed/interrupted. Offer **Back up now** or **Retry backup**, using the warning surface
and shared inline controls. Keep counts, backup time, technical details and the job
link in a collapsed Details disclosure. During a job or manual backup, progress uses
the same area rather than stacking an unbacked-changes banner. Successful coverage
clears the notice; it cannot be dismissed. Retry only backs up the current catalog,
never repeats photo operations. Catalog backups contain recorded metadata/history,
not photo files. Surface known causes plainly without guessing unknown failures.
