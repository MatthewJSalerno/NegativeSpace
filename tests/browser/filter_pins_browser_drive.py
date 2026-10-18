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
    values = {'small_image_min': 800, 'suspicious_min_year': 2020}
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
    # The sidebar owns an unfiltered place's total. A filter shows one matching/whole
    # total, and removing two pins updates the real rows, URL and chip counts each time.
    whole = request.get('/api/v1/photos?view=organized').json()
    total = whole['total']
    summary = page.locator('.gallery-result-count')
    library_count = main.get_by_role('link', name=re.compile('^Library')).locator('.sidebar-count')
    expect(library_count).to_have_text(f'{total:,}')
    expect(page.locator('.card')).to_have_count(min(60, total))
    expect(summary).to_have_count(0)
    expect(page.locator('.pager').get_by_text(f'{total:,} photos', exact=True)).to_have_count(0)
    rows = main.locator('.sidebar-filter-row')
    boxes = rows.evaluate_all('(rows)=>rows.map(e=>{const r=e.getBoundingClientRect();const c=e.querySelector(".sidebar-count").getBoundingClientRect();const p=e.querySelector(".filter-pin").getBoundingClientRect();return {height:r.height,count:c.right,pin:p.x};})')
    assert len({round(b['height'],1) for b in boxes}) == 1, boxes
    assert len({round(b['count'],1) for b in boxes}) == 1, boxes
    assert len({round(b['pin'],1) for b in boxes}) == 1, boxes
    expect(choose('Review later').locator('.sidebar-count')).to_have_text('0')
    baseline_gallery_y = page.locator('.gallery-head').bounding_box()['y']
    if os.environ.get('SHOTS'): page.screenshot(path=f"{os.environ['SHOTS']}/gallery-unfiltered-count.png")
    pin('Has similar photos').click()
    pin('Suspicious dates').click()
    combined = request.get('/api/v1/photos?view=organized&similar=true&suspicious=true&match_min=90&filter_pins=similar,suspicious').json()
    assert 0 < combined['total'] < total, 'The fixture must exercise a real restriction'
    expect(summary).to_have_text(f"Showing {combined['total']:,} of {total:,} photos")
    for label in ('Has similar photos', 'Suspicious dates'):
        expect(unpin(label)).to_have_attribute('aria-pressed', 'true')
        expect(choose(label).locator('.sidebar-count')).to_have_text(f"{combined['total']:,}")
    unpin('Has similar photos').click()
    suspicious_only = request.get('/api/v1/photos?view=organized&suspicious=true&filter_pins=suspicious').json()
    expect(choose('Has similar photos')).to_have_attribute('aria-pressed', 'false')
    expect(choose('Suspicious dates')).to_have_attribute('aria-pressed', 'true')
    expect(summary).to_have_text(f"Showing {suspicious_only['total']:,} of {total:,} photos")
    expect(choose('Suspicious dates').locator('.sidebar-count')).to_have_text(f"{suspicious_only['total']:,}")
    expect(choose('Has similar photos').locator('.sidebar-count')).to_have_text(f"{suspicious_only['chips']['similar']:,}")
    expect(page).not_to_have_url(re.compile(r'[?&]similar=1'))
    expect(page).to_have_url(re.compile(r'[?&]suspicious=1'))
    expect(page.locator('.card')).to_have_count(min(60, suspicious_only['total']))
    # One-filter gallery position stays stable when its pin turns it off.
    filtered_gallery_y = page.locator('.gallery-head').bounding_box()['y']
    unpin('Suspicious dates').click()
    for label in ('Has similar photos', 'Suspicious dates'):
        expect(choose(label)).to_have_attribute('aria-pressed', 'false')
        expect(pin(label)).to_have_attribute('aria-pressed', 'false')
    expect(choose('Suspicious dates').locator('.sidebar-count')).to_have_text(f"{whole['chips']['suspicious']:,}")
    expect(page.locator('.card')).to_have_count(min(60, total))
    expect(summary).to_have_count(0)
    expect(clear).not_to_be_visible()
    assert abs(page.locator('.gallery-head').bounding_box()['y'] - filtered_gallery_y) < 1
    assert abs(page.locator('.gallery-head').bounding_box()['y'] - baseline_gallery_y) < 1
    expect(library_count).to_have_text(f'{total:,}')
    page.reload()
    expect(page.locator('.card')).to_have_count(min(60, total))
    expect(summary).to_have_count(0)
    for label in ('Has similar photos', 'Suspicious dates'):
        expect(choose(label)).to_have_attribute('aria-pressed', 'false')
        expect(pin(label)).to_have_attribute('aria-pressed', 'false')
    # Capture-date filtering must not show a misleading file-timestamp year panel.
    page.goto(base + '/?view=organized&sort=newest')
    expect(page.locator('.scrubber')).to_be_visible()
    choose('No usable capture date').click()
    expect(page.locator('.scrubber')).to_have_count(0)
    expected_undated = request.get('/api/v1/photos?view=organized&undated=true').json()['total']
    expect(summary).to_have_text(f'Showing {expected_undated:,} of {total:,} photos')
    pin('No usable capture date').click()
    choose('Small images').click()
    expect(choose('No usable capture date')).to_have_attribute('aria-pressed', 'true')
    expect(page.locator('.scrubber')).to_have_count(0)
    page.reload()
    expect(choose('No usable capture date')).to_have_attribute('aria-pressed', 'true')
    expect(page.locator('.scrubber')).to_have_count(0)
    expect(summary).to_have_text(re.compile(r'^Showing [\d,]+ of [\d,]+ photos$'))
    expect(page.locator('.card').first).to_be_visible()
    if os.environ.get('SHOTS'): page.screenshot(path=f"{os.environ['SHOTS']}/no-capture-date.png")
    unpin('No usable capture date').click()
    expect(choose('Small images')).to_have_attribute('aria-pressed', 'true')
    expect(page.locator('.scrubber')).to_be_visible()
    clear.click()
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
    # Library-only filters pause at every source entry; both unpinned choices and
    # saved pins return on a sidebar Library/Needs review visit. Explicit URLs stay exact.
    for pinned in (False, True):
        choose('Review later').click()
        if pinned: pin('Review later').click()
        for source_entry in ('Not organized', 'Source folders', 'Needs attention'):
            main.get_by_role('link', name=re.compile('^' + source_entry + r'\b')).click()
            expect(choose('Review later')).to_have_attribute('aria-pressed', 'false')
            expect(choose('Review later')).to_have_attribute('aria-disabled', 'true')
            expect(main.get_by_role('button', name=('Unpin ' if pinned else 'Pin ') + 'Review later', exact=True)).to_have_attribute('aria-pressed', 'false')
            expect(page).not_to_have_url(re.compile(r'reason=later|similar=1'))
            if source_entry == 'Source folders':
                page.get_by_role('button', name='Still in source', exact=True).click()
                expected_source = request.get('/api/v1/photos?view=source').json()['total']
                expect(page.locator('.grid .card')).to_have_count(min(60, expected_source))
            page.reload()
            expect(choose('Review later')).to_have_attribute('aria-pressed', 'false')
            main.get_by_role('link', name=re.compile('^Library')).click()
            expect(choose('Review later')).to_have_attribute('aria-pressed', 'true')
            expect(page.locator('.grid .card')).to_have_count(1)
            if pinned: expect(unpin('Review later')).to_have_attribute('aria-pressed', 'true')
        clear.click()
    # Similarity is also suspended and restored, including the related sort.
    pin('Has similar photos').click()
    main.get_by_role('link', name='Source folders', exact=True).click()
    expect(choose('Has similar photos')).to_have_attribute('aria-pressed', 'false')
    expect(unpin('Has similar photos')).to_have_attribute('aria-pressed', 'false')
    main.get_by_role('link', name=re.compile('^Needs review')).click()
    expect(choose('Has similar photos')).to_have_attribute('aria-pressed', 'true')
    clear.click()
    main.get_by_role('link', name=re.compile('^Library')).click()
    pin('Small images').click()
    main.get_by_role('link', name=re.compile('^Not organized')).click()
    # Forgetting a saved pin at source must also cancel its remembered filter.
    unpin('Small images').click()
    main.get_by_role('link', name=re.compile('^Library')).click()
    expect(choose('Small images')).to_have_attribute('aria-pressed', 'false')
    choose('Small images').click()
    main.get_by_role('link', name='Source folders', exact=True).click()
    clear.click()
    main.get_by_role('link', name=re.compile('^Library')).click()
    expect(choose('Small images')).to_have_attribute('aria-pressed', 'false')
    # Source URLs cannot activate a destination-only reason, even on refresh.
    for source_view in ('unorganized', 'source'):
        page.goto(base + '/?view=' + source_view + '&reason=issues')
        expect(page).not_to_have_url(re.compile('reason=issues'))
        expect(choose('Files needing verification')).to_have_attribute('aria-pressed', 'false')
    # Shared search/date filters still apply on a normal Not organized navigation.
    page.goto(base + '/?view=organized&undated=1&q=photo')
    main.get_by_role('link', name=re.compile('^Not organized')).click()
    expect(page).to_have_url(re.compile('undated=1'))
    expect(page).to_have_url(re.compile('q=photo'))
    clear.click()
    # A cross-location search link promises the search results, not saved filters.
    main.get_by_role('link', name=re.compile('^Library')).click()
    pin('Review later').click()
    main.get_by_role('link', name=re.compile('^Not organized')).click()
    page.get_by_role('searchbox', name='Search filenames', exact=True).fill('photo')
    page.get_by_role('button', name=re.compile(r'matches in Library$')).click()
    expect(choose('Review later')).to_have_attribute('aria-pressed', 'false')
    expect(page.locator('.grid .card')).to_have_count(60)
    expect(page).to_have_url(re.compile('q=photo'))
    clear.click()
    # Clear all includes source folder restrictions, preserves the place, and clears search.
    page.goto(base + '/?view=unorganized&tree=1&folder=generated&q=missing')
    expect(clear).to_be_visible()
    assert abs(choose('Has similar photos').bounding_box()['y'] - initial_filter_y) < 1
    clear.click()
    expect(page).not_to_have_url(re.compile(r'folder=|q='))
    expect(page).to_have_url(re.compile('tree=1'))
    page.goto(base + '/?view=organized')
    # Source attention is always an available child link, counted even at zero.
    attention = main.get_by_role('link', name=re.compile('^Needs attention'))
    expect(attention.locator('.sidebar-count')).to_have_text('0')
    expect(main.get_by_role('button', name='Pin Needs attention', exact=True)).to_have_count(0)
    attention.click()
    expect(page).to_have_url(re.compile('view=unorganized&reason=attention'))
    expect(attention).to_have_attribute('aria-current', 'page')
    main.get_by_role('link', name=re.compile('^Not organized')).click()
    expect(attention).not_to_have_attribute('aria-current', 'page')
    # Old attention pins cannot silently hide source photos now that it is navigation.
    page.evaluate("localStorage.setItem('ns.filterPins', JSON.stringify(['attention']))")
    page.goto(base + '/?view=unorganized&tree=1&folder=trip%2Fday+1')
    tree = page.get_by_role('navigation', name='Source folders', exact=True)
    page.get_by_role('button', name='Still in source', exact=True).click()
    expect(page).to_have_url(re.compile('folder='))
    expect(page.locator('.grid .card')).to_have_count(10)
    page.get_by_role('button', name='Waiting', exact=True).click()
    expect(page).to_have_url(re.compile('folder='))
    expect(page).not_to_have_url(re.compile('reason=attention'))
    page.get_by_role('button', name='Still in source', exact=True).click()
    # The source scope controls must not cover the tree, including desktop reflow.
    for width in (1440, 720):
        page.set_viewport_size({'width': width, 'height': 1000})
        switch = page.locator('.source-tree > .segmented').bounding_box()
        folder_box = tree.bounding_box()
        assert folder_box['y'] >= switch['y'] + switch['height'], (switch, folder_box)
        if os.environ.get('SHOTS'): page.screenshot(path=f"{os.environ['SHOTS']}/source-navigation-{width}.png")
    page.set_viewport_size({'width': 1440, 'height': 1000})
    main.get_by_role('link', name=re.compile('^Library')).click()
    expect(page).not_to_have_url(re.compile('folder=|tree=|reason=attention'))
    expect(page.locator('.source-tree')).to_have_count(0)
    page.get_by_role('button', name='Filters', exact=True).click()
    expect(page.get_by_role('navigation', name='Dates', exact=True)).to_be_visible()
    expect(page.get_by_role('navigation', name='Folders', exact=True)).to_have_count(0)
    expect(page.get_by_role('button', name='Folders', exact=True)).to_have_count(0)
    page.get_by_role('button', name='Close filters', exact=True).click()
    # Explicit old destination links cannot leave an invisible source folder filter.
    page.goto(base + '/?view=organized&folder=does-not-exist')
    expect(page).not_to_have_url(re.compile('folder='))
    expect(page.locator('.card-image').first).to_be_visible()
    page.reload()
    expect(page).not_to_have_url(re.compile('folder='))
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
        expect(inspector.get_by_role('tab')).to_have_count(3)
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
    choose('No usable capture date').click()
    expect(choose('No usable capture date')).to_have_attribute('aria-pressed', 'true')
    expect(choose('Suspicious dates').locator('.sidebar-count')).to_have_text(f'{suspicious_count:,}')
    choose('Suspicious dates').click()
    expect(choose('No usable capture date')).to_have_attribute('aria-pressed', 'false')
    expect(choose('Suspicious dates')).to_have_attribute('aria-pressed', 'true')
    pin('Small images').click()
    choose('No usable capture date').click()
    expect(choose('Suspicious dates')).to_have_attribute('aria-pressed', 'false')
    expect(choose('Small images')).to_have_attribute('aria-pressed', 'true')
    expect(choose('No usable capture date')).to_have_attribute('aria-pressed', 'true')
    expect(selected).to_contain_text('1 photo selected')
    selected.get_by_role('button', name='Clear selection').click()
    page.reload()
    expect(unpin('Small images')).to_have_attribute('aria-pressed', 'true')
    expect(choose('Small images')).to_have_attribute('aria-pressed', 'true')
    main.get_by_role('link', name=re.compile('^Needs review')).click()
    expect(choose('Review later')).to_have_attribute('aria-disabled', 'true')
    expect(choose('Review later')).to_have_attribute('title', re.compile('Unpin Small images'))
    expect(choose('Review later').locator('.sidebar-count')).to_have_text('—')
    choose('Review later').focus()
    expect(page.get_by_role('note').filter(has_text='Unpin Small images')).to_be_visible()
    page.keyboard.press('Escape')
    unpin('Small images').click()
    expect(choose('Small images')).to_have_attribute('aria-pressed', 'false')
    expect(choose('Review later')).not_to_have_attribute('aria-disabled', 'true')
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
    # A saved pin not applied to this job link can be removed without losing its scope.
    unpin('Small images').click()
    expect(page).to_have_url(re.compile(r'[?&]run=' + str(copied) + r'(?:&|$)'))
    expect(choose('Small images')).to_have_attribute('aria-pressed', 'false')
    expect(pin('Small images')).to_have_attribute('aria-pressed', 'false')
    pin('Small images').click()
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
