"""Drives the built web interface in a real browser (Playwright, headless Chromium).

Run by tests/webui_browser_test.sh against a server holding generated photos. It walks
the first-use path - create the catalog, settings, Scan, the gallery, the Inspector,
selecting photos and copying them - and fails on any browser console error.

The unit suites cannot see the screens; this is what found a gallery that never
refreshed after a job too short to be seen running.
"""
import re
import sys
import time

from playwright.sync_api import expect, sync_playwright

BASE = sys.argv[1]
PHOTOS = int(sys.argv[2])            # distinct photos in the source
DUPLICATES = int(sys.argv[3])        # extra exact copies among them

errors = []
server_errors = []
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.on("console", lambda m: m.type == "error" and not m.text.startswith("Failed to load resource") and errors.append(m.text))
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("response", lambda r: r.status >= 500 and server_errors.append(f"{r.status} {r.url}"))

    page.goto(BASE)
    expect(page.get_by_text("No catalog found")).to_be_visible()
    page.get_by_role("button", name="Create new catalog").click()
    expect(page.get_by_text("Welcome to NegativeSpace")).to_be_visible()
    page.get_by_role("button", name="Save and continue").click()
    expect(page.get_by_text("No photos yet")).to_be_visible()
    expect(page.get_by_role("button", name="Move all")).to_be_disabled()

    page.get_by_role("button", name="Scan the source").click()
    drawer = page.locator(".drawer")
    expect(drawer).to_contain_text("Scan finished", timeout=120_000)
    expect(drawer).to_contain_text(f"{PHOTOS + DUPLICATES:,} new or changed, including {DUPLICATES:,} duplicate")
    # The gallery refreshes itself when the job ends: duplicates fold into their photo.
    expect(page.locator(".card")).to_have_count(min(PHOTOS, 60))
    expect(page.locator(".views")).to_contain_text(f"Not yet organized ({PHOTOS:,})")
    time.sleep(1)
    broken = page.evaluate("[...document.querySelectorAll('.card img')]"
                           ".filter(i => i.complete && i.naturalWidth === 0).length")
    assert broken == 0, f"{broken} grid thumbnails failed to load"

    page.locator(".card-image").first.click()
    inspector = page.locator(".inspector")
    expect(inspector).to_contain_text("Not yet organized")
    expect(inspector.locator(".inspector-image img:not([style*='none'])")).to_be_visible(timeout=15_000)
    first_url = page.url
    page.keyboard.press("ArrowRight")
    expect(page).not_to_have_url(first_url)
    page.keyboard.press("Escape")
    expect(inspector).to_have_count(0)

    checks = page.locator(".card-check input")
    checks.nth(0).click()
    checks.nth(2).click(modifiers=["Shift"])
    expect(page.locator(".action-bar")).to_contain_text("3 photos selected")
    page.get_by_role("button", name="Copy selected").click()
    dialog = page.get_by_role("alertdialog")
    expect(dialog).to_contain_text("Copy 3 selected photos?")
    dialog.get_by_role("button", name="Copy").click()
    expect(drawer).to_contain_text("Copy finished", timeout=60_000)
    expect(drawer).to_contain_text("3 of 3 files copied")
    # A job shorter than one feed update must still refresh the counts.
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
print("web interface: first run, scan, gallery, inspector, selection, copy, settings, search and phone layout ok")
