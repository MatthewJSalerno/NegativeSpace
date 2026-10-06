"""Prerequisite scan failures remain visible in Copy/Move banners and Logs.

    DRIVER=transfer_outcome_browser_drive.py sh tests/webui_browser_test.sh

Uses only the harness's disposable, generated source files.
"""
import re
import sys
import time
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    request = p.request.new_context(base_url=sys.argv[1])
    assert request.post('/api/v1/catalog').ok

    def run_job(**body):
        response = request.post('/api/v1/jobs/start', data=body)
        assert response.status == 202, response.text()
        run_id = response.json()['id']
        for _ in range(600):
            run = request.get(f'/api/v1/runs/{run_id}').json()
            if run['status'] not in ('Preparing', 'Running', 'Cancelling'):
                return run
            time.sleep(.2)
        raise AssertionError('Job did not finish')

    run_job(mode='index')
    for index, (mode, all_failed) in enumerate((('copy', False), ('copy', True),
                                               ('move', False), ('move', True))):
        names = [f'photo-{10 + index * 2 + offset:03d}.jpg' for offset in (0, 1)]
        ids = []
        for name in names:
            found = request.get('/api/v1/photos', params={'q':name}).json()['items']
            assert len(found) == 1
            ids.append(found[0]['id'])
        (Path('/src') / names[0]).write_text('no longer a photo')
        if all_failed:
            (Path('/src') / names[1]).unlink()
        run = run_job(mode=mode, file_ids=ids)
        outcome = run['outcome']
        assert (outcome['verdict'], outcome['failed'], outcome['total']) == (
            'none_succeeded' if all_failed else 'partial', 2 if all_failed else 1, 2), outcome
        # Move's good photo is copied-only because this harness mounts source :ro.
        page = browser.new_page(viewport={'width':1400, 'height':900})
        page.goto(sys.argv[1])
        banner = page.locator('.finished-banner')
        expect(banner).to_contain_text(f"{outcome['failed']} failed")
        expect(banner).to_contain_text("finished, nothing succeeded" if all_failed else "finished with failures")
        link = banner.get_by_role('link', name='View failures', exact=True)
        expect(link).to_be_visible()
        link.click()
        expect(page).to_have_url(re.compile(r'run=' + str(run['id']) + r'(?:&|$)'))
        expect(page).to_have_url(re.compile(r'status=Failed'))
        expect(page.locator('.log-table tbody tr')).to_have_count(outcome['failed'])
        page.close()
    browser.close()
print('Copy/Move mixed and all-failed scans: counts, banners and failure links passed')
