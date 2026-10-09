"""Rejects in the browser (webui-spec 7.8): Reject waits for photos in the library; one
photo rejected from the Inspector and a selection after reviewing it; the Rejects view
with what it holds and how to empty it; Return to library, offered only there. View
counts follow the search. The reminder past a limit, on every page, and the Stats tile. Fails on any browser console error."""
import os
import re
import sys
import time
from playwright.sync_api import expect, sync_playwright

BASE = sys.argv[1]
NEWER, OLDER, DUPLICATES = (int(a) for a in sys.argv[2:5])
PHOTOS = NEWER + OLDER
errors = []


def run_job(request, mode):
    run = request.post("/api/v1/jobs/start", data={"mode": mode}).json()["id"]
    for _ in range(600):
        if (request.get(f"/api/v1/runs/{run}").json()["status"] not in ("Preparing", "Running", "Cancelling")
                and request.get('/api/v1/jobs/active').json()['active'] is None):
            return
        time.sleep(.2)
    raise AssertionError(f"{mode} timed out")


def selection_bar(page):
    return page.get_by_role("region", name="Selection")


def view_button(page, name):
    return page.get_by_role("navigation", name="Main").get_by_role("link", name=re.compile(rf"^{name}\b"))


def place_count(page, name):
    return view_button(page, name).locator(".sidebar-count")


