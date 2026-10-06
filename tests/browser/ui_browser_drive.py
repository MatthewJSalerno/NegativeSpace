"""Run just the shared UI checks in the same isolated browser fixture.

    DRIVER=ui_browser_drive.py sh tests/browser/webui_browser_test.sh
"""
import sys
import time
from playwright.sync_api import sync_playwright
from ui_browser_checks import check_ui

base = sys.argv[1]
with sync_playwright() as p:
    browser = p.chromium.launch()
    request = p.request.new_context(base_url=base)
    assert request.post('/api/v1/catalog').ok
    run = request.post('/api/v1/jobs/start', data={"mode": "index"}).json()
    for _ in range(180):
        result = request.get(f'/api/v1/runs/{run["id"]}').json()
        if (result['status'] == 'Completed'
                and request.get('/api/v1/jobs/active').json()['active'] is None):
            break
        time.sleep(1)
    else:
        raise AssertionError('Index did not complete')
    check_ui(browser, base, None)
    browser.close()
