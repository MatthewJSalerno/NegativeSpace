# Sidebar and Stats validation

This batch changes wording, sidebar presentation and Stats. Filtering, metadata writes
and file-transfer rules stay the same. Automated results are recorded separately from
these maintainer checks. Report results by test and step, for example **U2c passed**.

Maintainer results: U1–U4 passed, and **U2b** passed after the label-width fix.
Only **U1b** remains: repeat the first Index from a fresh setup, as requested after
seeing the delay twice on first Index. The review instance is reset with an empty
catalog and destination. Complete setup, then run Index and report the delay between
clicking it and seeing progress. No Copy or metadata-edit repeat is needed.

## Test U1 — Setup and photo-log wording

**a.** On the fresh review instance, complete setup. In Step 2, Small-image review and
Suspicious dates should be visible; expand File types and Rejects reminder to inspect
them, then collapse them. Back/Next should stay visible. In Metadata, check the shared-sidecar
example: `photo.jpg` and `photo.png` can share `photo.xmp`; `photo.jpg.xmp` identifies one
photo. The RAW rule is a statement, with no disabled storage selector. Choose **Ask me**
for shared sidecars. Leave the earliest expected year at 1800 and enable small-image
reminders at 800 pixels.

**b.** Run Index. The initiating control should show Starting immediately; once accepted,
progress should appear below the top toolbar without waiting for the next live update;
when it finishes, open the Notifications bell for the result. A later unchanged re-index
can finish in under two seconds. Then run Copy. The source is the full demo library plus four generated
validation photos. Processing issues in the demo may leave some files in Not organized;
these do not prevent the checks below. No Move is needed.

**c.** Open Library, search `ui-stats-date.jpg`, and open its information pane. Under
History, check **View photo logs** and **View lineage tree**. The lineage dialog also
uses **View photo logs**. Both log links should show this photo's history.

**d.** Open Settings → Metadata. The same examples and RAW rule should appear. The
shared-sidecar guidance should point to Not organized → Needs attention and Resolve
XMP; it should not say individual choices are unavailable.

## Test U2 — Sidebar alignment and count explanations

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

## Test U3 — Stats dates and duplicate space

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

## Test U4 — Verified metadata edits

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
