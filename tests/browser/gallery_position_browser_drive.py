"""Explicit photo navigation locates cards without taking over manual browsing."""
import re
import sys
import time
from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    request = p.request.new_context(base_url=sys.argv[1])
    assert request.post('/api/v1/catalog').ok
    run = request.post('/api/v1/jobs/start', data={'mode': 'index'}).json()['id']
    for _ in range(600):
        if (request.get(f'/api/v1/runs/{run}').json()['status'] not in ('Preparing', 'Running', 'Cancelling')
                and request.get('/api/v1/jobs/active').json()['active'] is None):
            break
        time.sleep(.2)
    else:
        raise AssertionError('Index timed out')
    items = request.get('/api/v1/photos?page_size=240').json()['items']
    target = items[125]['id']
    page = browser.new_page(viewport={'width': 1600, 'height': 1000})
    errors, fetched = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('request', lambda r: fetched.append(r.url) if '/api/v1/photos?' in r.url else None)
    page.add_init_script('''window.nsScrolls = []; const scroll = window.scrollTo;
        window.scrollTo = function(...args) { window.nsScrolls.push(args); return scroll.apply(window,args); };''')

    def visible_card(photo):
        card = page.locator(f'.card[data-id="{photo}"]')
        expect(card).to_have_class(re.compile(r'\bopen\b'))
        page.wait_for_function('''id => {
            const card = document.querySelector(`.card[data-id="${id}"]`);
            if (!card) return false;
            const box = card.getBoundingClientRect();
            const header = document.querySelector('header');
            return box.top >= Math.max(0, header.getBoundingClientRect().bottom) && box.bottom <= innerHeight;
        }''', arg=photo)
        return card

    # A real Logs link to a distant photo loads its page directly.
    page.goto(f'{sys.argv[1]}/logs?photo={target}')
    page.get_by_role('link', name='Open the photo', exact=True).click()
    visible_card(target)
    pages = [int(re.search(r'[?&]page=(\d+)', u)[1]) for u in fetched]
    assert 3 in pages and (2 not in pages or pages.index(3) < pages.index(2)), pages
    page.get_by_role('button', name='Next photo', exact=True).click()
    visible_card(items[126]['id'])
    page.get_by_role('button', name='Previous photo', exact=True).click()
    visible_card(target)
    # Both history actions have matching type and aligned text containers.
    links = page.locator('.history-links')
    expect(links).to_be_visible()
    styles = links.evaluate('el => [...el.children].map(c => ({font:getComputedStyle(c).fontSize, height:c.getBoundingClientRect().height, top:c.getBoundingClientRect().top}))')
    assert styles[0]['font'] == styles[1]['font']
    assert abs(styles[0]['top']-styles[1]['top']) < 1 and abs(styles[0]['height']-styles[1]['height']) < 1

    # An Inspector -> Logs -> photo round trip preserves the tab's Library filters.
    page.get_by_role('searchbox', name='Search filenames').fill('photo-010')
    expect(page.locator('.card')).to_have_count(1)
    page.get_by_role('link', name='Open in the log', exact=True).click()
    page.get_by_role('link', name='Open the photo', exact=True).click()
    expect(page.get_by_role('searchbox', name='Search filenames')).to_have_value('photo-010')
    expect(page.get_by_role('button', name='Show in gallery', exact=True)).to_be_visible()

    # A failed location lookup is retryable, without losing the Inspector.
    page.route('**/api/v1/photos/position', lambda route: route.fulfill(status=503, content_type='application/json', body='{}'))
    page.goto(f'{sys.argv[1]}/?photo={target}')
    expect(page.get_by_role('button', name='Retry locating photo')).to_be_visible()
    page.unroute('**/api/v1/photos/position')
    page.get_by_role('button', name='Retry locating photo').click()
    visible_card(target)
    expect(page.get_by_role('button', name='Retry locating photo')).to_have_count(0)

    # Inspector navigation crosses a page boundary in both directions.
    page.goto(f'{sys.argv[1]}/?photo={items[119]["id"]}')
    visible_card(items[119]['id'])
    page.get_by_role('button', name='Next photo', exact=True).click()
    visible_card(items[120]['id'])
    page.get_by_role('button', name='Previous photo', exact=True).click()
    visible_card(items[119]['id'])

    # A late location response must not reopen an Inspector the user closed.
    held = []
    page.route('**/api/v1/photos/position', lambda route: held.append(route))
    page.goto(f'{sys.argv[1]}/?photo={target}')
    expect(page.locator('.inspector')).to_be_visible()
    page.wait_for_timeout(100)
    assert held
    page.locator('.inspector').get_by_role('button', name='Close', exact=True).click()
    for route in held:
        route.fulfill(status=200, content_type='application/json', body='{"position":125,"page":3,"previous_id":1,"next_id":2}')
    page.unroute('**/api/v1/photos/position')
    page.wait_for_timeout(200)
    expect(page.locator('.inspector')).to_have_count(0)

    # A hidden photo offers an explicit, temporary view without clearing search.
    page.goto(f'{sys.argv[1]}/?q=photo-010&photo={target}')
    expect(page.get_by_role('button', name='Show in gallery', exact=True)).to_be_visible()
    expect(page.get_by_role('searchbox', name='Search filenames')).to_have_value('photo-010')
    page.get_by_role('button', name='Show in gallery', exact=True).click()
    visible_card(target)
    expect(page.locator('.focus-head')).to_contain_text('Showing the inspected photo')
    page.locator('.focus-head').get_by_role('button', name='Back to results', exact=True).click()
    expect(page.locator('.card')).to_have_count(1)
    expect(page.get_by_role('searchbox', name='Search filenames')).to_have_value('photo-010')

    # Clicking a visible card does not issue a programmatic scroll.
    page.goto(sys.argv[1])
    expect(page.locator('.card').first).to_be_visible()
    page.wait_for_timeout(300)
    before = page.evaluate('nsScrolls.length')
    page.locator('.card-image').first.click()
    expect(page.locator('.inspector')).to_be_visible()
    page.wait_for_timeout(300)
    assert page.evaluate('nsScrolls.length') == before
    page.mouse.wheel(0, 300)
    page.wait_for_timeout(400)
    after = page.evaluate('nsScrolls.length')
    page.wait_for_timeout(400)
    assert page.evaluate('nsScrolls.length') == after, 'Inspector fought manual scroll'
    assert not errors, errors
    browser.close()
print('Gallery positioning, hidden-photo action, manual scroll and History alignment passed')
