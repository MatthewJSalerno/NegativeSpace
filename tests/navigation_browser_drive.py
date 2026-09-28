"""Same-page links and browser history synchronize mounted browsing state."""
import re
import sys
import time
from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    request = p.request.new_context(base_url=sys.argv[1])
    assert request.post('/api/v1/catalog').ok
    response = request.post('/api/v1/jobs/start', data={'mode': 'index'})
    assert response.status == 202
    run_id = response.json()['id']
    for _ in range(600):
        run = request.get(f'/api/v1/runs/{run_id}').json()
        if run['status'] not in ('Preparing', 'Running', 'Cancelling'):
            break
        time.sleep(.2)
    else:
        raise AssertionError('Index did not finish')
    page = browser.new_page(viewport={'width': 1400, 'height': 900})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(sys.argv[1] + '/logs?status=Failed&q=missing&from=2020-01-01')
    expect(page.get_by_role('checkbox', name=re.compile(r'^Failed '))).to_be_checked()
    page.locator('.finished-banner').get_by_role('link', name='View log', exact=True).click()
    expect(page.get_by_role('searchbox', name='Search the log')).to_have_value('')
    expect(page.get_by_role('checkbox', name=re.compile(r'^Indexed \(\d'))).to_be_checked()
    expect(page.locator('.log-table tbody tr').first).to_be_visible()
    page.go_back()
    expect(page.get_by_role('searchbox', name='Search the log')).to_have_value('missing')
    expect(page.get_by_role('checkbox', name=re.compile(r'^Indexed \(\d'))).not_to_be_checked()
    page.go_forward()
    expect(page.get_by_role('searchbox', name='Search the log')).to_have_value('')
    page.get_by_role('link', name='Library', exact=True).click()
    search = page.get_by_role('searchbox', name='Search filenames')
    search.fill('photo-010')
    expect(page.locator('.card')).to_have_count(1)
    page.locator('.card-image').first.click()
    expect(page.locator('.inspector')).to_be_visible()
    page.get_by_role('link', name='Library', exact=True).click()
    expect(search).to_have_value('')
    expect(page.locator('.inspector')).to_have_count(0)
    expect(page.locator('.card')).to_have_count(60)
    page.go_back()
    expect(search).to_have_value('photo-010')
    expect(page.locator('.card')).to_have_count(1)
    expect(page.locator('.inspector')).to_be_visible()
    page.go_forward()
    expect(search).to_have_value('')
    expect(page.locator('.card')).to_have_count(60)
    # Scroll into a later batch; an explicit Library link returns to page one.
    page.mouse.wheel(0, 20_000)
    expect(page.locator('.card')).to_have_count(120, timeout=10_000)
    page.locator('.card').nth(90).scroll_into_view_if_needed()
    expect(page).to_have_url(re.compile(r'page=2\b'))
    page.get_by_role('link', name='Library', exact=True).click()
    expect(page.locator('.pager').first.locator('button.current')).to_have_text('1')
    expect(page.locator('.card')).to_have_count(60)
    page.locator('.card-check input').nth(0).check()
    page.locator('.card-check input').nth(1).check()
    page.get_by_role('button', name='Show only selected', exact=True).click()
    expect(page.locator('.focus-head')).to_contain_text('2 selected photos')
    page.get_by_role('link', name='Library', exact=True).click()
    expect(page.locator('.focus-head')).to_have_count(0)
    expect(page.locator('.card-check input:checked')).to_have_count(2)
    page.get_by_role('button', name=re.compile(r'^Actions')).click()
    menu = page.get_by_role('menu', name='Actions')
    menu.get_by_role('menuitem', name='Copy', exact=True).click()
    menu.get_by_role('menuitem', name='Copy selected (2)').click()
    expect(page.get_by_role('region', name='Review before copying')).to_be_visible()
    page.get_by_role('link', name='Library', exact=True).click()
    expect(page.get_by_role('region', name='Review before copying')).to_have_count(0)
    expect(page.locator('.card-check input:checked')).to_have_count(2)
    assert not errors, errors
    browser.close()
print('Same-page Logs and Library links, Inspector and Back/Forward passed')
