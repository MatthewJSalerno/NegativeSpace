"""Real backup outcomes in the shared status area, with generated storage failures."""
import json
import os
import re
from pathlib import Path
import sys
import time
from playwright.sync_api import sync_playwright, expect

base = sys.argv[1]
control = Path('/catalog/backup-test.json')
def configure(**values):
    control.write_text(json.dumps(values))

with sync_playwright() as p:
    request = p.request.new_context(base_url=base)
    assert request.post('/api/v1/catalog').ok
    Path('/src/photo-000.jpg').rename('/src/backup-check.jpg')
    def state():
        return request.get('/api/v1/jobs/active').json()
    def wait(predicate):
        for _ in range(600):
            current = state()
            if predicate(current):
                return current
            time.sleep(.1)
        raise AssertionError(current)
    def start(mode):
        response = request.post('/api/v1/jobs/start', data={'mode': mode})
        assert response.ok, response.text()
        return response.json()['id']
    browser = p.chromium.launch()
    page = browser.new_page(viewport={'width':1440,'height':900}, color_scheme='dark')
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    def shot(name):
        if os.environ.get('SHOTS'):
            page.screenshot(path=f"{os.environ['SHOTS']}/{name}.png")

    configure(hold=True)
    index = start('index')
    current = wait(lambda s: s['active'] and s['active'].get('backup_stage') == 'post_job')
    assert current['active']['status'] == 'Completed'
    try:
        for path in ('/', '/logs', '/stats'):
            page.goto(base + path)
            expect(page.locator('.drawer-backup')).to_contain_text('Index finished')
            expect(page.locator('.drawer-backup')).to_contain_text('Backing up catalog')
            expect(page.locator('.backup-notice')).to_have_count(0)
        page.goto(base)
        expect(page.locator('.card-check input').first).to_be_disabled()
        page.get_by_role('button', name='Jobs', exact=True).click()
        expect(page.get_by_role('menuitem', name=re.compile(r'^Index\b'))).to_have_attribute('aria-disabled', 'true')
        page.keyboard.press('Escape')
        assert request.post('/api/v1/jobs/start', data={'mode':'copy'}).status == 409
        assert request.post('/api/v1/backups').status == 409
        assert request.post(f'/api/v1/jobs/{index}/cancel').status == 409
        shot('backup-progress-dark')
    finally:
        configure()
    wait(lambda s: s['active'] is None and s['backup']['unbacked_count'] == 0)
    expect(page.locator('.drawer-backup')).to_have_count(0)
    expect(page.locator('.card-check input').first).to_be_enabled()
    assert state()['last']['id'] == index, 'Refused work started automatically'

    configure(failure='insufficient_space')
    copied = start('copy')
    current = wait(lambda s: s['active'] is None and s['last']['id'] == copied)
    assert current['last']['outcome']['succeeded'] > 0
    saved_outcome = current['last']['outcome']
    for path in ('/', '/logs', '/stats'):
        page.goto(base + path)
        notice = page.locator('.backup-notice')
        expect(notice).to_contain_text('backup storage is full')
        expect(notice.get_by_role('button', name='Retry backup')).to_be_enabled()
    page.reload()
    expect(page.locator('.backup-notice')).to_contain_text('Catalog backup failed')
    shot('backup-failure-dark')
    page.evaluate("document.documentElement.style.fontSize='200%'")
    page.locator('.backup-notice summary').click()
    for width in (1440, 720, 390):
        page.set_viewport_size({'width':width, 'height':900})
        expect(page.locator('.backup-notice').get_by_role('button', name='Retry backup')).to_be_visible()
        assert page.locator('.backup-notice').evaluate('(e) => e.scrollWidth <= e.clientWidth + 1')
    shot('backup-failure-text-200')
    page.evaluate("document.documentElement.style.fontSize=''")
    page.locator('.backup-notice summary').click()
    page.set_viewport_size({'width':1440, 'height':900})
    # An unsuccessful retry stays visible, retaining the actual Copy outcome.
    previous_attempt = state()['backup']['latest']['attempt_id']
    page.locator('.backup-notice').get_by_role('button', name='Retry backup').click()
    wait(lambda s: s['active'] is None and s['backup']['latest']['attempt_id'] > previous_attempt)
    expect(page.locator('.backup-notice')).to_contain_text('backup storage is full')
    assert state()['last']['outcome'] == saved_outcome
    configure(hold=True)
    page.locator('.backup-notice').get_by_role('button', name='Retry backup').click()
    expect(page.locator('.drawer-backup')).to_contain_text('Backing up catalog')
    try:
        wait(lambda s: s['active'] and s['active'].get('backup_stage') == 'manual')
        assert request.post('/api/v1/jobs/start', data={'mode':'index'}).status == 409
        page.goto(base + '/?view=organized')
        expect(page.locator('.drawer-backup')).to_be_visible()
        expect(page.locator('.card').first).to_be_visible()
        page.goto(base + '/stats')
        expect(page.locator('.drawer-backup')).to_be_visible()
    finally:
        configure()
    wait(lambda s: s['active'] is None and s['backup']['latest']['outcome'] == 'succeeded')
    expect(page.locator('.backup-notice')).to_have_count(0)
    expect(page.locator('.drawer-backup')).to_have_count(0)
    expect(page.locator('.stat-tiles')).to_contain_text('Up to date')
    assert state()['last']['outcome'] == saved_outcome

    # Interrupted snapshots are not retried on page load and do not alter Copy.
    configure(interrupt=True)
    assert request.post('/api/v1/backups').ok
    current = wait(lambda s: s['active'] is None)
    attempt = current['backup']['latest']['attempt_id']
    page.reload()
    expect(page.locator('.backup-notice')).to_contain_text('Catalog backup did not finish')
    assert state()['backup']['latest']['attempt_id'] == attempt
    configure()
    page.locator('.backup-notice').get_by_role('button', name='Retry backup').click()
    expect(page.locator('.backup-notice')).to_have_count(0)
    wait(lambda s: s['active'] is None and s['backup']['latest']['outcome'] == 'succeeded')
    assert state()['last']['id'] == copied
    assert not errors, errors
    browser.close()
print('Backup status: busy through snapshot, no queue, page navigation, failure/retry and interruption passed.')
