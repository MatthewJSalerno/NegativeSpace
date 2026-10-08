"""Rejecting from Similar photos and side by side (webui-spec 7.8): Reject… per look-alike;
in the comparison a Reject… under each photo, asked once with "Don't ask again while
comparing", the next look-alike shown with Return it to the library, and the last photo
always asked about; Keep this one, reject the rest, reviewed with the kept photo first.
Fails on any browser console error."""
import os
import re
import sys
import time
from playwright.sync_api import expect, sync_playwright

BASE = sys.argv[1]
errors = []

with sync_playwright() as p:
    request = p.request.new_context(base_url=BASE)
    assert request.post("/api/v1/catalog").ok

    def run_job(mode):
        response = request.post("/api/v1/jobs/start", data={"mode": mode})
        assert response.ok, response.text()
        run = response.json()["id"]
        for _ in range(600):
            if (request.get(f"/api/v1/runs/{run}").json()["status"] not in ("Preparing", "Running", "Cancelling")
                    and request.get("/api/v1/status").json()["active_job"] is None):
                return
            time.sleep(.2)
        raise AssertionError(f"{mode} timed out")

    def matches_of(photo, threshold=90):
        return request.get(f"/api/v1/similar/{photo}?threshold={threshold}&page_size=60").json()

    def status_of(photo):
        return request.get(f"/api/v1/photos/{photo}/inspect").json()["status"]

    run_job("index")
    run_job("copy")
    top = request.get("/api/v1/photos?view=similar&sort=matches&match_min=90").json()["items"][0]
    reference, name = top["id"], top["filename"]
    total = matches_of(reference)["total"]
    assert total >= 6, f"the fixture needs a set of look-alikes, got {total}"

    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.on("console", lambda m: m.type == "error" and not m.text.startswith("Failed to load resource") and errors.append(m.text))
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    banner = page.locator(".finished-banner")

    def shot(label):
        if os.environ.get("SHOTS"):
            page.screenshot(path=os.path.join(os.environ["SHOTS"], label + ".png"))

    def open_similar():
        page.goto(f"{BASE}/?photo={reference}&tab=similar")
        page.get_by_role("button", name=re.compile(r"^90% or higher:")).click()
        expect(page.locator(".inspector-match-list li").first).to_be_visible()

    # One reference preview, not an implied Keep decision or a repeated thumbnail.
    open_similar()
    inspector = page.locator(".inspector")
    preview = inspector.locator(".inspector-preview")
    keeping = inspector.get_by_role("button", name=re.compile(r"^Keep reference, reject "))
    expect(keeping).to_have_text(f"Keep reference, reject {total} matches…")
    expect(inspector.get_by_text("Keeping", exact=True)).to_have_count(0)
    expect(inspector.locator(f'.photo-matches img[src*="/photos/{reference}/"]')).to_have_count(0)
    for width, panel_width in ((2200, 1300), (1440, 700), (720, 360)):
        page.set_viewport_size({"width": width, "height": 1000})
        page.evaluate("w => localStorage.setItem('ns.inspectorWidth', String(w))", panel_width)
        open_similar()
        expect(preview.get_by_role("heading", name="Reference photo", exact=True)).to_be_visible()
        expect(preview.locator(".inspector-image img:not([style*='none'])")).to_be_visible(timeout=15_000)
        assert preview.evaluate("e => getComputedStyle(e).borderTopWidth") == "2px"
        expect(inspector.locator(f'.photo-matches img[src*="/photos/{reference}/"]')).to_have_count(0)
        if width == 2200:
            expect(inspector.locator(".inspector-main")).to_have_attribute("data-wide", "true")
        shot(f"reference-preview-{width}")
    page.set_viewport_size({"width": 1440, "height": 1000})
    open_similar()
    for theme in ("light", "dark"):
        page.emulate_media(color_scheme=theme)
        shot(f"reference-preview-{theme}")
    page.emulate_media(forced_colors="active")
    expect(preview.get_by_role("heading", name="Reference photo", exact=True)).to_be_visible()
    assert preview.evaluate("e => getComputedStyle(e).borderTopStyle") == "solid"
    page.emulate_media(forced_colors="none", color_scheme="light")
    inspector.get_by_role("tab", name="Photo information", exact=True).click()
    expect(preview.get_by_role("heading", name="Reference photo", exact=True)).to_have_count(0)
    expect(preview).to_have_attribute("data-reference", "false")
    inspector.get_by_role("tab", name="Similar photos", exact=True).click()
    rows = page.locator(".inspector-match-list li")
    expect(rows.first.get_by_role("button", name=re.compile(r"^Reject .+…$"))).to_be_visible()
    shot("s1-similar-tab")
    first = matches_of(reference)["items"][0]
    rows.first.get_by_role("button", name=f"Reject {first['filename']}…").click()
    dialog = page.get_by_role("alertdialog")
    expect(dialog).to_contain_text(f"Reject {first['filename']}?")
    dialog.get_by_role("button", name="Reject", exact=True).click()
    expect(banner).to_contain_text("1 of 1 photo moved to Rejects", timeout=60_000)
    assert status_of(first["id"]) == "Rejected_Copied"
    total -= 1
    expect(keeping).to_have_text(f"Keep reference, reject {total} matches…")

    # Side by side: a Reject… under each photo.
    page.locator(".inspector-match").first.click()
    workspace = page.get_by_role("dialog", name="Review photo match")
    expect(workspace.locator(".review-photo-name button")).to_have_count(2)
    # A quiet rule separates the two photos.
    assert workspace.locator(".review-photo").nth(1).evaluate("e => getComputedStyle(e).borderLeftStyle") == "solid"
    candidate = workspace.locator(".review-photo").nth(1).locator(".review-photo-name > span").inner_text()
    shot("s2-side-by-side")
    workspace.locator(".review-photo").nth(1).get_by_role("button", name="Reject…").click()
    ask = page.get_by_role("alertdialog")
    expect(ask).to_contain_text(f"Reject {candidate}?")
    expect(ask.get_by_role("button", name="Cancel")).to_be_focused()
    ask.get_by_label("Don't ask again while comparing").check()
    shot("s3-ask-once")
    ask.get_by_role("button", name="Reject", exact=True).click()
    status = workspace.locator(".workspace-status")
    expect(status).to_contain_text(f"Rejected {candidate} · next look-alike shown", timeout=60_000)
    next_one = workspace.locator(".review-photo").nth(1).locator(".review-photo-name > span")
    expect(next_one).not_to_have_text(candidate)
    shot("s4-after-reject")
    # Asked once: the next reject in this comparison happens straight away.
    second = next_one.inner_text()
    workspace.locator(".review-photo").nth(1).get_by_role("button", name="Reject…").click()
    expect(page.get_by_role("alertdialog")).to_have_count(0)
    expect(status).to_contain_text(f"Rejected {second}", timeout=60_000)
    # Return it to the library, from the note.
    status.get_by_role("button", name="Return it to the library").click()
    expect(status).to_contain_text(f"Returned {second} to the library.", timeout=60_000)
    page.keyboard.press("Escape")
    expect(workspace).to_have_count(0)
    total -= 1

    # From side by side too: the same review, keeping the photo on the left.
    open_similar()
    page.locator(".inspector-match").first.click()
    workspace = page.get_by_role("dialog", name="Review photo match")
    workspace.get_by_role("button", name=f"Keep {name}, reject the other {total}…").click()
    expect(workspace).to_have_count(0)
    review = page.get_by_role("region", name="Review before rejecting")
    expect(review).to_contain_text(f"Keeping {name}")
    expect(page.locator(".card").first).to_have_class(re.compile(r"\bcard-keep\b"))
    review.get_by_role("button", name="Cancel").click()
    expect(review).to_have_count(0)

    # Keep this one, reject the rest: reviewed first, the kept photo first and full size.
    open_similar()
    page.get_by_role("button", name=f"Keep reference, reject {total} matches…", exact=True).click()
    review = page.get_by_role("region", name="Review before rejecting")
    expect(review).to_contain_text(f"Keeping {name}")
    expect(review).to_contain_text(f"{total:,} of {total:,} look-alikes will be moved to Rejects. Untick any you want to keep.")
    # A review, not the Similar view: no grouping, threshold or match-count badges.
    expect(page.get_by_role("checkbox", name="Group similar photos")).to_have_count(0)
    expect(page.locator(".card-match-count")).to_have_count(0)
    cards = page.locator(".card")
    # The kept photo leads, loaded on its own, whatever page its look-alikes fill.
    expect(cards).to_have_count(min(total, 60) + 1)
    expect(cards.first).to_have_class(re.compile(r"\bcard-keep\b"))
    expect(cards.first).to_contain_text("Keeping")
    expect(cards.first.get_by_role("checkbox")).to_have_count(0)
    first_box = cards.first.bounding_box()
    other_box = cards.nth(1).bounding_box()
    assert abs(first_box["width"] - other_box["width"]) < 2, (first_box, other_box)
    cards.nth(1).get_by_role("checkbox").uncheck()
    kept_too = cards.nth(1).get_attribute("data-id")
    expect(review.get_by_role("button", name=f"Reject these {total - 1} photos")).to_be_visible()
    expect(review).to_contain_text(f"{total - 1:,} of {total:,} look-alikes will be moved to Rejects.")
    shot("s5-keep-review")
    review.get_by_role("button", name=f"Reject these {total - 1} photos").click()
    expect(banner).to_contain_text(f"{total - 1} of {total - 1} photos moved to Rejects", timeout=60_000)
    assert status_of(reference) == "Copied", "the kept photo was rejected"
    assert status_of(int(kept_too)) == "Copied", "an unticked look-alike was rejected"

    # The last one: a new comparison asks again, and leaving none of the compared photos in
    # the library always asks, without Don't ask again.
    open_similar()
    page.locator(".inspector-match").first.click()
    workspace = page.get_by_role("dialog", name="Review photo match")
    workspace.locator(".review-photo").nth(1).get_by_role("button", name="Reject…").click()
    ask = page.get_by_role("alertdialog")
    expect(ask.get_by_label("Don't ask again while comparing")).to_be_visible()
    ask.get_by_role("button", name="Reject", exact=True).click()
    expect(workspace.locator(".workspace-status")).to_contain_text("no more look-alikes", timeout=60_000)
    workspace.locator(".review-alone").get_by_role("button", name="Reject…").click()
    ask = page.get_by_role("alertdialog")
    expect(ask).to_contain_text(f"Reject {name} too?")
    expect(ask).to_contain_text("None of these photos would be left in the library.")
    expect(ask.get_by_label("Don't ask again while comparing")).to_have_count(0)
    expect(ask.get_by_role("button", name="Cancel")).to_be_focused()
    shot("s6-last-one")
    ask.get_by_role("button", name="Cancel").click()
    assert status_of(reference) == "Copied"

    # Rejecting it after all closes the comparison with a note in the Library, which lasts
    # only while the photo is in Rejects: returned from the Rejects view, the note goes.
    workspace.locator(".review-alone").get_by_role("button", name="Reject…").click()
    page.get_by_role("alertdialog").get_by_role("button", name="Reject it too").click()
    expect(workspace).to_have_count(0, timeout=60_000)
    note = page.locator(".notice")
    expect(note).to_contain_text(f"Rejected {name}.")
    expect(note.get_by_role("button", name="Return it to the library")).to_be_visible()
    page.get_by_role("button", name="Close", exact=True).click()
    page.get_by_role("navigation", name="Views").get_by_role("button", name=re.compile(r"^Rejects")).click()
    page.get_by_role("searchbox", name="Search filenames").fill(name)
    expect(page.locator(".card")).to_have_count(1)
    expect(page.locator(f".card[data-id='{reference}']")).to_be_visible()
    # Everything in the view is on screen, so Select offers the view, not "on screen" too.
    select_button = page.locator(".select-menu > button")
    select_button.click()
    select = page.get_by_role("menu", name="Select")
    expect(select.get_by_role("menuitem", name=re.compile(r"^Select all in this view"))).to_be_visible()
    expect(select.get_by_role("menuitem", name=re.compile(r"^Select all on screen"))).to_have_count(0)
    select_button.click()
    expect(select).to_have_count(0)
    page.locator(f".card[data-id='{reference}'] .card-check input").click()
    page.get_by_role("region", name="Selection").get_by_role("button", name="Return to library (1)…").click()
    page.get_by_role("alertdialog").get_by_role("button", name="Return to library", exact=True).click()
    expect(banner).to_contain_text("1 of 1 photo returned to the library", timeout=60_000)
    expect(note).to_have_count(0)
    assert status_of(reference) == "Copied"

    assert not errors, f"browser errors: {errors}"
    print("Reject from similar photos browser checks passed")
