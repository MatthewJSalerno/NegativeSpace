"""First-run year choice and immediate date-policy updates in the rendered app."""
import os
import re
import sys
import time
from playwright.sync_api import sync_playwright, expect

with sync_playwright() as p:
    browser=p.chromium.launch()
    request=p.request.new_context(base_url=sys.argv[1])
    assert request.post('/api/v1/catalog').ok
    page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[]
    page.on('pageerror',lambda e: errors.append(str(e)))
    page.goto(sys.argv[1])
    page.get_by_label('Color mode',exact=True).select_option('dark')
    expect(page.locator('html')).to_have_attribute('data-theme','dark')
    page.get_by_role('button',name='Next',exact=True).click()
    year=page.get_by_label('Earliest expected year',exact=True)
    expect(year).to_have_value('1800')
    year.fill('2020')
    page.get_by_label('Small-image reminders',exact=False).select_option('off')
    for _ in range(2): page.get_by_role('button',name='Next',exact=True).click()
    page.get_by_role('button',name='Save and continue',exact=True).click()
    expect(page.get_by_role('button',name='Settings',exact=True)).to_be_visible()
    assert request.get('/api/v1/settings').json()['suspicious_min_year']['value']==2020
    def wait(run):
        for _ in range(600):
            status=request.get(f'/api/v1/runs/{run}').json()
            if status['status'] not in ('Preparing','Running','Cancelling') and request.get('/api/v1/status').json()['active_job'] is None:
                assert status['status']=='Completed',status
                return
            time.sleep(.2)
        raise AssertionError('Job timed out')
    for mode in ('index','copy'):
        response=request.post('/api/v1/jobs/start',data={'mode':mode})
        assert response.ok,response.text()
        wait(response.json()['id'])
    page.goto(sys.argv[1]+'/?view=organized&suspicious=1')
    expect(page.locator('.card')).to_have_count(60)
    expect(page.locator('.gallery-guidance > div:not([aria-hidden=true])')).to_contain_text('2020')
    page.locator('.card .card-image').first.click()
    expect(page.get_by_text('Recorded year is before your earliest expected year (2020).',exact=False).first).to_be_visible()
    page.get_by_role('button',name='Settings',exact=True).click()
    page.get_by_role('tab',name='Files').click()
    year.fill('10000')
    page.get_by_role('button',name='Save settings',exact=True).click()
    expect(page.get_by_text('Enter a whole year from 1 to 9999.',exact=True)).to_be_visible()
    year.fill('1800')
    page.get_by_role('button',name='Save settings',exact=True).click()
    expect(page.get_by_text('Saved.',exact=True)).to_be_visible()
    page.get_by_role('button',name='Close settings').click()
    expect(page.locator('.card')).to_have_count(0)
    expect(page.locator('.gallery-guidance > div:not([aria-hidden=true])')).to_contain_text('1800')
    expect(page.get_by_text('Recorded year is before your earliest expected year (2020).',exact=False)).to_have_count(0)
    page.get_by_role('button',name='Settings',exact=True).click()
    page.get_by_role('tab',name='Files').click()
    year.fill('2020')
    page.get_by_role('button',name='Save settings',exact=True).click()
    expect(page.get_by_text('Saved.',exact=True)).to_be_visible()
    year.scroll_into_view_if_needed()
    if os.environ.get('SHOTS'): page.screenshot(path=os.path.join(os.environ['SHOTS'],'date-settings-dark.png'))
    page.set_viewport_size({'width':800,'height':700})
    year.scroll_into_view_if_needed()
    assert page.locator('.modal-shell > .settings').evaluate('e => e.scrollWidth <= e.clientWidth+1')
    if os.environ.get('SHOTS'): page.screenshot(path=os.path.join(os.environ['SHOTS'],'date-settings-reflow.png'))
    page.get_by_role('button',name='Close settings').click()
    expect(page.get_by_role('dialog',name='Photo details',exact=True)).to_be_visible()
    page.get_by_role('dialog',name='Photo details',exact=True).get_by_role('button',name='Close',exact=True).click()
    expect(page.locator('.card')).to_have_count(60)
    page.reload()
    expect(page.locator('.card')).to_have_count(60)
    expect(page.get_by_role('button',name='Dark mode',exact=True)).to_have_attribute('aria-pressed','true')
    assert not errors,errors
    browser.close()
print('First-run year choice, validation, persistence, filter counts and inspector refresh passed')
