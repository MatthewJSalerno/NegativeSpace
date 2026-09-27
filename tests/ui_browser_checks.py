"""Shared UI behavior, against the built app and synthetic browser-suite catalog."""
import re
from playwright.sync_api import expect


def check_ui(browser, base, _shot):
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(base)
    expect(page.locator(".card").first).to_be_visible()

    # A modal owns focus, contains both Tab directions and returns to its opener.
    settings = page.get_by_role("button", name="Settings", exact=True)
    settings.click()
    modal = page.get_by_role("dialog", name="Settings", exact=True)
    expect(modal).to_be_visible()
    close = modal.get_by_role("button", name="Close settings")
    expect(close).to_be_focused()
    save = modal.get_by_role("button", name="Save settings", exact=True)
    expect(save).to_be_visible()
    close.focus()
    page.keyboard.press("Shift+Tab")
    expect(save).to_be_focused()
    page.keyboard.press("Tab")
    expect(close).to_be_focused()
    # Inertness also prevents programmatically focusing a background action.
    settings.evaluate("e => e.focus()")
    expect(close).to_be_focused()
    workers = modal.get_by_label("Maximum worker processes")
    original = workers.input_value()
    workers.fill("0")
    save.click()
    expect(workers).to_be_focused()
    expect(workers).to_have_attribute("aria-invalid", "true")
    description = workers.get_attribute("aria-describedby")
    assert description and "settings-workers-error" in description
    expect(page.locator("#settings-workers-error")).to_contain_text("at least 1")
    workers.fill(original)
    page.keyboard.press("Escape")
    expect(modal).to_have_count(0)
    expect(settings).to_be_focused()

    # Commands have arrow navigation, disabled-item explanations, submenu return,
    # and trigger restoration. A confirmation starts on its safe action.
    actions = page.get_by_role("button", name=re.compile(r"^Actions"))
    actions.focus()
    page.keyboard.press("Enter")
    menu = page.get_by_role("menu", name="Actions", exact=True)
    expect(menu.get_by_role("menuitem", name=re.compile(r"^Index"))).to_be_focused()
    page.keyboard.press("End")
    move = menu.get_by_role("menuitem", name="Move", exact=True)
    expect(move).to_be_focused()
    page.keyboard.press("ArrowRight")
    sub = page.get_by_role("menu", name="Move", exact=True)
    expect(sub.get_by_role("menuitem").first).to_be_focused()
    page.keyboard.press("ArrowLeft")
    expect(move).to_be_focused()
    page.keyboard.press("ArrowRight")
    page.keyboard.press("End")
    page.keyboard.press("Enter")
    confirm = page.get_by_role("alertdialog")
    expect(confirm.get_by_role("button", name="Cancel", exact=True)).to_be_focused()
    for theme in ("light", "dark"):
        page.emulate_media(color_scheme=theme)
        pair = confirm.get_by_role("button", name="Move", exact=True).evaluate("""e => {
            const s=getComputedStyle(e); return [s.color,s.backgroundColor]; }""")
        def luminance(value):
            values = [int(c) / 255 for c in re.findall(r"\d+", value)[:3]]
            linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in values]
            return sum(c * w for c, w in zip(linear, (.2126, .7152, .0722)))
        light, dark = sorted(map(luminance, pair), reverse=True)
        assert (light + .05) / (dark + .05) >= 4.5, (theme, pair)
    page.keyboard.press("Escape")
    expect(actions).to_be_focused()
    page.emulate_media(color_scheme="light")

    select = page.get_by_role("button", name="Select", exact=True)
    select.focus()
    page.keyboard.press("ArrowDown")
    expect(page.get_by_role("menu", name="Select").get_by_role("menuitem").first).to_be_focused()
    page.keyboard.press("Escape")
    expect(select).to_be_focused()

    # Supplemental help is explicitly operable, described, and dismissible.
    help_button = page.locator(".views .help-trigger").first
    help_button.click()
    expect(help_button).to_have_attribute("aria-expanded", "true")
    expect(page.locator(".views .help-content")).to_contain_text("EXIF")
    page.keyboard.press("Escape")
    expect(help_button).to_have_attribute("aria-expanded", "false")
    expect(help_button).to_be_focused()
    actions.focus()
    actions.hover()  # Leave the help target before testing a fresh pointer entry.
    help_button.hover()
    help_content = page.locator(".views .help-content")
    expect(help_content).to_be_visible()
    help_content.hover()
    page.wait_for_timeout(200)  # The pointer has crossed the bubble's dismissal grace period.
    expect(help_content).to_be_visible()

    # Help from the sticky sidebar must paint above the adjacent photo grid.
    sidebar_help = page.locator(".side-panel .help-trigger:visible").first
    for theme in ("light", "dark"):
        page.emulate_media(color_scheme=theme)
        actions.hover()
        sidebar_help.hover()
        bubble = page.locator(".side-panel .help-content")
        expect(bubble).to_be_visible()
        assert bubble.evaluate("""e => {
            const r = e.getBoundingClientRect();
            return e.contains(document.elementFromPoint(r.right - 8, r.top + r.height / 2));
        }"""), "Sidebar help is covered by adjacent content"
        assert bubble.evaluate("""e => {
            const s = getComputedStyle(e);
            const probe = document.createElement('span');
            probe.style.backgroundColor = 'var(--surface-2)';
            e.append(probe);
            const matches = getComputedStyle(probe).backgroundColor === s.backgroundColor;
            probe.remove(); return matches;
        }"""), "Help must use the subdued theme surface"
    page.emulate_media(color_scheme="light")
    actions.hover()

    # Nested dialogs close one at a time and restore focus to the underlying task.
    page.locator(".card-image").first.click()
    preview_split = page.get_by_role("separator", name="Resize photo preview", exact=True)
    expect(preview_split).to_have_attribute("aria-orientation", "horizontal")
    preview = page.get_by_role("button", name="Enlarge the photo")
    initial_height = preview.bounding_box()["height"]
    preview_split.focus()
    page.keyboard.press("ArrowDown")
    expect(preview_split).to_have_attribute("aria-valuenow", "55")
    assert preview.bounding_box()["height"] > initial_height
    handle = preview_split.bounding_box()
    page.mouse.move(handle["x"] + handle["width"] / 2, handle["y"] + handle["height"] / 2)
    page.mouse.down()
    page.mouse.move(handle["x"] + handle["width"] / 2, handle["y"] - 45, steps=5)
    page.mouse.up()
    saved_share = preview_split.get_attribute("aria-valuenow")
    assert int(saved_share) < 55
    page.reload()
    expect(preview_split).to_have_attribute("aria-valuenow", saved_share)
    # A wide desktop Inspector uses the same separator vertically.
    page.set_viewport_size({"width": 2400, "height": 900})
    outer = page.get_by_role("separator", name="Resize the photo panel", exact=True)
    outer.focus()
    for _ in range(20):
        page.keyboard.press("ArrowLeft")
    expect(preview_split).to_have_attribute("aria-orientation", "vertical")
    preview_split.focus()
    photo_url = page.url
    page.keyboard.press("ArrowRight")
    expect(preview_split).to_have_attribute("aria-valuenow", str(min(75, int(saved_share) + 5)))
    assert page.url == photo_url, "Resizing must not navigate to another photo"
    page.set_viewport_size({"width": 1400, "height": 900})
    page.get_by_role("button", name="Enlarge the photo").click()
    enlarged = page.get_by_role("dialog", name=re.compile(r"^Enlarged:"))
    expect(enlarged.get_by_role("button", name="Close the enlarged photo")).to_be_focused()
    lineage_opener = enlarged.get_by_role("button", name="View lineage tree")
    lineage_opener.click()
    lineage = page.get_by_role("dialog", name=re.compile(r"^Lineage of"))
    expect(lineage.get_by_role("button", name="Close", exact=True)).to_be_focused()
    page.keyboard.press("Escape")
    expect(lineage).to_have_count(0)
    expect(lineage_opener).to_be_focused()
    page.keyboard.press("Escape")
    expect(enlarged).to_have_count(0)
    page.keyboard.press("Escape")

    # A failed appended page stops loading, preserves selection and retries once.
    page.goto(base)
    expect(page.locator(".card").first).to_be_visible()
    selected = page.locator(".card-check input").first
    selected.check()
    selected_label = selected.get_attribute("aria-label")
    failed_requests = []
    def fail_more(route):
        from urllib.parse import urlparse, parse_qs
        number = int(parse_qs(urlparse(route.request.url).query).get("page", ["1"])[0])
        if number > 1:
            failed_requests.append(number)
            route.abort()
        else:
            route.continue_()
    page.route("**/api/v1/photos?*", fail_more)
    page.locator(".page-sentinel").last.scroll_into_view_if_needed()
    retry = page.get_by_role("button", name="Retry: load more photos", exact=True)
    expect(retry).to_be_visible()
    expect(page.locator(".page-sentinel [role=alert]")).to_contain_text("could not be loaded")
    assert failed_requests
    expect(page.get_by_label(selected_label, exact=True)).to_be_checked()
    page.unroute("**/api/v1/photos?*", fail_more)
    retry.click()
    expect(page.locator(".card")).not_to_have_count(60)
    expect(page.get_by_label(selected_label, exact=True)).to_be_checked()
    expect(retry).to_have_count(0)

    # Coarse-pointer/narrow layouts and forced colors preserve operable controls.
    phone = browser.new_page(viewport={"width": 320, "height": 700}, is_mobile=True, has_touch=True)
    phone.goto(base)
    expect(phone.locator(".card").first).to_be_visible()
    phone.get_by_role("button", name=re.compile(r"^Actions")).click()
    box = phone.get_by_role("menu", name="Actions", exact=True).bounding_box()
    assert box and box["x"] >= 0 and box["x"] + box["width"] <= 320, box
    phone.keyboard.press("Escape")
    phone.get_by_role("button", name="Settings", exact=True).click()
    expect(phone.get_by_label("Maximum worker processes")).to_be_visible()
    assert phone.evaluate("document.documentElement.scrollWidth <= innerWidth")
    phone.keyboard.press("Escape")
    photo = phone.locator(".card-image").first
    photo.click()
    phone_inspector = phone.get_by_role("dialog", name="Photo details", exact=True)
    expect(phone_inspector).to_be_visible()
    assert phone_inspector.evaluate("e => e.contains(document.activeElement)")
    phone.get_by_role("button", name="Settings", exact=True, include_hidden=True).evaluate("e => e.focus()")
    assert phone_inspector.evaluate("e => e.contains(document.activeElement)")
    phone.keyboard.press("Escape")
    expect(phone_inspector).to_have_count(0)
    expect(photo).to_be_focused()
    phone.close()
    page.emulate_media(forced_colors="active", reduced_motion="reduce")
    page.goto(base)
    page.get_by_role("button", name="Settings", exact=True).focus()
    assert page.get_by_role("button", name="Settings", exact=True).evaluate("e => getComputedStyle(e).outlineStyle") != "none"
    assert not errors, errors
    page.close()
    print("shared UI: focus, menus, validation, help, theme contrast, retry, narrow layout and forced colors ok")
