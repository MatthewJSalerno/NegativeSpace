"""Large-selection navigation through the real web proxy, using generated fixtures.

Run with the browser harness's SIMILARITY_RECOVERY_FIXTURE=1 catalog mount.
Extra catalog rows reuse one generated photo's bytes; this tests navigation,
not indexing or duplicate classification.
"""
import os
from pathlib import Path
import re
import sqlite3
import sys
import time

from playwright.sync_api import expect, sync_playwright


with sync_playwright() as p:
    browser = p.chromium.launch()
    request = p.request.new_context(base_url=sys.argv[1])
    assert request.post('/api/v1/catalog').ok
    started = request.post('/api/v1/jobs/start', data={'mode': 'index'})
    assert started.ok, started.text()
    for _ in range(600):
        run = request.get(f'/api/v1/runs/{started.json()["id"]}').json()
        if run['status'] not in ('Preparing', 'Running', 'Cancelling'):
            assert run['status'] == 'Completed', run
            break
        time.sleep(.2)
    else:
        raise AssertionError('Index did not finish')

    with sqlite3.connect('/catalog/db/ns_sqlite.db') as conn:
        conn.row_factory = sqlite3.Row
        template = dict(conn.execute("SELECT * FROM photos WHERE status='Pending' LIMIT 1").fetchone())
        template.pop('id')
        source = Path('/src') / Path(template['source_path']).relative_to('/data/source')
        for i in range(1100):
            name = f'selection-{i:04d}.jpg'
            os.link(source, Path('/src') / name)
            row = {**template, 'source_path': f'/data/source/{name}'}
            conn.execute(f'INSERT INTO photos({",".join(row)}) VALUES({",".join("?" for _ in row)})',
                         list(row.values()))

    selected = request.get('/api/v1/photos/ids').json()['ids']
    assert len(selected) > 1000
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors = []
    positions = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('response', lambda response: positions.append(response)
            if response.url.endswith('/api/v1/photos/position') else None)
    page.goto(sys.argv[1] + '/?sort=name')
    page.get_by_role('button', name=re.compile(r'^Select')).first.click()
    page.get_by_role('menu', name='Select').get_by_role('menuitem').filter(
        has=page.locator('.menu-label').get_by_text(f'Select all in this view ({len(selected):,})', exact=True)).click()
    line = page.locator('.selection-line')
    line.get_by_role('button', name='Show only selected').click()
    expect(page.locator('.focus-head')).to_contain_text('Showing only')
    inspector = page.locator('.inspector')
    pager = page.locator('.pager').first

    # Cross a page boundary near the start, then another beyond the old limit.
    for number in (1, 17):
        before = request.post('/api/v1/photos/selection', data={
            'ids': selected, 'sort': 'name', 'page': number, 'page_size': 60}).json()['items'][-1]
        after = request.post('/api/v1/photos/selection', data={
            'ids': selected, 'sort': 'name', 'page': number + 1, 'page_size': 60}).json()['items'][0]
        pager.get_by_label('Go to page').fill(str(number))
        pager.get_by_role('button', name='Go', exact=True).click()
        page.locator(f'.card[data-id="{before["id"]}"] .card-image').click()
        expect(inspector.locator('h2')).to_have_text(before['filename'])
        inspector.get_by_role('button', name='Next photo', exact=True).click()
        expect(inspector.locator('h2')).to_have_text(after['filename'])
        expect(page.locator(f'.card[data-id="{after["id"]}"].open')).to_be_visible()
        inspector.get_by_role('button', name='Previous photo', exact=True).click()
        expect(inspector.locator('h2')).to_have_text(before['filename'])
        inspector.get_by_role('button', name='Close', exact=True).click()
    # Already-loaded neighbors can be reached locally; require a real server
    # lookup with the whole selection, without imposing one request per click.
    assert positions and all(response.ok for response in positions), [r.status for r in positions]
    assert all(len(response.request.post_data_json['ids']) == len(selected) for response in positions)
    assert not errors, errors
    browser.close()
    print(f'Large selection: {len(selected)} photos; Show only selected and Inspector page-boundary navigation passed.')
