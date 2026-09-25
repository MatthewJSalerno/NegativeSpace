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
    expect(page.get_by_text("If you have set a CPU limit on this container, update this field to match it.")).to_be_visible()
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
    expect(inspector.locator(".inspector-image img:not([style*='none'])")).to_be_visible(timeout=15_000)
    expect(inspector).to_contain_text("Photo EXIF information")
    expect(inspector).to_contain_text("Not in the photo's EXIF")
    expect(inspector).to_contain_text("File created")
    expect(inspector).to_contain_text("File modified")
    widths = inspector.locator("table.info").evaluate_all("ts => ts.map(t => Math.round(t.getBoundingClientRect().width))")
    assert len(widths) == 3 and len(set(widths)) == 1, f"the information tables differ in width: {widths}"
    shot("3-inspector")
    no_errors_yet()

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

    page.get_by_role("button", name="Settings").click()
    expect(page.get_by_role("dialog")).to_contain_text("Changes apply to future jobs")
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)

    page.locator(".search").fill("photo-000")
    expect(page.locator(".card")).to_have_count(1, timeout=5_000)
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
      "settings, search and phone layout ok")
