# Shared Reject confirmation validation

Maintainer validation is pending. Report results by test and step, for example
**RC2b passed**. These checks cover the shared Reject question; no Index or Copy is
needed. The review instance contains the full demo library and six generated check
photos, already copied into Library. Clear other filters before searching.

Verified starting state: `rc-single.jpg`, `rc-bulk-a.jpg`, `rc-bulk-b.jpg`,
`rc-burst-1.jpg`, `rc-burst-2.jpg` and `rc-burst-3.jpg` are each present once in
Library. At 100%, each burst photo matches only the other two. Run RC3 after RC1/RC2;
leave the burst photos in Library until RC3.

## Test RC1 — One photo and appearance

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

## Test RC2 — Selected photos

**a.** In Library, search `rc-bulk-`. Tick `rc-bulk-a.jpg` and `rc-bulk-b.jpg`, then
choose **Reject (2)…**. Review both photos and choose **Reject these 2 photos**.
The shared question should say **Reject 2 photos?**, with Cancel focused and no
comparison checkbox.

**b.** Cancel that question. Both photos should remain selected in the review, and
no Reject job should start.

**c.** Choose **Reject these 2 photos** again, then **Reject**. Wait for completion.
In Rejects, search `rc-bulk-`: both photos should be there and absent from Library.

## Test RC3 — Comparison preference and last photo

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

## Automated verification

The Rejects, comparison rejection, photo review, main-page, Move confirmation and
submission browser drivers passed in Docker. The first new focus assertion was
corrected to check restoration before resizing changes the underlying photo pane;
the final Rejects rerun passed. Existing coverage remains intact. The web build,
spec/schema/API checks and user-document link checks passed. Rendered questions were
inspected in dark/light mode and at narrow width with 200% text sizing.

Full publication checks and maintainer acceptance remain separate gates before push
and merge.
