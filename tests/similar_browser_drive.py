"""Read-only similarity review against generated photos and the real Index."""
import os
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
        outcome = request.get(f'/api/v1/runs/{run}').json()
        if outcome['status'] not in ('Preparing', 'Running', 'Cancelling'):
            break
        time.sleep(.2)
    assert outcome['status'] == 'Completed', outcome
    queue = request.get('/api/v1/similar').json()
    assert queue['total'] > 60 and queue['state']['pending'] == 0, queue
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(sys.argv[1])
    page.get_by_role('link', name='Similar', exact=True).click()
    queue_region = page.get_by_role('region', name='Matching photos', exact=True)
    expect(queue_region.locator('.match-card')).to_have_count(30)
    queue_region.get_by_role('button', name='Next page', exact=True).click()
    expect(page).to_have_url(re.compile(r'page=2'))
    expect(queue_region.locator('.match-card')).to_have_count(30)
    queue_region.get_by_role('button', name=re.compile('^Compare ')).first.click()
    comparison = page.get_by_role('region', name='Photo comparison', exact=True)
    expect(comparison).to_be_visible()
    expect(comparison.get_by_text('Largest dimensions', exact=True).first).to_be_visible()
    comparison.get_by_role('button', name='Review side by side', exact=True).first.click()
    dialog = page.get_by_role('dialog', name='Review photo match', exact=True)
    expect(dialog).to_be_visible()
    expect(dialog.get_by_text('Different bytes (different SHA-1).', exact=False)).to_be_visible()
    dialog.get_by_role('slider', name='Zoom both previews', exact=True).fill('2')
    dialog.get_by_role('slider', name='Horizontal position', exact=True).fill('75')
    transforms = dialog.locator('.review-zoom').evaluate_all('els => els.map(e => ({transform:e.style.transform, origin:e.style.transformOrigin}))')
    assert len(transforms) == 2 and transforms[0] == transforms[1] and transforms[0]['transform'] == 'scale(2)', transforms
    dialog.get_by_role('button', name='Unrelated', exact=True).click()
    expect(dialog.get_by_role('status')).to_contain_text('Saved: Unrelated')
    if os.environ.get('SHOTS'):
        dialog.screenshot(path=os.path.join(os.environ['SHOTS'], 'match-review-desktop.png'))
    dialog.get_by_role('button', name='Close review', exact=True).click()
    page.reload()
    comparison.get_by_role('button', name='Review side by side', exact=True).first.click()
    expect(dialog.get_by_role('button', name='Unrelated', exact=True)).to_have_attribute('aria-pressed', 'true')
    page.set_viewport_size({'width':390,'height':844})
    assert dialog.evaluate('e => e.scrollWidth <= e.clientWidth + 1'), 'review overflow'
    if os.environ.get('SHOTS'):
        page.screenshot(path=os.path.join(os.environ['SHOTS'], 'match-review-mobile.png'))
    page.set_viewport_size({'width':1440,'height':1000})
    dialog.get_by_role('button', name='Close review', exact=True).click()
    page.get_by_text('Validation and performance', exact=True).click()
    diagnostics = page.get_by_role('region', name='Matching diagnostics', exact=True)
    expect(diagnostics.get_by_text('Unrelated judgments', exact=True).locator('+ dd')).to_have_text('1')
    expect(diagnostics.get_by_text('Last comparison phase, reported elapsed', exact=True).locator('+ dd')).to_contain_text('job')
    page.get_by_text('Validation and performance', exact=True).click()
    page.get_by_role('slider', name='Minimum visual match').fill('100')
    expect(page.get_by_role('slider')).to_have_value('100')
    expect(comparison).to_be_visible()
    url = page.url
    page.reload()
    expect(comparison).to_be_visible()
    assert page.url == url
    comparison.get_by_role('link', name='Photo details and history', exact=True).first.click()
    expect(page.get_by_role('link', name='Find similar photos', exact=True)).to_be_visible()
    page.go_back()
    expect(comparison).to_be_visible()
    expect(page.get_by_role('slider')).to_have_value('100')
    page.get_by_role('button', name='Close comparison', exact=True).click()
    expect(comparison).to_have_count(0)
    # Old exact-mode bookmarks now open visual review too; the page has one purpose.
    page.goto(f'{sys.argv[1]}/similar?mode=exact&threshold=100')
    expect(page.get_by_label('Match mode', exact=True)).to_have_count(0)
    expect(page.get_by_role('heading', name='Photos with visual matches', exact=True)).to_be_visible()
    expect(page.get_by_role('slider')).to_have_value('100')
    expect(queue_region.locator('.match-card')).to_have_count(30)
    filename = queue_region.locator('.match-caption strong').first.inner_text()
    page.get_by_role('searchbox', name='Search filenames').fill(filename)
    expect(queue_region.locator('.match-card')).to_have_count(1)
    page.get_by_role('button', name='Refresh', exact=True).click()
    expect(queue_region.locator('.match-card')).to_have_count(1)
    page.get_by_role('searchbox', name='Search filenames').fill('')
    expect(queue_region.locator('.match-card')).to_have_count(30)
    page.evaluate('window.scrollTo(0, 400)')
    page.wait_for_function("sessionStorage.getItem('similar-scroll:' + location.search) === '400'")
    page.reload()
    expect(queue_region.locator('.match-card')).to_have_count(30)
    page.wait_for_function('Math.abs(window.scrollY - 400) < 2')
    page.get_by_role('link', name='Library', exact=True).click()
    page.go_back()
    expect(queue_region.locator('.match-card')).to_have_count(30)
    page.wait_for_function('Math.abs(window.scrollY - 400) < 2')
    page.route('**/api/v1/similar?*', lambda route: route.fulfill(status=503, content_type='application/json', body='{}'))
    page.get_by_role('button', name='Refresh', exact=True).click()
    expect(page.get_by_role('alert')).to_be_visible()
    page.unroute('**/api/v1/similar?*')
    page.get_by_role('button', name='Retry', exact=True).click()
    expect(queue_region.locator('.match-card')).to_have_count(30)
    page.set_viewport_size({'width': 390, 'height': 844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'mobile overflow'
    if os.environ.get('SHOTS'):
        page.screenshot(path=os.path.join(os.environ['SHOTS'], 'similar-mobile.png'))
    page.set_viewport_size({'width': 1440, 'height': 1000})
    if os.environ.get('SHOTS'):
        page.screenshot(path=os.path.join(os.environ['SHOTS'], 'similar-desktop.png'))
    assert not errors, errors
    browser.close()
    print('Similarity browser checks passed')
