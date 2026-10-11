"""Browsing, browser-persisted pins, exclusive filters, links, selection and reflow."""
import os
import re
import sys
import time
import uuid
from playwright.sync_api import sync_playwright, expect

base = sys.argv[1]
with sync_playwright() as p:
    request = p.request.new_context(base_url=base)
    assert request.post('/api/v1/catalog').ok
    settings = request.get('/api/v1/settings').json()
    values = {'small_image_min': 800, 'suspicious_min_year': 2024}
    response = request.put('/api/v1/settings', data={'values': values,
        'revisions': {key: settings[key]['revision'] for key in values}})
    assert response.ok, response.text()
    def job(mode):
        response = request.post('/api/v1/jobs/start', data={'mode': mode})
        assert response.ok, response.text()
        ident = response.json()['id']
        for _ in range(600):
            if request.get('/api/v1/jobs/active').json()['active'] is None: return ident
            time.sleep(.2)
        raise AssertionError('Job did not finish')
    job('index')
    copied = job('copy')
    suspicious_count = request.get('/api/v1/photos?view=organized').json()['chips']['suspicious']
    browser = p.chromium.launch()
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(base + '/?view=organized')
    main = page.get_by_role('navigation', name='Main', exact=True)
    def choose(label): return main.get_by_role('button', name=re.compile('^' + label + r'(?: \d|$)'))
    def pin(label): return main.get_by_role('button', name='Pin ' + label, exact=True)
    def unpin(label): return main.get_by_role('button', name='Unpin ' + label, exact=True)
    # The clear action lives beside Look into, with space reserved while hidden.
    clear = main.get_by_role('button', name='Clear all filters', exact=True)
    expect(clear).not_to_be_visible()
    initial_filter_y = choose('Has similar photos').bounding_box()['y']
    # Review later is available and counted immediately in Library, even at zero.
    expect(choose('Review later')).not_to_have_attribute('aria-disabled', 'true')
    expect(choose('Review later').locator('.sidebar-count')).to_have_text('0')
    pid = request.get('/api/v1/photos?view=organized').json()['items'][0]['id']
    detail = request.get(f'/api/v1/photos/{pid}/review').json()
    response = request.post(f'/api/v1/photos/{pid}/review', data={
        'photo_id': pid, 'sha1': detail['sha1'], 'revision': detail['revision'],
        'reason': 'later', 'action': 'later', 'note': '', 'request_id': uuid.uuid4().hex})
    assert response.ok, response.text()
    page.reload()
    expect(choose('Review later').locator('.sidebar-count')).to_have_text('1')
    choose('Review later').click()
    expect(page.locator('.card-check input')).to_have_count(1)
    expect(page).to_have_url(re.compile('view=organized'))
    main.get_by_role('link', name=re.compile('^Needs review')).click()
    expect(choose('Review later')).to_have_attribute('aria-pressed', 'true')
    expect(choose('Review later').locator('.sidebar-count')).to_have_text('1')
    main.get_by_role('link', name=re.compile('^Library')).click()
    expect(choose('Review later')).to_have_attribute('aria-pressed', 'true')
    pin('Review later').click()
    expect(choose('Small images')).to_have_attribute('aria-disabled', 'true')
    expect(choose('Small images')).to_have_attribute('title', re.compile('Unpin Review later'))
    page.reload()
    expect(unpin('Review later')).to_have_attribute('aria-pressed', 'true')
    expect(choose('Review later').locator('.sidebar-count')).to_have_text('1')
    page.get_by_role('button', name='Clear all filters', exact=True).click()
    expect(clear).not_to_be_visible()
    assert abs(choose('Has similar photos').bounding_box()['y'] - initial_filter_y) < 1
    # Clear all includes source folder restrictions, preserves the place, and clears search.
    page.goto(base + '/?view=unorganized&tree=1&folder=generated&q=missing')
    expect(clear).to_be_visible()
    assert abs(choose('Has similar photos').bounding_box()['y'] - initial_filter_y) < 1
    clear.click()
    expect(page).not_to_have_url(re.compile(r'folder=|q='))
    expect(page).to_have_url(re.compile('tree=1'))
    page.goto(base + '/?view=organized')
    # Clicking another gallery photo resets the tab; explicit tab URLs still restore.
    page.locator('.card-image').nth(0).click()
    inspector = page.locator('.inspector')
    expect(inspector.get_by_role('tab', name='Photo information', exact=True)).to_have_attribute('aria-selected', 'true')
    inspector.get_by_role('tab', name='Similar photos', exact=True).click()
    page.reload()
    expect(inspector.get_by_role('tab', name='Similar photos', exact=True)).to_have_attribute('aria-selected', 'true')
    # Hold each detail response so an intermediate single-tab layout cannot pass unnoticed.
    pending_details = []
    page.route(re.compile(r'/api/v1/photos/\d+/inspect$'), lambda route: pending_details.append(route))
    baseline = inspector.get_by_role('tab', name='Photo information', exact=True).bounding_box()
    def check_loading_tabs(selected):
        expect(inspector.locator('.inspector-side')).to_have_attribute('aria-busy', 'true')
        expect(inspector.get_by_role('tab')).to_have_count(2)
        expect(inspector.get_by_role('tab', name=selected, exact=True)).to_have_attribute('aria-selected', 'true')
        box = inspector.get_by_role('tab', name='Photo information', exact=True).bounding_box()
        assert abs(box['width'] - baseline['width']) < 2, (box, baseline)
        # Wait for the request without releasing it; inspect the actual loading render.
        for _ in range(100):
            if pending_details: break
            page.wait_for_timeout(20)
        assert pending_details
        if os.environ.get('SHOTS'): page.screenshot(path=f"{os.environ['SHOTS']}/inspector-loading-{selected.replace(' ', '-')}.png")
        pending_details.pop(0).continue_()
        expect(inspector.locator('.inspector-side')).to_have_attribute('aria-busy', 'false')
    page.locator('.card-image').nth(1).click()
    check_loading_tabs('Photo information')
    inspector.get_by_role('tab', name='Similar photos', exact=True).click()
    inspector.get_by_role('button', name='Next photo', exact=True).click()
    check_loading_tabs('Similar photos')
    page.unroute(re.compile(r'/api/v1/photos/\d+/inspect$'))
    expect(inspector.get_by_role('tab', name='Similar photos', exact=True)).to_have_attribute('aria-selected', 'true')
    inspector.get_by_role('button', name='Close', exact=True).click()
    first = page.locator('.card-check input').first
    first.check()
    selected = page.get_by_role('region', name='Selection')
    choose('No capture date').click()
    expect(choose('No capture date')).to_have_attribute('aria-pressed', 'true')
    expect(choose('Suspicious dates').locator('.sidebar-count')).to_have_text(f'{suspicious_count:,}')
    choose('Suspicious dates').click()
    expect(choose('No capture date')).to_have_attribute('aria-pressed', 'false')
    expect(choose('Suspicious dates')).to_have_attribute('aria-pressed', 'true')
    pin('Small images').click()
    choose('No capture date').click()
    expect(choose('Suspicious dates')).to_have_attribute('aria-pressed', 'false')
    expect(choose('Small images')).to_have_attribute('aria-pressed', 'true')
    expect(choose('No capture date')).to_have_attribute('aria-pressed', 'true')
    expect(selected).to_contain_text('1 photo selected')
    selected.get_by_role('button', name='Clear selection').click()
    page.reload()
    expect(unpin('Small images')).to_have_attribute('aria-pressed', 'true')
    expect(choose('Small images')).to_have_attribute('aria-pressed', 'true')
    main.get_by_role('link', name=re.compile('^Needs review')).click()
    expect(choose('Review later')).to_have_attribute('aria-disabled', 'true')
    expect(choose('Review later')).to_have_attribute('title', re.compile('Unpin Small images'))
    unpin('Small images').click()
    choose('Review later').click()
    expect(choose('Small images')).to_have_attribute('aria-pressed', 'false')
    pin('Review later').click()
    expect(choose('Small images')).to_have_attribute('aria-disabled', 'true')
    page.get_by_role('button', name='Clear all filters', exact=True).click()
    expect(pin('Review later')).to_have_attribute('aria-pressed', 'false')
    expect(choose('Review later')).to_have_attribute('aria-pressed', 'false')
    # An explicit job link is exact even though a pin is saved. Choosing a normal
    # place restores applicable pins; unavailable pins stay removable.
    pin('Small images').click()
    page.goto(base + '/?view=organized&run=' + str(copied))
    expect(choose('Small images')).to_have_attribute('aria-pressed', 'false')
    expect(unpin('Small images')).to_have_attribute('aria-pressed', 'true')
    main.get_by_role('link', name=re.compile('^Library')).click()
    expect(choose('Small images')).to_have_attribute('aria-pressed', 'true')
    main.get_by_role('link', name=re.compile('^Not organized')).click()
    expect(choose('Small images')).to_have_attribute('aria-disabled', 'true')
    expect(unpin('Small images')).not_to_have_attribute('aria-disabled', 'true')
    main.get_by_role('link', name=re.compile('^Library')).click()
    # Turning off a pinned filter clears its pin, too; it does not return on reload.
    choose('Small images').click()
    page.reload()
    expect(pin('Small images')).to_have_attribute('aria-pressed', 'false')
    expect(choose('Small images')).to_have_attribute('aria-pressed', 'false')
    pin('Small images').focus()
    page.keyboard.press('Enter')
    expect(unpin('Small images')).to_have_attribute('aria-pressed', 'true')
    for mode in ('light', 'dark'):
        page.evaluate("mode => {localStorage.setItem('ns.theme', mode); window.dispatchEvent(new StorageEvent('storage',{key:'ns.theme',newValue:mode}));}", mode)
        for width, height in [(1440, 1000), (800, 500)]:
            page.set_viewport_size({'width': width, 'height': height})
            if width <= 800: page.get_by_role('button', name='Menu', exact=True).click()
            expect(unpin('Small images')).to_be_visible()
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth + 1')
            if os.environ.get('SHOTS'): page.screenshot(path=f"{os.environ['SHOTS']}/filter-pins-{mode}-{width}.png")
            if width <= 800: page.keyboard.press('Escape')
    assert not errors, errors
    browser.close()
print('PASS: filter replacement, pin persistence, counts, exclusive reminders, exact links, selection and reflow')
