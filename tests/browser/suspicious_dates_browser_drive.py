"""Recovery UI with generated files and an opt-in disposable catalog mount."""
import os
import re
import sqlite3
import sys
import time
from playwright.sync_api import sync_playwright, expect

with sync_playwright() as p:
    browser = p.chromium.launch()
    request = p.request.new_context(base_url=sys.argv[1])
    created = request.post('/api/v1/catalog')
    assert created.ok, created.text()
    def wait(run):
        for _ in range(600):
            result = request.get(f'/api/v1/runs/{run}').json()
            if (result['status'] not in ('Preparing','Running','Cancelling')
                    and request.get('/api/v1/jobs/active').json()['active'] is None):
                assert result['status'] == 'Completed', result
                return
            time.sleep(.2)
        raise AssertionError('Job did not finish')
    for mode in ('index','copy'):
        response = request.post('/api/v1/jobs/start',data={'mode':mode})
        assert response.ok, response.text()
        wait(response.json()['id'])
    with sqlite3.connect('/catalog/db/ns_sqlite.db') as conn:
        ids = [r[0] for r in conn.execute("SELECT id FROM photos WHERE status='Copied' ORDER BY id LIMIT 2")]
        for photo,year,source in zip(ids,('0001','2218'),('exif','file_mtime')):
            conn.execute("UPDATE photos SET metadata_json=json_set(metadata_json,'$.date_taken',?,'$.date_source',?) WHERE id=?",(year+'-01-01 12:00:00',source,photo))
    page = browser.new_page(viewport={'width':1440,'height':1000})
    errors=[]
    page.on('pageerror',lambda e: errors.append(str(e)))
    page.goto(sys.argv[1])
    page.get_by_role('button',name=re.compile('^Suspicious dates')).click()
    expect(page.locator('.card')).to_have_count(2)
    expect(page).to_have_url(re.compile('view=suspicious'))
    page.reload()
    expect(page.locator('.card')).to_have_count(2)
    page.locator(f'.card[data-id="{ids[0]}"] .card-image').click()
    expect(page.get_by_text('Suspicious date:',exact=False)).to_be_visible()
    expect(page.get_by_text('Source: photo EXIF',exact=False)).to_be_visible()
    if os.environ.get('SHOTS'):
        page.screenshot(path=os.path.join(os.environ['SHOTS'],'suspicious-date-inspector.png'))
    page.get_by_role('tab',name='Similar photos',exact=True).click()
    page.get_by_role('button',name=re.compile('^Review side by side:')).first.click()
    expect(page.get_by_role('table',name='Capture information',exact=True).get_by_role('rowheader',name=re.compile('^Date review'))).to_be_visible()
    expect(page.get_by_text('Recorded year is before 1800.',exact=True)).to_be_visible()
    page.get_by_role('table',name='Capture information',exact=True).get_by_role('rowheader',name=re.compile('^Date review')).scroll_into_view_if_needed()
    if os.environ.get('SHOTS'):
        page.screenshot(path=os.path.join(os.environ['SHOTS'],'suspicious-date-comparison.png'))
    page.get_by_role('button',name='Back to gallery',exact=True).click()
    page.goto(sys.argv[1]+'/?view=suspicious')
    page.set_viewport_size({'width':700,'height':844})
    expect(page.locator('.card')).to_have_count(2)
    assert page.locator('body').evaluate('e => e.scrollWidth <= innerWidth'), 'narrow overflow'
    if os.environ.get('SHOTS'):
        page.screenshot(path=os.path.join(os.environ['SHOTS'],'suspicious-dates-narrow.png'))
    assert not errors,errors
    browser.close()
print('Suspicious date browser checks passed')
