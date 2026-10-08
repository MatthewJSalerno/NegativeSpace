"""Completed jobs refresh open details and retry only failed grid images."""
import sys
import time
from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    req = p.request.new_context(base_url=sys.argv[1])
    assert req.post('/api/v1/catalog').ok

    def job(**body):
        response = req.post('/api/v1/jobs/start', data=body)
        assert response.status == 202
        run = response.json()['id']
        for _ in range(600):
            if (req.get(f'/api/v1/runs/{run}').json()['status'] not in ('Preparing', 'Running', 'Cancelling')
                    and req.get('/api/v1/jobs/active').json()['active'] is None):
                return run
            time.sleep(.2)
        raise AssertionError('Job timeout')

    job(mode='index')
    ids = [item['id'] for item in req.get('/api/v1/photos').json()['items'][:3]]
    page = browser.new_page(viewport={'width':1400, 'height':900})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    missing = f'**/api/v1/photos/{ids[0]}/thumbnail'
    permanent = f'**/api/v1/photos/{ids[1]}/thumbnail'
    attempts = []

    def fail(route):
        attempts.append(route.request.url)
        route.fulfill(status=404, json={'availability':'pending'})

    page.route(missing, fail)
    page.route(permanent, fail)
    page.goto(sys.argv[1])
    card = page.locator(f'.card[data-id="{ids[0]}"]')
    stuck = page.locator(f'.card[data-id="{ids[1]}"]')
    healthy = page.locator(f'.card[data-id="{ids[2]}"] img')
    expect(card).to_contain_text('Preview not made yet')
    expect(stuck).to_contain_text('Preview not made yet')
    expect(healthy).to_be_visible()
    healthy.evaluate('(img) => {window.healthyImage = img; window.healthyLoads = 0; img.addEventListener("load", () => window.healthyLoads++);} ')
    card.locator('.card-check input').check()
    card.locator('.card-image').click()
    panel = page.locator('.inspector')
    expect(panel).to_contain_text('Not written yet.')
    expect(panel.locator('.inspector-image img:not([style*="none"])')).to_be_visible()
    page.unroute(missing)
    scroll_before = page.evaluate('window.scrollY')
    run = job(mode='copy', file_ids=[ids[0]])
    expect(page.locator('.finished-banner a').first).to_have_attribute('href', f'/logs?run={run}', timeout=15000)
    expect(panel).not_to_contain_text('Not written yet.')
    expect(panel.locator('.photo-history')).to_contain_text('Copied')
    expect(card.locator('img')).to_be_visible()
    expect(card.locator('.card-check input')).to_be_checked()
    expect(stuck).to_contain_text('Preview not made yet')
    count = len(attempts)
    page.wait_for_timeout(2000)
    assert len(attempts) == count, 'Persistent failure is retrying without another job'
    assert healthy.evaluate('(img) => img === window.healthyImage && window.healthyLoads === 0')
    assert abs(page.evaluate('window.scrollY') - scroll_before) < 3
    run = job(mode='move', file_ids=[ids[0]])
    banner = page.locator('.finished-banner')
    expect(banner).to_contain_text('copied only', timeout=15000)
    detail = banner.locator('.tip > span').first
    assert detail.evaluate('(el) => getComputedStyle(el).textDecorationLine') == 'none'
    help_button = banner.get_by_role('button', name='More information')
    help_button.click()
    expect(banner.get_by_role('note')).to_be_visible()
    expect(panel.locator('.photo-history')).to_contain_text('Copied only')
    assert not errors, errors
    browser.close()
print('Inspector metadata/history refresh, bounded thumbnail retry, healthy-image preservation and reason help passed')
