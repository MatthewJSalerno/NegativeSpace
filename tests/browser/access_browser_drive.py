"""Instance access settings through real generated-host aliases, no external DNS."""
import os
import sys
import time
from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    request = p.request.new_context(base_url=sys.argv[1])
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    assert request.post("/api/v1/catalog").ok
    page.goto(sys.argv[1])
    for n in range(4):
        if n == 1:
            page.get_by_label("Small-image reminders (required)").select_option("off")
        page.get_by_role("button", name="Next", exact=True).click()
    expect(page.locator(".settings-step")).to_have_text("Step 5 of 5 Access")
    field = page.get_by_label("Additional allowed addresses", exact=True)
    field.fill("https://invalid.example")
    page.get_by_role("button", name="Save and continue", exact=True).click()
    expect(page.get_by_role("alert")).to_contain_text("without schemes, ports, paths or wildcards")
    field.fill("review.example, other.example")
    page.get_by_role("button", name="Save and continue", exact=True).click()
    expect(page.get_by_role("button", name="Index source", exact=True)).to_be_visible()
    assert request.get("/api/v1/access").json()["hosts"] == ["review.example", "other.example"]
    run = request.post("/api/v1/jobs/start", data={"mode": "index"}).json()["id"]
    for _ in range(300):
        if request.get("/api/v1/jobs/active").json()["active"] is None and request.get(f"/api/v1/runs/{run}").json()["status"] == "Completed":
            break
        time.sleep(.1)
    else:
        raise AssertionError("Generated Index did not complete")
    page.reload()

    page.get_by_role("button", name="Settings", exact=True).click()
    page.get_by_role("tab", name="Access", exact=True).click()
    expect(field).to_have_value("review.example, other.example")
    field.fill("review.example, other.example, stale.example")
    current = request.get("/api/v1/access").json()
    assert request.put("/api/v1/access", data={"hosts": ["review.example", "other.example", "new.example"], "revision": current["revision"]}).ok
    page.get_by_role("button", name="Save settings", exact=True).click()
    expect(page.get_by_role("alert")).to_contain_text("changed elsewhere")
    page.get_by_role("button", name="Reload settings", exact=True).click()
    expect(field).to_have_value("review.example, other.example, new.example")
    field.fill("review.example, other.example")
    page.get_by_role("button", name="Save settings", exact=True).click()
    expect(page.get_by_role("status").filter(has_text="Saved.")).to_be_visible()
    for width in (1440, 720):
        page.set_viewport_size({"width": width, "height": 1000})
        expect(field).to_be_visible()
        assert page.get_by_role("dialog", name="Settings", exact=True).evaluate("e => e.scrollWidth <= e.clientWidth + 1")
        if os.environ.get("SHOTS"):
            page.screenshot(path=f"{os.environ['SHOTS']}/access-settings-{width}.png")
    page.get_by_role("button", name="Close settings", exact=True).click()
    # Real alternative authority, served by the same isolated web container.
    page.goto("http://review.example:8080/")
    page.get_by_role("button", name="Settings", exact=True).click()
    page.get_by_role("tab", name="Access", exact=True).click()
    field.fill("other.example")
    page.get_by_role("button", name="Save settings", exact=True).click()
    confirm = page.get_by_role("dialog", name="Remove the address you are using?", exact=True)
    expect(confirm).to_be_visible()
    expect(confirm.get_by_role("button", name="Cancel", exact=True)).to_be_focused()
    confirm.get_by_role("button", name="Cancel", exact=True).click()
    assert "review.example" in request.get("/api/v1/access").json()["hosts"]
    page.get_by_role("button", name="Save settings", exact=True).click()
    confirm.get_by_role("button", name="Remove this address and save", exact=True).click()
    expect(page.get_by_role("status").filter(has_text="This address is no longer allowed")).to_be_visible()
    page.reload()
    expect(page.get_by_text("This address is not allowed.", exact=False)).to_be_visible(timeout=15000)
    page.goto("http://other.example:8080/")
    expect(page.get_by_role("button", name="Settings", exact=True)).to_be_visible()
    assert not errors, errors
    browser.close()
print("Access setup, invalid input, persisted values, conflicts, reflow, confirmed removal and recovery passed")
