"""Request counts and job-finish freshness through the real job feed."""
import json
import os
import sys
import time
from collections import Counter
from urllib.parse import urlsplit
from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    request = p.request.new_context(base_url=sys.argv[1])
    assert request.post('/api/v1/catalog').ok

    def job(mode):
        response = request.post('/api/v1/jobs/start', data={'mode': mode})
        assert response.ok, response.text()
        job_id = response.json()['id']
        for _ in range(600):
            state = request.get('/api/v1/jobs/active').json()
            if state['active'] is None and state['last']['id'] == job_id:
                return job_id
            time.sleep(.1)
        raise AssertionError('Job did not finish')

    job('index')
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    counts = Counter()
    page.on('request', lambda r: counts.update([urlsplit(r.url).path]) if r.method == 'GET' else None)
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    for path, target, selector in [('/stats', '/api/v1/stats', '.stat-tile'),
                                   ('/logs', '/api/v1/runs', '.logs'),
                                   ('/', '/api/v1/photos/folders', '.card')]:
        counts.clear()
        started = time.monotonic()
        page.goto(sys.argv[1] + path)
        expect(page.locator(selector).first).to_be_visible()
        # Let the real initial snapshot and subsequent unchanged snapshots arrive.
        page.wait_for_timeout(2200)
        print(json.dumps({'page': path, 'counts': dict(counts), 'settled_seconds': round(time.monotonic()-started, 3)}), flush=True)
        assert counts[target] == 1, (path, target, counts)
    page.goto(sys.argv[1] + '/stats')
    expect(page.locator('.stat-tile').first).to_be_visible()
    page.wait_for_timeout(1200)
    before = counts['/api/v1/stats']
    copied = job('copy')
    expect(page.locator('.finished-banner')).to_contain_text(f'Job #{copied}')
    expect(page.locator('.stat-tile').filter(has_text='In Library')).to_contain_text('100%')
    page.wait_for_timeout(1200)
    assert counts['/api/v1/stats'] == before + 1, counts
    # Stats geometry is an intentional shared contract, in either theme/reflow.
    for mode in ('light', 'dark'):
        page.emulate_media(color_scheme=mode)
        for width in (1440, 600):
            page.set_viewport_size({'width': width, 'height': 1000})
            geometry = page.evaluate('''() => {
                const tile = document.querySelector('.stat-tile');
                tile.classList.add('tile-warn');
                const border = getComputedStyle(tile).borderLeftWidth;
                const cell = document.querySelector('.stat-folders td');
                return {border, padding: cell && getComputedStyle(cell).paddingLeft};
            }''')
            assert geometry == {'border': '4px', 'padding': '8px'}, geometry
            if os.environ.get('SHOTS'):
                page.screenshot(path=f"{os.environ['SHOTS']}/requests-stats-{mode}-{width}.png", full_page=True)
    assert not errors, errors
    browser.close()
print('Initial request counts, finished-job refresh and Stats geometry passed')
