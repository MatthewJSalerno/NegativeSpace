"""Drives the built web interface in a real browser (Playwright, headless Chromium).

Run by tests/webui_browser_test.sh against both containers holding generated photos:
NEWER photos dated in one year and OLDER in an earlier one, plus exact copies. It walks
first run, settings, Index, the gallery and its paging, jumping to a date, the
Inspector and its divider, selection, Copy and search, and fails on any browser
console error.

The unit suites cannot see the screens. This found a gallery that never refreshed
after a job too short to be seen running, and an Inspector that crashed on a date
format the browser rejects.
"""
import os
import re
import sys
import time

from playwright.sync_api import expect, sync_playwright

BASE = sys.argv[1]
NEWER, OLDER, DUPLICATES = (int(a) for a in sys.argv[2:5])
PHOTOS = NEWER + OLDER

errors = []
server_errors = []
def open_actions(page, branch=None):
    """Opens the Actions menu, and Copy or Move within it; returns the menu."""
    page.get_by_role("button", name=re.compile(r"^Actions")).click()
    menu = page.get_by_role("menu", name="Actions")
    if branch:
        menu.get_by_role("menuitem", name=branch, exact=True).click()
    return menu


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.on("console", lambda m: m.type == "error" and not m.text.startswith("Failed to load resource") and errors.append(m.text))
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("response", lambda r: r.status >= 500 and server_errors.append(f"{r.status} {r.url}"))

    def no_errors_yet():
        assert not errors, f"browser errors: {errors}"

    def shot(name):
        # SHOTS=<folder> keeps screenshots for reviewing the screens by eye.
        if os.environ.get("SHOTS"):
            page.screenshot(path=f"{os.environ['SHOTS']}/{name}.png")

    # First run: create the catalog, then settings as the page, saying they can change later.
    page.goto(BASE)
    expect(page.get_by_text("No catalog found")).to_be_visible()
    page.get_by_role("button", name="Create new catalog").click()
    expect(page.get_by_text("Welcome to NegativeSpace")).to_be_visible()
    expect(page.locator(".notice-first-run")).to_contain_text("change any of them at any time in the app's Settings")
    expect(page.locator(".settings")).to_contain_text(re.compile(r"This container may use (all )?\d+"))
    shot("1-welcome")
    page.get_by_role("button", name="Save and continue").click()
    expect(page.get_by_text("No photos yet")).to_be_visible()
    # The Actions menu: every item that cannot run says why.
    menu = open_actions(page, "Move")
    expect(menu.get_by_role("menuitem", name=re.compile(r"^Move all"))).to_be_disabled()
    expect(menu).to_contain_text("Index your library first")
    expect(menu.get_by_role("menuitem", name=re.compile(r"^Index"))).to_be_enabled()
    page.keyboard.press("Escape")
    expect(page.locator(".menu")).to_have_count(0)

    # Index; the result shows at the top of the page, and the gallery refreshes itself.
    page.get_by_role("button", name="Index your library").click()
    banner = page.locator(".finished-banner")
    expect(banner).to_contain_text("Index finished", timeout=180_000)
    expect(banner).to_contain_text(f"{PHOTOS + DUPLICATES:,} new or changed, including {DUPLICATES:,} duplicate")
    top = banner.bounding_box()["y"]
    assert top < 150, f"the finished-job banner is not at the top of the page (y={top})"
    expect(page.locator(".card")).to_have_count(60)
    expect(page.locator(".views")).to_contain_text(f"Not yet organized ({PHOTOS:,})")
    time.sleep(1)
    broken = page.evaluate("[...document.querySelectorAll('.card img')]"
                           ".filter(i => i.complete && i.naturalWidth === 0).length")
    assert broken == 0, f"{broken} grid thumbnails failed to load"
    shot("2-indexed")
    no_errors_yet()

    # Paging for a large library: numbered pages, go-to, page size, jump to a date.
    pager = page.locator(".pager").first
    pages = -(-PHOTOS // 60)
    expect(pager.get_by_role("button", name=str(pages), exact=True)).to_be_visible()
    pager.get_by_role("button", name="Last page").click()
    expect(page).to_have_url(re.compile(rf"page={pages}\b"))
    expect(page.locator(".card")).to_have_count(PHOTOS - 60 * (pages - 1))
    pager.get_by_label("Go to page").fill("2")
    pager.get_by_role("button", name="Go", exact=True).click()
    expect(page).to_have_url(re.compile(r"page=2\b"))
    page.reload()
    expect(page).to_have_url(re.compile(r"page=2\b"))
    expect(page.locator(".pager").first.locator("button.current")).to_have_text("2")
    page.goto(BASE)
    # The date tree: clicking the older year jumps to its page; its first photo is photo
    # number NEWER + 1. Ticking it shows only that year, and the address keeps it.
    dates = page.get_by_role("navigation", name="Dates")
    expect(dates.get_by_label("Show only June 2019")).to_be_visible()   # every year starts unfolded
    dates.get_by_role("button", name="2019", exact=True).click()
    expect(page).to_have_url(re.compile(rf"page={NEWER // 60 + 1}\b"))
    expect(page.locator(".card-sub", has_text="2019").first).to_be_visible()
    dates.get_by_label("Show only 2019").check()
    expect(page.locator(".dates-filter-line")).to_contain_text("Showing only 2019")
    expect(page.locator(".pager").first).to_contain_text(f"{OLDER} photos")
    expect(page.locator(".views")).to_contain_text(f"All photos ({OLDER})")
    expect(dates.get_by_role("button", name="2023", exact=True)).to_be_visible()   # counts ignore the filter
    page.reload()
    expect(page.locator(".pager").first).to_contain_text(f"{OLDER} photos")
    page.locator(".dates-filter-line").get_by_role("button", name="Show all dates").click()
    expect(page.locator(".pager").first).to_contain_text(f"{PHOTOS} photos")
    shot("2b-dates")
    page.locator(".pager").first.get_by_label("Photos per page").select_option("120")
    expect(page).to_have_url(re.compile(r"size=120"))
    page.goto(BASE)
    no_errors_yet()

    # The Inspector: bordered tables of equal width, EXIF kept apart from file dates.
    page.locator(".card-image").first.click()
    inspector = page.locator(".inspector")
    expect(inspector).to_contain_text("Not yet organized")
    expect(inspector).to_contain_text("Proposed destination path")
    expect(inspector.locator(".inspector-image img:not([style*='none'])")).to_be_visible(timeout=15_000)
    expect(inspector).to_contain_text("Photo EXIF information")
    expect(inspector).to_contain_text("Not in the photo's EXIF")
    expect(inspector).not_to_contain_text("File created")
    expect(inspector).to_contain_text("File modified")
    widths = inspector.locator("table.info").evaluate_all("ts => ts.map(t => Math.round(t.getBoundingClientRect().width))")
    assert len(widths) == 3 and len(set(widths)) == 1, f"the information tables differ in width: {widths}"
    shot("3-inspector")
    no_errors_yet()

    # Clicking the photo enlarges it over a blurred page, details below; Esc returns.
    inspector.locator(".inspector-image").click()
    lightbox = page.locator(".lightbox")
    expect(lightbox).to_be_visible()
    expect(lightbox).to_contain_text("Photo EXIF information")
    blur = lightbox.evaluate("e => getComputedStyle(e).backdropFilter")
    assert "blur" in blur, f"the enlarged view does not blur the page behind it: {blur}"
    shot("5-enlarged")
    page.keyboard.press("Escape")
    expect(lightbox).to_have_count(0)
    expect(inspector).to_be_visible()
    inspector.locator(".inspector-image").click()
    page.get_by_role("button", name="Close the enlarged photo").click()
    expect(lightbox).to_have_count(0)

    # The divider: drag it, and a wide panel puts the details beside the photo.
    divider = page.locator(".divider")
    before = inspector.bounding_box()["width"]
    box = divider.bounding_box()
    page.mouse.move(box["x"] + 4, box["y"] + 200)
    page.mouse.down()
    page.mouse.move(360, box["y"] + 200, steps=8)
    page.mouse.up()
    after = inspector.bounding_box()["width"]
    assert after > before + 200, f"dragging the divider did not widen the panel ({before} -> {after})"
    columns = inspector.locator(".inspector-main").evaluate("e => getComputedStyle(e).gridTemplateColumns")
    assert len(columns.split()) == 2, f"a wide panel did not place the details beside the photo: {columns}"
    shot("4-inspector-wide")
    divider.focus()
    page.keyboard.press("ArrowRight")
    assert inspector.bounding_box()["width"] < after, "the divider did not respond to the keyboard"

    page.keyboard.press("Escape")
    expect(inspector).to_have_count(0)
    page.locator(".card-image").first.click()
    first_url = page.url
    page.keyboard.press("ArrowRight")
    expect(page).not_to_have_url(first_url)
    page.keyboard.press("Escape")

    # The Select menu: this page, everything shown, and unselecting either.
    line = page.locator(".selection-line")
    def select(item):
        page.get_by_role("button", name=re.compile(r"^Select")).first.click()
        label = page.locator(".menu-label").get_by_text(item, exact=True)
        page.get_by_role("menu", name="Select").get_by_role("menuitem").filter(has=label).click()
    select("Select all on this page (60)")
    expect(line).to_contain_text("60 photos selected")
    select("Unselect all")
    expect(line).to_have_count(0)
    select(f"Select all ({PHOTOS})")
    expect(line).to_contain_text(f"{PHOTOS} photos selected")
    line.get_by_role("button", name="Clear").click()
    expect(line).to_have_count(0)

    # Selection and Copy; a job shorter than one feed update still refreshes the counts.
    # The selection line sits in the top row, after Logs.
    checks = page.locator(".card-check input")
    checks.nth(0).click()
    checks.nth(2).click(modifiers=["Shift"])
    expect(line).to_contain_text("3 photos selected")
    logs_box = page.get_by_role("link", name="Logs").bounding_box()
    line_box = line.bounding_box()
    assert abs(line_box["y"] - logs_box["y"]) < 20 and line_box["x"] > logs_box["x"], "the selection is not beside Logs"
    # On another page the three are outside the view; Show only selected brings them back.
    page.locator(".pager").first.get_by_role("button", name="2", exact=True).click()
    expect(line).to_contain_text("3 outside this view")
    line.get_by_role("button", name="Show only selected").click()
    expect(page.locator(".focus-head")).to_contain_text("Showing only the 3 selected photos")
    expect(page.locator(".card")).to_have_count(3)
    line.get_by_role("button", name="Back to results").click()
    expect(page.locator(".focus-head")).to_have_count(0)
    expect(page).to_have_url(re.compile(r"page=2\b"))
    # Clearing the selection while showing only it returns to the results.
    line.get_by_role("button", name="Show only selected").click()
    line.get_by_role("button", name="Clear").click()
    expect(page.locator(".focus-head")).to_have_count(0)
    expect(page.locator(".card")).to_have_count(60)
    page.locator(".pager").first.get_by_role("button", name="1", exact=True).click()
    checks.nth(0).click()
    checks.nth(2).click(modifiers=["Shift"])
    page.locator(".pager").first.get_by_role("button", name="2", exact=True).click()
    expect(line).to_contain_text("3 outside this view")
    # Acting on a selection that is hidden shows it first; Cancel returns to the page.
    open_actions(page, "Copy").get_by_role("menuitem", name="Copy selected (3)").click()
    expect(page.locator(".focus-head")).to_contain_text("Showing only the 3 selected photos")
    page.get_by_role("alertdialog").get_by_role("button", name="Cancel").click()
    expect(page.locator(".focus-head")).to_have_count(0)
    expect(page).to_have_url(re.compile(r"page=2\b"))
    open_actions(page, "Copy").get_by_role("menuitem", name="Copy selected (3)").click()
    dialog = page.get_by_role("alertdialog")
    expect(dialog).to_contain_text("Copy 3 selected photos?")
    expect(page.locator(".card")).to_have_count(3)
    shot("5b-review-before-copy")
    dialog.get_by_role("button", name="Copy").click()
    expect(page.locator(".focus-head")).to_contain_text("The 3 photos in the job just started")
    expect(banner).to_contain_text("Copy finished", timeout=60_000)
    expect(banner).to_contain_text("3 of 3 files copied")
    expect(page.locator(".badge-copied")).to_have_count(3, timeout=5_000)
    expect(line).to_contain_text("0 photos selected")
    page.locator(".focus-head").get_by_role("button", name="Back to results").click()
    expect(line).to_have_count(0)
    expect(page.locator(".views")).to_contain_text("Organized (3)", timeout=5_000)

    # Copy all, with one photo made unreadable to the app: the three already copied
    # and the duplicates are skipped with their reasons, and the failure is offered.
    locked = "/src/photo-129.jpg"
    os.chmod(locked, 0)
    # Counted over the whole catalog, whatever the gallery shows: search does not change it.
    page.locator(".search").fill("photo-00")
    open_actions(page, "Copy").get_by_role("menuitem", name=f"Copy all ({PHOTOS - 3:,})").click()
    dialog = page.get_by_role("alertdialog")
    expect(dialog).to_contain_text(f"every photo not yet copied ({PHOTOS - 3:,})")
    dialog.get_by_role("button", name="Copy").click()
    page.locator(".search").fill("")
    expect(banner).to_contain_text("Copy finished with failures", timeout=120_000)
    expect(banner).to_contain_text(
        f"{PHOTOS - 4} of {PHOTOS + DUPLICATES} files copied · 1 failed · {3 + DUPLICATES} skipped "
        f"(3 copied by an earlier job, {DUPLICATES} duplicates: the same content is copied once)")
    shot("6-skip-reasons")
    # Everything copyable is copied, but Move still has every copied photo to finish.
    menu = open_actions(page, "Copy")
    expect(menu.get_by_role("menuitem", name="Copy all (0)")).to_be_disabled()
    expect(menu).to_contain_text("Nothing to copy")
    menu.get_by_role("menuitem", name="Move", exact=True).click()
    expect(menu.get_by_role("menuitem", name=f"Move all ({PHOTOS - 1:,})")).to_be_enabled()
    expect(menu).to_contain_text(f"including {PHOTOS - 1:,} already copied")
    shot("6b-actions-menu")
    page.keyboard.press("Escape")

    # The Error Center: the log filtered to this job's failures, with what to do and Retry.
    banner.get_by_role("link", name="View failures").click()
    expect(page).to_have_url(re.compile(r"/logs\?run=\d+&status=Failed"))
    expect(page.get_by_role("heading", name="Failures")).to_be_visible()
    # Grouped by job: the job the banner named is the only one listed, and it is open.
    expect(page.locator(".job-group")).to_have_count(1)
    expect(page.locator(".job-head")).to_have_attribute("aria-expanded", "true")
    rows = page.locator(".log-table tbody tr")
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("photo-129.jpg")
    expect(rows.first).to_contain_text("Check its permissions")
    shot("7-failures")
    page.get_by_role("button", name=re.compile(r"^Retry the 1 failed photo")).click()
    expect(page.locator(".notice")).to_contain_text("Retrying 1 photo as a new Copy")
    expect(page.locator(".finished-banner")).to_contain_text("Copy", timeout=60_000)
    os.chmod(locked, 0o644)
    page.get_by_role("button", name="All statuses").click()
    expect(page.locator(".status-chips")).to_contain_text("Copied")
    # Every job, one line each until opened; the job arrived at from the banner stays open.
    page.get_by_role("button", name="Show all jobs").click()
    expect(page.locator(".job-group")).to_have_count(4)
    expect(page.locator(".job-head[aria-expanded=true]")).to_have_count(1)
    expect(page.locator(".log-table")).to_have_count(1)
    page.locator(".job-head").last.click()
    expect(page.locator(".log-table")).to_have_count(2)
    expect(page.locator(".job-group").last).to_contain_text("Indexed")
    # A banner dismissed in the library stays dismissed on the log.
    page.get_by_role("link", name="Library").first.click()
    expect(page.locator(".finished-banner")).to_be_visible()
    page.locator(".finished-banner").get_by_role("button", name="Dismiss").click()
    page.get_by_role("link", name="Logs").first.click()
    expect(page.locator(".job-group").first).to_be_visible()
    expect(page.locator(".finished-banner")).to_have_count(0)
    page.get_by_role("link", name="Library").first.click()
    expect(page).to_have_url(re.compile(r"/(\?.*)?$"))
    expect(page.locator(".card").first).to_be_visible()

    # A photo's history, from the Inspector.
    page.locator(".card-image").first.click()
    page.locator(".inspector").get_by_role("link", name="History").click()
    expect(page.get_by_role("heading", name=re.compile(r"^Log for photo #\d+"))).to_be_visible()
    expect(page.locator(".job-group").first).to_be_visible()
    heads = page.locator(".job-head")
    for i in range(heads.count()):
        if heads.nth(i).get_attribute("aria-expanded") == "false":
            heads.nth(i).click()
    expect(page.locator(".log-table").first).to_be_visible()
    expect(page.locator(".job-list")).to_contain_text("Indexed")
    page.go_back()
    expect(page.locator(".inspector")).to_be_visible()
    page.keyboard.press("Escape")

    page.get_by_role("button", name="Settings").click()
    expect(page.get_by_role("dialog")).to_contain_text("Changes apply to future jobs")
    # Catalog backups: each job above took one; Back up now adds a manual one.
    backups = page.locator(".backups")
    expect(backups).to_contain_text("not photos")
    expect(backups.locator("tbody tr", has_text="After job #").first).to_be_visible()
    backups.get_by_role("button", name="Back up now").click()
    expect(backups.locator("p.ok")).to_contain_text("verified")
    manual = backups.locator("tbody tr", has_text="Manual")
    expect(manual).to_have_count(1)
    expect(manual).to_contain_text("Zstandard")
    with page.expect_download() as got:
        manual.get_by_role("link", name="Download").click()
    assert got.value.suggested_filename.endswith(".db.zst"), got.value.suggested_filename
    page.get_by_label("Automatic backups to keep").fill("1")
    expect(backups).to_contain_text(re.compile(r"removes the \d+ oldest automatic backups? after the next"))
    shot("settings-backups")
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)

    # The quick filter for photos with no capture date in their EXIF.
    undated_filter = page.get_by_role("button", name=re.compile(r"^No capture date"))
    expect(undated_filter).to_contain_text(f"({PHOTOS - 2:,})")
    undated_filter.click()
    expect(page).to_have_url(re.compile(r"undated=1"))
    expect(page.locator(".pager").first).to_contain_text(f"{PHOTOS - 2:,} photos")
    undated_filter.click()
    expect(page).not_to_have_url(re.compile(r"undated=1"))

    # A photo with an EXIF date: shown from EXIF, one note for the missing time zone.
    page.locator(".search").fill("photo-000")
    expect(page.locator(".card")).to_have_count(1, timeout=5_000)
    page.locator(".card-image").first.click()
    expect(inspector).to_contain_text("2023-01-15 09:30:00")
    expect(inspector.locator(".section-note")).to_contain_text("recorded no time zone")
    expect(inspector.locator("th", has_text="*")).to_have_count(0)
    page.keyboard.press("Escape")
    expect(page).to_have_url(re.compile(r"q=photo-000"))
    page.reload()
    expect(page.locator(".search")).to_have_value("photo-000")

    phone = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True)
    phone.goto(BASE)
    expect(phone.locator(".card").first).to_be_visible()
    overflow = phone.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
    assert not overflow, "the page scrolls sideways at phone width"
    browser.close()

assert not errors, f"browser console errors: {errors}"
assert not server_errors, f"server errors: {server_errors}"
print("web interface: first run, index, paging, jump to date, inspector, divider, selection, copy, "
      "settings, backups, dates, select, show only selected, search and phone layout ok")
