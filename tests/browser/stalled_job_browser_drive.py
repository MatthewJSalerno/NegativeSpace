"""User choice when real generated scan work stops reporting progress."""
import os
import sys
import time
from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    request = p.request.new_context(base_url=sys.argv[1])
    assert request.post('/api/v1/catalog').ok
    run = request.post('/api/v1/jobs/start', data={'mode':'index'}).json()['id']
    for _ in range(300):
        if request.get('/api/v1/status').json()['indexed']:
            break
        time.sleep(.1)
    else:
        raise AssertionError('Ready fixture photos were not indexed')
    page = browser.new_page(viewport={'width':1440,'height':1000})
    page.clock.install()
    page.goto(sys.argv[1])
    expect(page.locator('.drawer')).to_contain_text('Reading photos', timeout=30000)
    page.clock.fast_forward(125000)
    expect(page.locator('.drawer')).to_contain_text('No progress recorded for two minutes.')
    assert request.get('/api/v1/jobs/active').json()['active']['id'] == run
    page.get_by_role('button', name='Keep waiting', exact=True).click()
    expect(page.get_by_role('button', name='Keep waiting', exact=True)).to_have_count(0)
    assert request.get('/api/v1/jobs/active').json()['active']['id'] == run
    page.clock.fast_forward(125000)
    expect(page.get_by_role('button', name='Keep waiting', exact=True)).to_be_visible()
    page.set_viewport_size({'width':720,'height':900})
    if os.environ.get('SHOTS'):
        page.screenshot(path=f"{os.environ['SHOTS']}/stalled-job-warning.png", full_page=True)
    page.get_by_role('button', name='Cancel job', exact=True).click()
    expect(page.locator('.finished-banner')).to_contain_text('was cancelled', timeout=30000)
    assert request.get('/api/v1/jobs/active').json()['active'] is None
    assert request.get('/api/v1/status').json()['library_photos'] == 0
    browser.close()
print('No-progress warning, Keep waiting, explicit cancel and engine-lock release passed')
