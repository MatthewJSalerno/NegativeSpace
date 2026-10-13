"""An external source removal updates the existing Library and history UI."""
import os
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

base = sys.argv[1]
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    request = pw.request.new_context(base_url=base)
    def get(path):
        response = request.get('/api/v1/' + path)
        assert response.ok, response.text()
        return response.json()
    def job(mode):
        response = request.post('/api/v1/jobs/start', data={'mode':mode})
        assert response.ok, response.text()
        run_id = response.json()['id']
        for _ in range(600):
            run = get(f'runs/{run_id}')
            if run['status'] not in ('Preparing', 'Running', 'Cancelling') and get('jobs/active')['active'] is None:
                assert run['status'] == 'Completed', run
                return run
            time.sleep(.2)
        raise AssertionError('job did not settle')
    assert request.post('/api/v1/catalog').ok
    job('index'); job('copy')
    before = get('status')
    photo = get('photos?view=organized')['items'][10]
    detail = get(f"photos/{photo['id']}/inspect")
    original = Path('/src') / Path(detail['source_path']).relative_to('/data/source')
    original.unlink()  # Only this harness's generated, disposable source.
    result = job('index')
    assert result['outcome']['failed'] == 0, result
    assert get('status')['eligible']['move'] == before['eligible']['move'] - 1
    page = browser.new_page(viewport={'width':1440, 'height':1000})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(f"{base}/?view=organized&photo={photo['id']}")
    panel = page.locator('.inspector')
    expect(panel).to_contain_text('Found at the destination')
    expect(panel.get_by_role('region', name='Files needing verification')).to_have_count(0)
    history = panel.locator('.photo-history')
    expect(history).to_contain_text('Found at destination')
    if os.environ.get('SHOTS'):
        page.screenshot(path=os.environ['SHOTS'] + '/copied-source-library.png')
    history.get_by_role('link', name='Open in the log').click()
    page.locator('.job-head').filter(has_text=f"Job #{result['id']} ·").click()
    expect(page.get_by_text('The original is no longer at its source location', exact=False).first).to_be_visible()
    if os.environ.get('SHOTS'):
        page.screenshot(path=os.environ['SHOTS'] + '/copied-source-history.png')
    assert not errors, errors
    browser.close()
print('PASS: externally removed original stays in Library with verified history and updated Move count')
