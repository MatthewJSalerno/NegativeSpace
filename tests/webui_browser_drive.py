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
    expect(page.get_by_role("button", name="Move all")).to_be_disabled()
    expect(page.locator(".tip").filter(has=page.get_by_role("button", name="Index", exact=True))).to_have_attribute(
        "data-tip", re.compile("Index your library"))

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
    # The older year's month: its first photo is photo number NEWER + 1, on this page.
    older = page.get_by_label("Jump to a month").locator("optgroup").nth(1).locator("option").first.get_attribute("value")
    page.get_by_label("Jump to a month").select_option(older)
    expect(page).to_have_url(re.compile(rf"page={NEWER // 60 + 1}\b"))
    expect(page.locator(".card-sub", has_text="2019").first).to_be_visible()
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

    # Selection and Copy; a job shorter than one feed update still refreshes the counts.
    checks = page.locator(".card-check input")
    checks.nth(0).click()
    checks.nth(2).click(modifiers=["Shift"])
    expect(page.locator(".action-bar")).to_contain_text("3 photos selected")
    page.get_by_role("button", name="Copy selected").click()
    dialog = page.get_by_role("alertdialog")
    expect(dialog).to_contain_text("Copy 3 selected photos?")
    dialog.get_by_role("button", name="Copy").click()
    expect(banner).to_contain_text("Copy finished", timeout=60_000)
    expect(banner).to_contain_text("3 of 3 files copied")
    expect(page.locator(".views")).to_contain_text("Organized (3)", timeout=5_000)
    expect(page.locator(".action-bar")).to_have_count(0)

    # Copy all, with one photo made unreadable to the app: the three already copied
    # and the duplicates are skipped with their reasons, and the failure is offered.
    locked = "/src/photo-129.jpg"
    os.chmod(locked, 0)
    page.get_by_role("button", name="Copy all").click()
    page.get_by_role("alertdialog").get_by_role("button", name="Copy").click()
    expect(banner).to_contain_text("Copy finished with failures", timeout=120_000)
    expect(banner).to_contain_text(
        f"{PHOTOS - 4} of {PHOTOS + DUPLICATES} files copied · 1 failed · {3 + DUPLICATES} skipped "
        f"(3 copied by an earlier job, {DUPLICATES} duplicates: the same content is copied once)")
    shot("6-skip-reasons")

    # The Error Center: the log filtered to this job's failures, with what to do and Retry.
    banner.get_by_role("link", name="View failures").click()
    expect(page).to_have_url(re.compile(r"/logs\?run=\d+&status=Failed"))
    expect(page.get_by_role("heading", name="Failures")).to_be_visible()
    rows = page.locator(".log-table tbody tr")
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("photo-129.jpg")
    expect(rows.first).to_contain_text("Check its permissions")
    shot("7-failures")
    page.get_by_role("button", name=re.compile(r"^Retry these photos")).click()
    expect(page.locator(".notice")).to_contain_text("Retrying 1 photo as a new Copy")
    expect(page.locator(".finished-banner")).to_contain_text("Copy", timeout=60_000)
    os.chmod(locked, 0o644)
    page.get_by_role("button", name="All statuses").click()
    expect(page.locator(".status-chips")).to_contain_text("Copied")
    page.get_by_role("link", name="Library").first.click()
    expect(page).to_have_url(re.compile(r"/(\?.*)?$"))
    expect(page.locator(".card").first).to_be_visible()

    # A photo's history, from the Inspector.
    page.locator(".card-image").first.click()
    page.locator(".inspector").get_by_role("link", name="History").click()
    expect(page.get_by_role("heading", name=re.compile(r"^Log for photo #\d+"))).to_be_visible()
    expect(page.locator(".log-table")).to_contain_text("Indexed")
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
      "settings, backups, search and phone layout ok")
