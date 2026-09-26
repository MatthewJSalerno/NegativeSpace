"""Drives the built web interface in a real browser (Playwright, headless Chromium).

Run by tests/webui_browser_test.sh against both containers holding generated photos:
NEWER photos dated in one year and OLDER in an earlier one, plus exact copies. It walks
first run, settings and backups, Index, the gallery's scrolling and date tree, the
Inspector (metadata, history, lineage), selection with its review before Copy, the
Actions menu, the log, and search, and fails on any browser console error.

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
    page.goto(BASE + "/logs")   # an address left by an earlier session
    expect(page.get_by_text("No catalog found")).to_be_visible()
    page.get_by_role("button", name="Create new catalog").click()
    expect(page.get_by_text("Welcome to NegativeSpace")).to_be_visible()
    expect(page.locator(".notice-first-run")).to_contain_text("change any of them at any time in the app's Settings")
    expect(page.locator(".settings")).to_contain_text(re.compile(r"This container may use (all )?\d+"))
    shot("1-welcome")
    page.get_by_role("button", name="Save and continue").click()
    # Saved, the first run lands in the Library, where the Index waits, whatever the address was.
    expect(page).to_have_url(re.compile(r"^[^?]*://[^/]+/(\?.*)?$"))
    expect(page.get_by_text("No photos yet")).to_be_visible()
    # Which build is running, at the top right beside Settings.
    expect(page.locator(".version-tag")).to_have_text(re.compile(r"^v\d+\.\d+\.\d+"))
    # The logo at the top left, in its own proportions.
    logo = page.locator(".brand .logo").bounding_box()
    assert logo and logo["x"] < 40 and abs(logo["width"] / logo["height"] - 991 / 956) < 0.05, f"logo: {logo}"
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

    # A large library: the pager (numbered pages, go-to, size) and continuous scrolling.
    pager = page.locator(".pager").first
    pages = -(-PHOTOS // 60)
    expect(pager.get_by_role("button", name=str(pages), exact=True)).to_be_visible()
    pager.get_by_role("button", name="Last page").click()
    expect(page).to_have_url(re.compile(rf"page={pages}\b"))
    expect(page.locator(".gallery-foot")).to_contain_text(f"End of {PHOTOS} photos")
    pager.get_by_label("Go to page").fill("2")
    pager.get_by_role("button", name="Go", exact=True).click()
    expect(page).to_have_url(re.compile(r"page=2\b"))
    page.reload()
    expect(page).to_have_url(re.compile(r"page=2\b"))
    expect(page.locator(".pager").first.locator("button.current")).to_have_text("2")
    page.goto(BASE)
    # Continuous scrolling: past the first page the next loads below it, and the page
    # number and the address follow the photos on top.
    expect(page.locator(".card")).to_have_count(60)
    page.mouse.wheel(0, 20_000)
    expect(page.locator(".card")).to_have_count(120, timeout=10_000)
    # The left panel stays beside the photos however far the gallery scrolls.
    page.mouse.wheel(0, 20_000)
    page.wait_for_timeout(300)
    panel = page.locator(".side-panel").bounding_box()
    toolbar = page.locator(".toolbar").bounding_box()
    assert abs(panel["y"] - (toolbar["y"] + toolbar["height"])) < 4, f"the left panel scrolled away: {panel}"
    page.locator(".card").nth(90).scroll_into_view_if_needed()
    expect(page).to_have_url(re.compile(r"page=2\b"), timeout=5_000)
    expect(page.locator(".pager").first.locator("button.current")).to_have_text("2")
    # The tree highlights every month with a photo on screen, not the page's: January
    # 2023 has two photos, mid-row in page 2, and lights up when they are in view.
    january = page.locator(".card", has_text="2023-01-15").first
    january.evaluate("""e => window.scrollTo(0, e.getBoundingClientRect().top + window.scrollY
        - document.querySelector('.toolbar').getBoundingClientRect().height - 2)""")
    expect(page.locator(".dates-row.current.month", has_text="January")).to_have_count(1, timeout=5_000)
    page.goto(BASE)
    # The date tree: clicking the older year jumps to its page; its first photo is photo
    # number NEWER + 1. Checking it shows only that year, and the address keeps it.
    dates = page.get_by_role("navigation", name="Dates")
    expect(dates.get_by_label("Show only June 2019")).to_be_visible()   # every year starts unfolded
    dates.get_by_role("button", name="2019", exact=True).click()
    expect(page).to_have_url(re.compile(rf"page={NEWER // 60 + 1}\b"))
    expect(page.locator(".card-sub", has_text="2019").first).to_be_visible()
    dates.get_by_label("Show only 2019").check()
    expect(page.locator(".dates-filter-line")).to_contain_text("Showing only 2019")
    # Select these: the photos the date filter shows, in one click.
    page.locator(".dates-filter-line").get_by_role("button", name=f"Select these {OLDER}").click()
    expect(page.locator(".selection-line")).to_contain_text(f"{OLDER} photos selected")
    page.locator(".selection-line").get_by_role("button", name="Clear").click()
    expect(page.locator(".pager").first).to_contain_text(f"{OLDER} photos")
    expect(page.locator(".views")).to_contain_text(f"All photos ({OLDER})")
    expect(dates.get_by_role("button", name="2023", exact=True)).to_be_visible()   # counts ignore the filter
    page.reload()
    expect(page.locator(".pager").first).to_contain_text(f"{OLDER} photos")
    # A date outside the filter says so and offers the fixes as buttons that apply them.
    dates.get_by_role("button", name="2023", exact=True).click()
    notice = page.locator(".notice")
    expect(notice).to_contain_text("2023 is outside the dates shown.")
    notice.get_by_role("button", name="Show 2023 too").click()
    expect(page.locator(".dates-filter-line")).to_contain_text("2019, 2023")
    expect(page.locator(".card-sub", has_text="2023").first).to_be_visible()
    expect(notice).to_have_count(0)
    dates.get_by_label("Show only 2023").uncheck()
    page.locator(".dates-filter-line").get_by_role("button", name="Show all dates").click()
    # Types, above Dates and folded until opened: only the types the library holds (here, JPEG).
    types = page.get_by_role("navigation", name="Types")
    side = page.locator(".side-panel nav").evaluate_all("ns => ns.map(n => n.getAttribute('aria-label'))")
    assert side[:2] == ["Types", "Dates"], f"Types is not at the top of the panel: {side}"
    expect(types.locator(".type-row")).to_have_count(0)
    types.get_by_role("button", name=re.compile(r"Types")).click()
    expect(types.locator(".type-row")).to_have_count(1)
    expect(types.locator(".type-row")).to_contain_text(f"JPG{PHOTOS:,}")
    types.get_by_label("Show only JPG").check()
    expect(page.locator(".dates-filter-line")).to_contain_text("Showing only JPG")
    expect(page).to_have_url(re.compile(r"type=jpg"))
    types.get_by_role("button", name=re.compile(r"Types")).click()           # folded, it still names the filter
    expect(types.get_by_role("button", name=re.compile(r"Types"))).to_contain_text("JPG")
    page.locator(".dates-filter-line").get_by_role("button", name="Show all types").click()
    expect(page).not_to_have_url(re.compile(r"type="))
    # Oldest first turns the tree over: the oldest year leads.
    year_names = dates.locator(".dates-tree > li > .dates-row .dates-name")
    expect(year_names.first).to_have_text("2023")
    page.get_by_label("Sort").select_option("oldest")
    expect(year_names.first).to_have_text("2019")
    page.get_by_label("Sort").select_option("newest")
    expect(page.locator(".pager").first).to_contain_text(f"{PHOTOS} photos")
    shot("2b-dates")
    page.locator(".pager").first.get_by_label("Photos loaded at a time").select_option("120")
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
    expect(inspector).to_contain_text("As recorded when NegativeSpace first indexed this file")
    # History, in a section of its own near the top, with the latest events.
    history = inspector.locator(".photo-history")
    expect(history).to_contain_text("Indexed")
    expect(history.locator("h3")).to_have_text("History (1)")
    expect(inspector.get_by_role("link", name="History", exact=True)).to_have_count(0)   # one place, not two
    widths = inspector.locator("table.info").evaluate_all("ts => ts.map(t => Math.round(t.getBoundingClientRect().width))")
    assert len(widths) == 3 and len(set(widths)) == 1, f"the information tables differ in width: {widths}"
    # Show all metadata: every tag recorded, folded until asked for, with a filter.
    inspector.get_by_role("button", name=re.compile(r"^Show all metadata \(\d+ tags\)")).click()
    expect(inspector.locator(".meta-table")).to_contain_text("ImageWidth")
    # Scrolled to the last tag, Hide stays in reach, below the panel's own title bar.
    inspector.locator(".meta-table tr").last.scroll_into_view_if_needed()
    hide = inspector.get_by_role("button", name="Hide all metadata")
    expect(hide).to_be_in_viewport()
    title_bottom = inspector.locator(".inspector-head").bounding_box()
    title_bottom = title_bottom["y"] + title_bottom["height"]
    assert hide.bounding_box()["y"] >= title_bottom - 1, "the metadata header slid under the panel's title bar"
    inspector.get_by_label("Filter the metadata").fill("ImageWidth")
    expect(inspector.locator(".meta-table tr")).to_have_count(1)
    hide.click()
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
    page.get_by_role("button", name=re.compile(r"^Select")).first.click()
    on_screen = page.get_by_role("menu", name="Select").locator(".menu-label", has_text=re.compile(r"^Select all on screen"))
    n = int(re.search(r"\((\d+)\)", on_screen.inner_text()).group(1))
    visible = page.locator(".card").evaluate_all(
        "cs => cs.filter(c => { const r = c.getBoundingClientRect(); return r.bottom > 0 && r.top < innerHeight; }).length")
    assert 0 < n < 60 and abs(n - visible) <= 6, f"on screen counted {n}, but {visible} photos are visible"
    on_screen.click()
    expect(line).to_contain_text(f"{n} photos selected")
    select("Unselect all")
    expect(line).to_have_count(0)
    select(f"Select all in this view ({PHOTOS})")
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
    # Hidden by a filter, the three are outside the view; Show only selected brings them back.
    only_2019 = page.get_by_role("navigation", name="Dates").get_by_label("Show only 2019")
    only_2019.check()
    expect(line).to_contain_text("3 outside this view")
    line.get_by_role("button", name="Show only selected").click()
    expect(page.locator(".focus-head")).to_contain_text("Showing only the 3 selected photos")
    expect(page.locator(".card")).to_have_count(3)
    line.get_by_role("button", name="Back to results").click()
    expect(page.locator(".focus-head")).to_have_count(0)
    expect(page).to_have_url(re.compile(r"date=2019"))
    # Clearing the selection while showing only it returns to the results.
    line.get_by_role("button", name="Show only selected").click()
    line.get_by_role("button", name="Clear").click()
    expect(page.locator(".focus-head")).to_have_count(0)
    expect(page.locator(".pager").first).to_contain_text(f"{OLDER} photos")
    only_2019.uncheck()
    checks.nth(0).click()
    checks.nth(2).click(modifiers=["Shift"])
    only_2019.check()
    expect(line).to_contain_text("3 outside this view")
    # Copy selected shows every selected photo to review, with the action in a bar above
    # them, not a dialog over them. Cancel returns to the view it came from.
    review = page.get_by_role("region", name="Review before copying")
    open_actions(page, "Copy").get_by_role("menuitem", name="Copy selected (3)").click()
    expect(review).to_contain_text("Review the 3 selected photos below")
    expect(page.get_by_role("alertdialog")).to_have_count(0)
    review.get_by_role("button", name="Cancel").click()
    expect(review).to_have_count(0)
    expect(page).to_have_url(re.compile(r"date=2019"))
    open_actions(page, "Copy").get_by_role("menuitem", name="Copy selected (3)").click()
    expect(page.locator(".card")).to_have_count(3)
    # Unchecking one there changes what will be copied; the photo stays on screen.
    page.locator(".card-check input").first.click()
    expect(review.get_by_role("button", name="Copy these 2 photos")).to_be_visible()
    expect(page.locator(".card")).to_have_count(3)
    page.locator(".card-check input").first.click()
    shot("5b-review-before-copy")
    review.get_by_role("button", name="Copy these 3 photos").click()
    expect(page.locator(".focus-head")).to_contain_text("The 3 photos in the job just started")
    expect(banner).to_contain_text("Copy finished", timeout=60_000)
    expect(banner).to_contain_text("3 of 3 files copied")
    expect(page.locator(".badge-copied")).to_have_count(3, timeout=5_000)
    expect(line).to_contain_text("0 photos selected")
    page.locator(".focus-head").get_by_role("button", name="Back to results").click()
    expect(line).to_have_count(0)
    only_2019.uncheck()
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
    # Hovering the failure count gives the reasons; a Failed photo's badge gives its own.
    expect(banner.locator(".tip")).to_have_attribute("data-tip", re.compile(r"Why they failed:\nPermission denied: 1"))
    page.locator(".search").fill("photo-129")
    expect(page.locator(".badge-failed")).to_have_attribute("title", "Failed: Permission denied")
    page.locator(".search").fill("")
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
    # The same top row as the Library, and the filters named in one line with one reset.
    expect(page.get_by_role("button", name=re.compile(r"^Actions"))).to_be_visible()
    expect(page.locator(".dates-filter-line")).to_contain_text(re.compile(r"Showing: job #\d+ · Failed"))
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
    # A long job loads more entries as it scrolls, and its header line stays in view.
    page.locator(".job-head[aria-expanded=true]").first.click()
    copy_all = page.locator(".job-group", has_text="Copy finished with failures")
    copy_all.locator(".job-head").click()
    rows = copy_all.locator(".log-table tbody tr")
    expect(rows).to_have_count(100)
    rows.last.scroll_into_view_if_needed()
    expect(rows).to_have_count(PHOTOS + DUPLICATES - 3 + 3, timeout=10_000)
    expect(copy_all.locator(".job-head")).to_be_in_viewport()
    shot("8-log-scrolling")
    copy_all.locator(".job-head").click()
    page.locator(".status-chips").get_by_role("button", name=re.compile(r"^Copied")).click()
    page.get_by_label("Search the log").fill("photo-00")
    expect(page.locator(".dates-filter-line")).to_contain_text("Showing: Copied · “photo-00”")
    page.get_by_role("button", name="Clear all filters").click()
    expect(page.get_by_label("Search the log")).to_have_value("")
    expect(page.locator(".dates-filter-line")).to_have_count(0)
    # A banner dismissed in the library stays dismissed on the log.
    page.get_by_role("link", name="Library").first.click()
    expect(page.locator(".finished-banner")).to_be_visible()
    page.locator(".finished-banner").get_by_role("button", name="Dismiss").click()
    page.get_by_role("link", name="Logs").first.click()
    expect(page.locator(".job-group").first).to_be_visible()
    expect(page.locator(".finished-banner")).to_have_count(0)
    # Kept with the catalog, not the browser: clearing the browser's storage keeps it dismissed.
    page.evaluate("localStorage.clear()")
    page.reload()
    expect(page.locator(".job-group").first).to_be_visible()
    page.wait_for_timeout(1500)
    expect(page.locator(".finished-banner")).to_have_count(0)
    page.get_by_role("link", name="Library").first.click()
    expect(page).to_have_url(re.compile(r"/(\?.*)?$"))
    expect(page.locator(".card").first).to_be_visible()

    # A photo's history, from the Inspector.
    page.locator(".card-image").first.click()
    # After a Copy, the pane lists the photo's whole history; the log is one link away.
    events = page.locator(".inspector .history-list li")
    expect(events).to_have_count(3)                       # indexed, copied, then skipped by Copy all
    expect(events.nth(0)).to_contain_text("Indexed")      # oldest first
    expect(events.nth(1)).to_contain_text("Copied")
    expect(events.nth(2)).to_contain_text("Skipped")
    shot("3b-history")
    # The lineage tree, in its own window: the source, the copy made from it, their steps.
    page.locator(".inspector").get_by_role("button", name="View lineage tree").click()
    tree = page.get_by_role("dialog", name=re.compile(r"^Lineage of "))
    expect(tree.locator(".lineage-node.lineage-indexed .lineage-kind").first).to_have_text("Source")
    copy_node = tree.locator(".lineage-node.lineage-copy")
    expect(copy_node).to_have_count(1)
    expect(copy_node).to_contain_text("Copied here")
    expect(tree.locator(".lineage-step", has_text="Skipped")).to_have_count(1)   # each step once
    expect(copy_node).to_contain_text("Present")
    shot("3c-lineage")
    page.keyboard.press("Escape")
    expect(tree).to_have_count(0)
    expect(page.locator(".inspector")).to_be_visible()     # Escape closes the window, not the panel too
    # From the enlarged photo too: the tree opens on top of it, and closing returns there.
    page.locator(".inspector .inspector-image").click()
    lightbox = page.locator(".lightbox")
    lightbox.get_by_role("button", name="View lineage tree").click()
    expect(tree).to_be_visible()
    box = tree.bounding_box()
    on_top = page.evaluate("([x, y]) => !!document.elementFromPoint(x, y).closest('.lineage-dialog')",
                           [box["x"] + box["width"] / 2, box["y"] + 20])
    assert on_top, "the lineage tree opened behind the enlarged photo"
    page.keyboard.press("Escape")
    expect(tree).to_have_count(0)
    expect(lightbox).to_be_visible()
    page.keyboard.press("Escape")
    expect(lightbox).to_have_count(0)
    # A step's job opens the log on that job.
    events.nth(0).click()
    tree.get_by_role("link", name=re.compile(r"^job #\d+ index")).click()
    expect(page).to_have_url(re.compile(r"/logs\?run=\d+&photo=\d+"))
    expect(page.locator(".job-head[aria-expanded=true]")).to_have_count(1)
    page.go_back()
    expect(page.locator(".inspector")).to_be_visible()
    page.locator(".inspector").get_by_role("link", name="Open in the log").click()
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

    # Stats, beside Settings: the library in figures, each leading to what is behind it.
    page.get_by_role("link", name="Stats").click()
    expect(page).to_have_url(re.compile(r"/stats$"))
    tiles = page.locator(".stat-tile")
    expect(tiles.filter(has_text="Photos")).to_contain_text(f"{PHOTOS:,}")
    expect(page.locator(".stat-panel h3")).to_have_count(6)
    expect(page.locator(".stat-panel", has_text="Duplicates")).to_contain_text("Extra copies")
    # Aligned: fixed columns, and every panel in a row as tall as the row.
    boxes = page.locator(".stat-panel").evaluate_all(
        "ps => ps.map(p => { const r = p.getBoundingClientRect(); return [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)]; })")
    rows = {}
    for left, top, width, height in boxes:
        rows.setdefault(top, []).append((left, width, height))
    for top, row in rows.items():
        assert len({w for _, w, _ in row}) == 1 and len({h for _, _, h in row}) == 1, f"a row of uneven panels: {row}"
    lefts = [sorted(l for l, _, _ in row) for row in rows.values()]
    assert all(r == lefts[0][:len(r)] for r in lefts), f"columns do not line up: {lefts}"
    shot("9-stats")
    # A format row opens the Library showing only that type.
    page.locator(".stat-bars a.bar-label", has_text="JPG").click()
    expect(page).to_have_url(re.compile(r"type=jpg"))
    expect(page.locator(".dates-filter-line")).to_contain_text("Showing only JPG")
    page.go_back()
    tiles.filter(has_text="Failed attempts").click()
    expect(page).to_have_url(re.compile(r"/logs\?status=Failed"))
    page.go_back()
    # The chart counts dates taken: here only the two photos with an EXIF date (2023).
    expect(page.locator(".year-bar")).to_have_count(1)
    page.locator(".year-bar", has_text="2023").click()
    expect(page).to_have_url(re.compile(r"date=2023"))
    expect(page.locator(".dates-filter-line")).to_contain_text("Showing only 2023")
    page.locator(".dates-filter-line").get_by_role("button", name="Show all dates").click()

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
    views = page.locator(".views")
    widths = views.locator("button").evaluate_all("bs => bs.map(b => Math.round(b.getBoundingClientRect().width))")
    undated_filter.click()
    expect(page).to_have_url(re.compile(r"undated=1"))
    expect(page.locator(".pager").first).to_contain_text(f"{PHOTOS - 2:,} photos")
    # The views keep their real counts, and the buttons their widths.
    expect(views).to_contain_text(f"All photos ({PHOTOS:,})")
    after = views.locator("button").evaluate_all("bs => bs.map(b => Math.round(b.getBoundingClientRect().width))")
    assert after == widths, f"the view buttons changed width: {widths} -> {after}"
    undated_filter.click()
    expect(page).not_to_have_url(re.compile(r"undated=1"))
    # All photos resets every filter: No capture date, the dates and the search.
    undated_filter.click()
    page.get_by_role("navigation", name="Dates").get_by_label("Show only 2019").check()
    page.locator(".search").fill("photo")
    expect(page).to_have_url(re.compile(r"q=photo"))
    page.get_by_role("button", name=re.compile(r"^All photos")).click()
    expect(page).not_to_have_url(re.compile(r"undated=1|date=|q="))
    expect(page.locator(".search")).to_have_value("")
    expect(page.locator(".pager").first).to_contain_text(f"{PHOTOS:,} photos")

    # A photo with an EXIF date: shown from EXIF, one note for the missing time zone.
    page.locator(".search").fill("photo-000")
    expect(page.locator(".card")).to_have_count(1, timeout=5_000)
    page.locator(".card-image").first.click()
    expect(inspector).to_contain_text("2023-01-15 09:30:00")
    expect(inspector.locator(".section-note")).to_contain_text("recorded no time zone")
    expect(inspector.locator("th", has_text="*")).to_have_count(0)
    # Its lineage has a duplicate branch; the duplicate's path opens that photo.
    inspector.get_by_role("button", name="View lineage tree").click()
    tree = page.get_by_role("dialog", name=re.compile(r"^Lineage of "))
    duplicate = tree.locator(".lineage-kind", has_text="Duplicate")
    expect(duplicate).to_have_count(1)
    # The gallery shows the copy the catalog keeps as the original; the other is the duplicate.
    shown = inspector.locator(".inspector-head h2").inner_text()
    other = "photo-000.jpg" if shown == "copy-of-000.jpg" else "copy-of-000.jpg"
    tree.get_by_role("button", name=re.compile(re.escape(other))).click()
    expect(tree).to_have_count(0)
    expect(inspector.locator(".inspector-head h2")).to_have_text(other)
    page.keyboard.press("Escape")
    page.locator(".card-image").first.click()
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
print("web interface: first run, index, scrolling, date tree, inspector, divider, selection, copy, "
      "stats, settings, backups, dates, select, show only selected, search and phone layout ok")
