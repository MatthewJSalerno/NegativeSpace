"""The thumbnail cache panel in Settings › Performance (webui-spec 4.2.1): sizes by kind,
Free up for detail previews, Repair as a job followed in the panel, and the Stats link."""
import os
import re
import sys
import time
from playwright.sync_api import sync_playwright, expect

base = sys.argv[1]
with sync_playwright() as p:
    browser = p.chromium.launch()
    request = p.request.new_context(base_url=base)
    assert request.post('/api/v1/catalog').ok

    def wait(run):
        for _ in range(600):
            status = request.get(f'/api/v1/runs/{run}').json()
            if status['status'] not in ('Preparing', 'Running', 'Cancelling') and request.get('/api/v1/status').json()['active_job'] is None:
                assert status['status'] == 'Completed', status
                return status
            time.sleep(.2)
        raise AssertionError('Job timed out')
    for mode in ('index', 'copy'):
        response = request.post('/api/v1/jobs/start', data={'mode': mode})
        assert response.ok, response.text()
        wait(response.json()['id'])
    # Opening two photos makes their detail previews.
    ids = [item['id'] for item in request.get('/api/v1/photos?view=organized').json()['items'][:2]]
    for photo in ids:
        assert request.get(f'/api/v1/photos/{photo}/thumbnail?size=preview').ok
    grid = request.get('/api/v1/thumbnails').json()['grid']

    page = browser.new_page(viewport={'width': 1440, 'height': 1000}, color_scheme='dark')
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(base + '/stats')
    page.get_by_role('button', name='Manage thumbnails', exact=True).click()
    expect(page.get_by_role('tab', name='Performance')).to_have_attribute('aria-selected', 'true')
    panel = page.locator('section.thumbnails')
    expect(panel.get_by_role('heading', name=re.compile('^Thumbnail cache — '))).to_be_visible()
    expect(panel.get_by_text(f"Grid thumbnails · ", exact=False)).to_contain_text(f"{grid['photos']} photos")
    expect(panel.get_by_text('Detail previews · ', exact=False)).to_contain_text('2 photos opened')
    panel.scroll_into_view_if_needed()
    if os.environ.get('SHOTS'): page.screenshot(path=os.path.join(os.environ['SHOTS'], 'thumbnails-dark.png'))

    # Free up acts at once and reports what it freed; previews are then gone.
    panel.get_by_role('button', name=re.compile('^Free up ')).click()
    expect(panel.get_by_role('status')).to_contain_text('from 2 detail previews.')
    expect(panel.get_by_text('Detail previews · ', exact=False)).to_contain_text('0 photos opened')
    expect(panel.get_by_role('button', name='Free up', exact=True)).to_be_disabled()
    expect(panel.get_by_text('No detail previews are stored.', exact=True)).to_be_visible()
    assert request.get('/api/v1/thumbnails').json()['previews'] == {'photos': 0, 'bytes': 0}

    # Repair is a job: it is followed in the panel and settles with its summary.
    panel.get_by_role('button', name='Repair grid thumbnails', exact=True).click()
    expect(panel.get_by_role('status')).to_contain_text('Thumbnail rebuild')
    runs = request.get('/api/v1/runs?limit=1').json()['runs']
    assert runs[0]['mode'] == 'REBUILD', runs[0]
    wait(runs[0]['id'])
    expect(panel.get_by_role('button', name='Repair grid thumbnails', exact=True)).to_be_enabled()
    expect(panel.get_by_role('button', name='Rebuild all grid thumbnails', exact=True)).to_be_enabled()
    expect(panel.get_by_role('status')).to_contain_text(f"#{runs[0]['id']}")
    assert request.get('/api/v1/thumbnails').json()['grid'] == grid

    if os.environ.get('SHOTS'):
        page.get_by_role('tab', name='Backups').click()
        page.screenshot(path=os.path.join(os.environ['SHOTS'], 'backups-dark.png'))
        page.get_by_role('tab', name='Performance').click()
        panel.scroll_into_view_if_needed()
        page.screenshot(path=os.path.join(os.environ['SHOTS'], 'thumbnails-after-dark.png'))
    # Desktop reflow keeps the panel inside Settings.
    page.set_viewport_size({'width': 800, 'height': 700})
    panel.scroll_into_view_if_needed()
    assert page.locator('.modal-shell > .settings').evaluate('e => e.scrollWidth <= e.clientWidth+1')
    if os.environ.get('SHOTS'): page.screenshot(path=os.path.join(os.environ['SHOTS'], 'thumbnails-reflow.png'))
    assert not errors, errors
    browser.close()
print('Thumbnail cache sizes, Free up, Repair as a job, the Stats link and reflow passed')