with sync_playwright() as p:
    request = p.request.new_context(base_url=BASE)
    assert request.post("/api/v1/catalog").ok
    run_job(request, "index")

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

    # Before any Copy or Move nothing is in the library: the selection bar offers only what
    # applies, Copy and Move, never a Reject or Return of none.
    page.goto(BASE)
    page.locator(".card-check input").first.click()
    bar = selection_bar(page)
    expect(bar.get_by_role("button", name="Copy (1)…")).to_be_visible()
    expect(bar.get_by_role("button", name=re.compile(r"^Reject"))).to_have_count(0)
    expect(bar.get_by_role("button", name=re.compile(r"^Return"))).to_have_count(0)
    bar.get_by_role("button", name="Clear selection").click()

    run_job(request, "copy")
    page.goto(BASE)
    view_button(page, "Library").click()

    # The sidebar's places count everything in them, whatever the search finds.
    page.get_by_role("searchbox", name="Search filenames").fill("photo-002")
    expect(page.locator(".card")).to_have_count(1)
    expect(place_count(page, "Library")).to_have_text(f"{PHOTOS:,}")
    expect(place_count(page, "Not organized")).to_have_text("0")
    expect(place_count(page, "Rejects")).to_have_text("0")

    # One photo, from the Inspector: asked first in a sentence, starting on Cancel.
    page.locator(".card-image").first.click()
    page.get_by_role("button", name="Reject…", exact=True).click()
    dialog = page.get_by_role("alertdialog")
    expect(dialog).to_contain_text(re.compile(r"Reject photo-002\S*\?"))
    expect(dialog).to_contain_text("You can bring it back any time until you manually empty Rejects.")
    expect(dialog.locator("p")).to_have_count(1)
    expect(dialog.get_by_role("button", name="Cancel")).to_be_focused()
    shot("r1-confirm-reject")
    dialog.get_by_role("button", name="Reject", exact=True).click()
    expect(banner).to_contain_text(re.compile(r"Job #\d+ · Reject finished"), timeout=60_000)
    expect(banner).to_contain_text("1 of 1 photo moved to Rejects")
    expect(page.locator(".card")).to_have_count(0)
    expect(place_count(page, "Library")).to_have_text(f"{PHOTOS - 1:,}")
    expect(place_count(page, "Rejects")).to_have_text("1")
    dismiss_banner()

    # The Rejects view: the photo, what Rejects holds, and how to empty it, in the page.
    page.get_by_role("searchbox", name="Search filenames").fill("")
    expect(place_count(page, "Library")).to_have_text(f"{PHOTOS - 1:,}")
    view_button(page, "Rejects").click()
    expect(page).to_have_url(re.compile(r"view=rejects"))
    expect(page.locator(".card")).to_have_count(1)
    expect(page.locator(".card img")).to_have_count(1)
    expect(page.locator(".card .badge-rejected_copied")).to_have_text("Rejected")
    line = page.locator(".rejects-line")
    expect(line).to_contain_text("Rejects holds 1 photo")
    how = line.get_by_role("button", name="How to empty Rejects")
    how.click()
    expect(how).to_have_attribute("aria-expanded", "true")
    expect(line).to_contain_text("deletes photos itself")
    shot("r2-rejects-view")

    # Return to library from the Inspector of a photo in Rejects.
    page.locator(".card-image").first.click()
    expect(page.locator(".inspector")).to_contain_text("In Rejects (source still in place; a Move removes it)")
    expect(page.locator(".inspector").get_by_role("tab", name="Similar photos in Library", exact=True)).to_be_visible()
    expect(page.locator(".inspector").get_by_role("button", name="Review later…", exact=True)).to_have_count(0)
    page.get_by_role("button", name="Return to library…", exact=True).click()
    dialog = page.get_by_role("alertdialog")
    expect(dialog).to_contain_text("Return this photo to the library?")
    dialog.get_by_role("button", name="Return to library", exact=True).click()
    expect(banner).to_contain_text("1 of 1 photo returned to the library", timeout=60_000)
    expect(page.locator(".card")).to_have_count(0)
    expect(line).to_contain_text("Rejects is empty.")
    dismiss_banner()

    # A selection is reviewed first, as for Copy and Move.
    view_button(page, "Library").click()
    page.locator(".card-check input").nth(0).click()
    page.locator(".card-check input").nth(1).click()
    selection_bar(page).get_by_role("button", name="Reject (2)…").click()
    review = page.get_by_role("region", name="Review before rejecting")
    expect(review).to_contain_text("Review before rejecting")
    expect(review).to_contain_text("2 of 2 selected photos will be moved to Rejects. Untick any you don't want.")
    expect(page.locator(".card")).to_have_count(2)
    shot("r3-review-before-reject")
    review.get_by_role("button", name="Reject these 2 photos").click()
    expect(banner).to_contain_text("2 of 2 photos moved to Rejects", timeout=60_000)
    # Back in Library, which the rejected photos have left; the banner opens the job's.
    expect(page.get_by_role("region", name="Review before rejecting")).to_have_count(0)
    banner.get_by_role("button", name="Show these photos").click()
    expect(page.get_by_role("region", name="A job's photos")).to_contain_text(re.compile(r"The 2 photos in Job #\d+ · Reject"))
    dismiss_banner()

    # In the job's photos, the selection bar follows what is selected: these photos are in
    # Rejects now, so it offers Return, not Reject.
    expect(page.locator(".card")).to_have_count(2)
    page.locator(".card-check input").nth(0).click()
    page.locator(".card-check input").nth(1).click()
    bar = selection_bar(page)
    expect(bar.get_by_role("button", name="Return to library (2)…")).to_be_enabled()
    expect(bar.get_by_role("button", name=re.compile(r"^Reject"))).to_have_count(0)
    bar.get_by_role("button", name="Clear selection").click()

    # From the job's log: a photo opens in the Inspector, which returns it, with the
    # action outlined so it reads as a button.
    run = request.get("/api/v1/runs").json()["runs"][0]
    assert run["mode"] == "REJECT", run
    page.goto(f"{BASE}/logs?run={run['id']}")
    show = page.get_by_role("link", name="Show these photos in the library")
    expect(show).to_have_attribute("href", f"/?run={run['id']}")
    page.locator("a[href*='photo=']").first.click()
    back = page.locator(".inspector .photo-actions").get_by_role("button", name="Return to library…", exact=True)
    expect(back).to_be_visible()
    assert back.evaluate("b => getComputedStyle(b).borderTopStyle") == "solid", "the Inspector action has no outline"
    shot("r3b-return-from-log")
    back.click()
    page.get_by_role("alertdialog").get_by_role("button", name="Return to library", exact=True).click()
    expect(banner).to_contain_text("1 of 1 photo returned to the library", timeout=60_000)
    dismiss_banner()

    # In the Rejects view, the selection bar offers Return to library and not Reject.
    page.goto(f"{BASE}/?view=rejects")
    expect(page.locator(".card")).to_have_count(1)
    page.set_viewport_size({"width": 700, "height": 900})
    expect(line).to_contain_text("Rejects holds 1 photo")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "the Rejects view scrolls sideways"
    shot("r4-rejects-narrow")
    page.set_viewport_size({"width": 1400, "height": 900})
    page.locator(".card-check input").nth(0).click()
    bar = selection_bar(page)
    expect(bar.get_by_role("button", name=re.compile(r"^Reject"))).to_have_count(0)
    # A selection in Rejects offers Return first, then a Move that says what it deletes.
    expect(bar.locator(".selection-actions button").first).to_have_text("Return to library (1)…")
    move = bar.get_by_role("button", name="Move (1)…")
    expect(move).to_have_attribute("title", re.compile("Those copies become the only ones"))
    move.click()
    dialog = page.get_by_role("alertdialog")
    expect(dialog).to_contain_text("This photo is in Rejects. Move deletes its original from your source")
    expect(dialog).to_contain_text("empty Rejects and it is gone")
    dialog.get_by_role("button", name="Cancel", exact=True).click()
    # One place per selection (webui-spec 2): library photos cannot join it. Library
    # never shows photos in Rejects, so its Select all takes library photos only.
    view_button(page, "Library").click()
    other = page.locator(".card:not(.selected) .card-check").first
    expect(other.locator("input")).to_be_disabled()
    expect(other).to_have_attribute("title", re.compile("Library photos can't be selected with photos in Rejects"))
    selection_bar(page).get_by_role("button", name="Clear selection", exact=True).click()
    page.get_by_role("button", name="Select", exact=True).click()
    page.get_by_role("menuitem", name=re.compile(r"^Select all in this view")).click()
    expect(selection_bar(page).get_by_role("button", name=re.compile(r"^Return"))).to_have_count(0)
    selection_bar(page).get_by_role("button", name="Clear selection", exact=True).click()
    page.goto(f"{BASE}/?view=rejects")
    page.locator(".card-check input").nth(0).click()
    bar = selection_bar(page)
    bar.get_by_role("button", name="Return to library (1)…").click()
    page.get_by_role("alertdialog").get_by_role("button", name="Return to library", exact=True).click()
    expect(banner).to_contain_text("1 of 1 photo returned to the library", timeout=60_000)
    expect(place_count(page, "Rejects")).to_have_text("0")

    # The reminder: on every page once Rejects passes a limit, until it is under both again.
    settings = request.get("/api/v1/settings").json()
    assert settings["rejects_reminder_bytes"]["value"] == 1_000_000_000
    assert settings["rejects_reminder_days"]["value"] == 30
    assert request.put("/api/v1/settings", data={"values": {"rejects_reminder_bytes": 1},
                                                 "revisions": {"rejects_reminder_bytes": 0}}).ok
    view_button(page, "Library").click()
    reminder = page.get_by_role("region", name="Rejects reminder")
    expect(reminder).to_have_count(0)
    page.locator(".card-image").first.click()
    page.get_by_role("button", name="Reject…", exact=True).click()
    page.get_by_role("alertdialog").get_by_role("button", name="Reject", exact=True).click()
    expect(banner).to_contain_text("1 of 1 photo moved to Rejects", timeout=60_000)
    expect(reminder).to_contain_text(re.compile(r"Rejects holds [\d.]+ KB in 1 photo"))
    expect(reminder.get_by_role("button", name="How to empty Rejects")).to_be_visible()
    shot("r5-reminder")
    for where in ("/stats", "/logs"):
        page.goto(f"{BASE}{where}")
        expect(reminder).to_be_visible()
    # Stats: what Rejects holds, opening the Rejects view.
    page.goto(f"{BASE}/stats")
    tile = page.locator("a.stat-tile", has_text="Rejects")
    expect(tile).to_contain_text("1 photo")
    expect(tile).to_contain_text("using now · oldest rejected today")
    shot("r6-stats-tile")
    tile.click()
    expect(page).to_have_url(re.compile(r"view=rejects"))
    expect(page.locator(".card")).to_have_count(1)
    expect(reminder.get_by_role("link", name="Open Rejects")).to_have_count(0)
    # Switched off in Settings, the reminder goes.
    page.get_by_role("button", name="Settings").click()
    page.get_by_role("tab", name="Files").click()
    page.get_by_label("Remind me when Rejects holds at least", exact=True).uncheck()
    expect(page.get_by_label("Remind me when Rejects holds at least (GB)")).to_be_disabled()
    shot("r7-reminder-settings")
    page.get_by_role("button", name="Save settings").click()
    expect(page.get_by_role("status").filter(has_text="Saved")).to_be_visible()
    expect(reminder).to_have_count(0)
    assert request.get("/api/v1/settings").json()["rejects_reminder_bytes"]["value"] is None

    # A job started from a job's photos: they follow to it once it ends, so the line above
    # them and the banner, each naming its job, describe the same one.
    reject = next(r for r in request.get("/api/v1/runs").json()["runs"] if r["mode"] == "REJECT")
    page.goto(f"{BASE}/?run={reject['id']}")
    line_above = page.get_by_role("region", name="A job's photos")
    expect(line_above).to_contain_text(f"The 1 photo in Job #{reject['id']} · Reject")
    page.locator(".card-check input").first.click()
    selection_bar(page).get_by_role("button", name="Return to library (1)…").click()
    page.get_by_role("alertdialog").get_by_role("button", name="Return to library", exact=True).click()
    expect(banner).to_contain_text(re.compile(r"Job #\d+ · Return to library finished"), timeout=60_000)
    returned = request.get("/api/v1/runs").json()["runs"][0]
    assert returned["mode"] == "RETURN", returned
    expect(line_above).to_contain_text(f"The 1 photo in Job #{returned['id']} · Return to library")
    expect(banner).to_contain_text(f"Job #{returned['id']} · Return to library finished")

    assert not errors, f"browser errors: {errors}"
    print("Rejects browser checks passed")
