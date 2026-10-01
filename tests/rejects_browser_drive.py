"""Rejects in the browser (webui-spec 7.8): reject one photo from the Inspector, a
selection after reviewing it, and a folder; the Rejects view with what it holds and how
to empty it; and Return to library. Fails on any browser console error."""
import os
import re
import sys
import time
from playwright.sync_api import expect, sync_playwright

BASE = sys.argv[1]
NEWER, OLDER, DUPLICATES = (int(a) for a in sys.argv[2:5])
PHOTOS = NEWER + OLDER
errors = []


def open_actions(page, branch):
    page.get_by_role("button", name=re.compile(r"^Actions")).click()
    menu = page.get_by_role("menu", name="Actions")
    menu.get_by_role("menuitem", name=branch, exact=True).click()
    return menu


def view_button(page, name):
    return page.get_by_role("navigation", name="Views").get_by_role("button", name=re.compile(rf"^{name}"))


with sync_playwright() as p:
    request = p.request.new_context(base_url=BASE)
    assert request.post("/api/v1/catalog").ok
    for mode in ("index", "copy"):
        run = request.post("/api/v1/jobs/start", data={"mode": mode}).json()["id"]
        for _ in range(600):
            if request.get(f"/api/v1/runs/{run}").json()["status"] not in ("Preparing", "Running", "Cancelling"):
                break
            time.sleep(.2)
        else:
            raise AssertionError(f"{mode} timed out")

    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.on("console", lambda m: m.type == "error" and not m.text.startswith("Failed to load resource") and errors.append(m.text))
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    banner = page.locator(".finished-banner")

    def shot(name):
        if os.environ.get("SHOTS"):
            page.screenshot(path=f"{os.environ['SHOTS']}/{name}.png")

    def dismiss_banner():
        page.get_by_role("button", name="Dismiss", exact=True).first.click()
        expect(banner).to_have_count(0)

    # One photo, from the Inspector: asked first, starting on Cancel.
    page.goto(BASE)
    expect(view_button(page, "All photos")).to_contain_text(f"({PHOTOS:,})")
    expect(view_button(page, "Rejects")).to_contain_text("(0)")
    page.get_by_role("searchbox", name="Search filenames").fill("photo-002")
    expect(page.locator(".card")).to_have_count(1)
    page.locator(".card-image").first.click()
    reject = page.get_by_role("button", name="Reject…", exact=True)
    expect(reject).to_be_enabled()
    shot("r1-inspector-reject")
    reject.click()
    dialog = page.get_by_role("alertdialog")
    expect(dialog).to_contain_text("Reject this photo?")
    expect(dialog).to_contain_text("Nothing is deleted.")
    expect(dialog.get_by_role("button", name="Cancel")).to_be_focused()
    shot("r2-confirm-reject")
    dialog.get_by_role("button", name="Reject", exact=True).click()
    expect(banner).to_contain_text("Reject finished", timeout=60_000)
    expect(banner).to_contain_text("1 of 1 photo moved to Rejects")
    expect(page.locator(".card")).to_have_count(0)
    expect(view_button(page, "All photos")).to_contain_text(f"({PHOTOS - 1:,})")
    expect(view_button(page, "Rejects")).to_contain_text("(1)")
    dismiss_banner()

    # The Rejects view: the photo, what Rejects holds, and how to empty it, in the page.
    page.get_by_role("searchbox", name="Search filenames").fill("")
    view_button(page, "Rejects").click()
    expect(page).to_have_url(re.compile(r"view=rejects"))
    expect(page.locator(".card")).to_have_count(1)
    expect(page.locator(".card .badge-rejected_copied")).to_have_text("Rejected")
    line = page.locator(".rejects-line")
    expect(line).to_contain_text("Rejects holds 1 photo")
    how = line.get_by_role("button", name="How to empty Rejects")
    expect(how).to_have_attribute("aria-expanded", "false")
    how.click()
    expect(how).to_have_attribute("aria-expanded", "true")
    expect(line).to_contain_text("never deletes photos")
    shot("r3-rejects-view")

    # Return to library, from the Inspector in the Rejects view.
    page.locator(".card-image").first.click()
    expect(page.locator(".inspector")).to_contain_text("In Rejects (source still in place; a Move removes it)")
    page.get_by_role("button", name="Return to library…", exact=True).click()
    dialog = page.get_by_role("alertdialog")
    expect(dialog).to_contain_text("Return this photo to the library?")
    dialog.get_by_role("button", name="Return to library", exact=True).click()
    expect(banner).to_contain_text("Return to library finished", timeout=60_000)
    expect(banner).to_contain_text("1 of 1 photo returned to the library")
    expect(page.locator(".card")).to_have_count(0)
    expect(line).to_contain_text("Rejects is empty.")
    expect(view_button(page, "All photos")).to_contain_text(f"({PHOTOS:,})")
    dismiss_banner()

    # A selection is reviewed first, as for Copy and Move.
    page.goto(BASE)
    page.locator(".card-check input").nth(0).click()
    page.locator(".card-check input").nth(1).click()
    open_actions(page, "Reject").get_by_role("menuitem", name="Reject selected (2)").click()
    review = page.get_by_role("region", name="Review before rejecting")
    expect(review).to_contain_text("2 photos will be moved to Rejects")
    expect(page.get_by_role("alertdialog")).to_have_count(0)
    expect(page.locator(".card")).to_have_count(2)
    shot("r4-review-before-reject")
    review.get_by_role("button", name="Reject these 2 photos").click()
    expect(banner).to_contain_text("2 of 2 photos moved to Rejects", timeout=60_000)
    dismiss_banner()

    # A folder, from the Folders tree: everything in it that is in the library.
    page.goto(BASE)
    expect(page.locator(".card").first).to_be_visible()
    folders_nav = page.get_by_role("navigation", name="Folders")
    trip = folders_nav.locator(".folder-row", has_text="trip / day 1")
    expect(trip.locator(".dates-count")).to_have_text("10")
    trip.get_by_role("checkbox").check()
    expect(page).to_have_url(re.compile(r"folder=trip"))
    item = open_actions(page, "Reject").get_by_role("menuitem", name=re.compile(r"^Reject this folder: trip \/ day 1 \(10\)"))
    expect(item).to_be_enabled()
    item.click()
    dialog = page.get_by_role("alertdialog")
    expect(dialog).to_contain_text("Reject the photos under trip / day 1?")
    dialog.get_by_role("button", name="Reject", exact=True).click()
    expect(banner).to_contain_text("10 of 10 photos moved to Rejects", timeout=60_000)
    item = open_actions(page, "Reject").get_by_role("menuitem", name=re.compile(r"^Reject this folder"))
    expect(item).to_be_disabled()
    expect(item).to_contain_text("Nothing to reject there")
    page.keyboard.press("Escape")
    page.keyboard.press("Escape")
    expect(view_button(page, "Rejects")).to_contain_text("(12)")

    # Narrow window: the Rejects view reflows without sideways scrolling.
    page.goto(f"{BASE}/?view=rejects")
    page.set_viewport_size({"width": 700, "height": 900})
    expect(page.locator(".rejects-line")).to_contain_text("Rejects holds 12 photos")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "the Rejects view scrolls sideways"
    shot("r5-rejects-narrow")

    assert not errors, f"browser errors: {errors}"
    print("Rejects browser checks passed")
