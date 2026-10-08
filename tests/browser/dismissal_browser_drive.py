"""Banner dismissal is acknowledged, survives page navigation, and exposes failed saves."""
import os
import sys
import time
from playwright.sync_api import sync_playwright, expect

base = sys.argv[1]
with sync_playwright() as p:
    request = p.request.new_context(base_url=base)
    assert request.post('/api/v1/catalog').ok
    response = request.post('/api/v1/jobs/start', data={'mode': 'index'})
    assert response.ok, response.text()
    run = response.json()['id']
    for _ in range(600):
        state = request.get(f'/api/v1/runs/{run}').json()
        if state['status'] not in ('Preparing', 'Running', 'Cancelling') and request.get('/api/v1/jobs/active').json()['active'] is None:
            break
        time.sleep(.2)
    else:
        raise AssertionError('Index did not settle')
    browser = p.chromium.launch()
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(base)
    banner = page.locator('.finished-banner')
    expect(banner).to_be_visible()
    held = []
    held_reads = []
    delay_reads = False
    def delay_write(route):
        if route.request.method == 'PUT':
            held.append(route)
        elif delay_reads:
            held_reads.append(route)
        else:
            route.continue_()
    page.route('**/api/v1/ui-state', delay_write)
    banner.get_by_role('button', name='Dismiss', exact=True).click()
    expect(banner.get_by_role('button', name='Saving…', exact=True)).to_be_disabled()
    assert request.get('/api/v1/ui-state').json()['dismissed_run'] is None
    page.get_by_role('link', name='Logs', exact=True).first.click()
    expect(banner.get_by_role('button', name='Saving…', exact=True)).to_be_disabled()
    assert len(held) == 1
    held.pop().fulfill(status=503, json={'detail': 'Generated save failure'})
    expect(banner.get_by_role('alert')).to_contain_text('Could not save the dismissal')
    expect(banner.get_by_role('button', name='Retry dismissal', exact=True)).to_be_enabled()
    # Shared state retains the actionable error across navigation and narrow reflow.
    page.get_by_role('link', name='Library', exact=True).first.click()
    expect(banner.get_by_role('alert')).to_be_visible()
    page.set_viewport_size({'width': 720, 'height': 900})
    expect(banner.get_by_role('button', name='Retry dismissal', exact=True)).to_be_in_viewport()
    if os.environ.get('SHOTS'):
        page.screenshot(path=os.environ['SHOTS'] + '/dismissal-error.png')
    page.set_viewport_size({'width': 1440, 'height': 1000})
    banner.get_by_role('button', name='Retry dismissal', exact=True).click()
    expect(banner.get_by_role('button', name='Saving…', exact=True)).to_be_disabled()
    # Reload before the request reaches the server must not claim a saved dismissal.
    assert len(held) == 1
    held.pop().abort()
    page.reload()
    expect(banner.get_by_role('button', name='Dismiss', exact=True)).to_be_visible()
    assert request.get('/api/v1/ui-state').json()['dismissed_run'] is None
    # A refresh that started before the write must not overwrite its acknowledgment.
    delay_reads = True
    with page.expect_request(lambda r: r.method == 'GET' and r.url.endswith('/ui-state')):
        page.evaluate("window.dispatchEvent(new Event('focus'))")
    banner.get_by_role('button', name='Dismiss', exact=True).click()
    expect(banner.get_by_role('button', name='Saving…', exact=True)).to_be_disabled()
    page.get_by_role('link', name='Stats', exact=True).click()
    expect(banner.get_by_role('button', name='Saving…', exact=True)).to_be_disabled()
    page.get_by_role('link', name='Logs', exact=True).first.click()
    expect(banner.get_by_role('button', name='Saving…', exact=True)).to_be_disabled()
    with page.expect_response(lambda r: r.request.method == 'PUT' and r.url.endswith('/ui-state')) as saved:
        held.pop().continue_()
    assert saved.value.ok
    expect(banner).to_have_count(0)
    assert request.get('/api/v1/ui-state').json()['dismissed_run'] == run
    assert len(held_reads) == 1
    with page.expect_response(lambda r: r.request.method == 'GET' and r.url.endswith('/ui-state')) as stale:
        held_reads.pop().fulfill(json={'dismissed_run': None})
    assert stale.value.json() == {'dismissed_run': None}
    page.evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
    delay_reads = False
    expect(banner).to_have_count(0)
    page.evaluate('localStorage.clear()')
    page.reload()
    expect(page.locator('.job-list-head')).to_be_visible()
    expect(banner).to_have_count(0)
    # Stale browser values must never hide banners from a replacement catalog.
    page.evaluate("localStorage.setItem('ns.dismissedRun', '999999')")
    page.route('**/api/v1/ui-state', lambda route: route.fulfill(json={'dismissed_run': None}))
    page.reload()
    expect(banner).to_be_visible()
    assert not errors, errors
    browser.close()
print('PASS: delayed/failed dismissal, navigation, interrupted reload, acknowledged reload, and catalog authority')
