"""Recorded lineage in the real window: grouping, links, scrolling and keyboard access.
Generated source files only. PREPARE_ONLY builds the same histories for manual review.
"""
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
from playwright.sync_api import expect, sync_playwright

BASE = sys.argv[1]
SRC = Path('/src')
errors = []


def job(request, mode, **extra):
    response = request.post('/api/v1/jobs/start', data={'mode': mode, **extra})
    assert response.ok, response.text()
    run_id = response.json()['id']
    for _ in range(1200):
        run = request.get(f'/api/v1/runs/{run_id}').json()
        if run['status'] not in ('Preparing', 'Running', 'Cancelling') and request.get('/api/v1/jobs/active').json()['active'] is None:
            assert run['status'] == 'Completed', run
            return run_id
        time.sleep(.1)
    raise AssertionError(f'{mode} did not settle')


with sync_playwright() as p:
    request = p.request.new_context(base_url=BASE)
    names = ['lineage-simple.jpg', 'lineage-one-index.jpg', 'lineage-later.jpg', 'lineage-long.jpg']
    for i, name in enumerate(names, 5):
        (SRC / f'photo-{i:03d}.jpg').rename(SRC / name)
    for i in range(1, 5):
        shutil.copyfile(SRC / names[1], SRC / f'lineage-one-index-copy-{i}.jpg')
    assert request.post('/api/v1/catalog').ok
    first_index = job(request, 'index')
    job(request, 'copy')
    def photo(name):
        rows = request.get('/api/v1/photos', params={'view': 'organized', 'q': name}).json()['items']
        assert len(rows) == 1, (name, rows)
        return rows[0]['id']
    ids = {name: photo(name) for name in names}
    def lineage(name):
        return request.get(f'/api/v1/photos/{ids[name]}/lineage').json()
    simple_before = lineage(names[0])
    # New archives arrive in separate scans. No implicit copying is done by Index.
    for i in range(1, 6):
        folder = SRC / f'arrival-{i}'
        folder.mkdir()
        shutil.copyfile(SRC / names[2], folder / f'lineage-later-copy-{i}.jpg')
        job(request, 'index')
    for _ in range(5):
        job(request, 'reject', file_ids=[ids[names[3]]])
        job(request, 'return', file_ids=[ids[names[3]]])
    assert lineage(names[0])['operations'] == simple_before['operations'], 'Unchanged Index added history'
    one = lineage(names[1])
    assert len([f for f in one['files'] if f['origin_kind'] == 'indexed']) == 5
    assert len({f['created_run_id'] for f in one['files'] if f['origin_kind'] == 'indexed'}) == 1
    later = lineage(names[2])
    assert len({f['created_run_id'] for f in later['files'] if f['origin_kind'] == 'indexed'}) == 6
    if os.environ.get('PREPARE_ONLY'):
        Path('/shots/lineage-fixtures.json').write_text(json.dumps(ids, indent=2))
        print('Prepared four verified lineage scenarios.')
        sys.exit(0)

    browser = p.chromium.launch()
    page = browser.new_page(viewport={'width': 1440, 'height': 900}, color_scheme='dark')
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('console', lambda msg: msg.type == 'error' and not msg.text.startswith('Failed to load resource') and errors.append(msg.text))
    def open_history(name):
        page.goto(f'{BASE}/?view=organized&photo={ids[name]}')
        opener = page.locator('.inspector').get_by_role('button', name='View lineage tree', exact=True)
        opener.click()
        dialog = page.get_by_role('dialog', name=re.compile('^Lineage of '))
        expect(dialog.locator('.lineage-summary')).to_be_visible()
        return dialog, opener
    def shot(name):
        if os.environ.get('SHOTS'):
            page.screenshot(path=f"{os.environ['SHOTS']}/{name}.png")
    dialog, opener = open_history(names[0])
    expect(dialog.locator('.lineage-event')).to_have_count(2)
    expect(dialog.locator('.lineage-step')).to_have_text(['Copied and verified'])
    expect(dialog.locator('.lineage-now')).to_contain_text('1 original remains in the source')
    tools = dialog.locator('.lineage-tools')
    expect(tools.locator('.metadata-history')).not_to_have_attribute('open', '')
    expect(tools.get_by_role('link', name='View photo logs', exact=True)).to_be_visible()
    assert tools.bounding_box()['y'] < dialog.locator('.lineage-timeline').first.bounding_box()['y']
    assert dialog.locator('.lineage-timeline').first.evaluate("e => e.nextElementSibling.classList.contains('lineage-now')")
    for heading in dialog.locator('.lineage-lane-head > span').all()[1:]:
        assert heading.evaluate("e => getComputedStyle(e).borderInlineStartWidth") == '1px'
    assert all(node.get_attribute('aria-hidden') == 'true' for node in dialog.locator('.lineage-graph').all())
    expect(dialog.get_by_role('button', name='Close', exact=True)).to_be_focused()
    path = dialog.locator('.lineage-path').first
    path.focus()
    expect(page.locator('.help-content')).to_contain_text('SHA-1')
    page.keyboard.press('Escape')  # dismiss help before the window
    expect(dialog).to_be_visible()
    shot('lt1-simple')
    page.keyboard.press('Escape')
    expect(dialog).to_have_count(0)
    expect(opener).to_be_focused()

    dialog, _ = open_history(names[1])
    expect(dialog.locator('.lineage-discoveries')).to_have_count(1)
    expect(dialog.locator('.lineage-discoveries > li')).to_have_count(3)
    dialog.get_by_role('button', name='Show all 5', exact=True).click()
    expect(dialog.locator('.lineage-discoveries > li')).to_have_count(5)
    expect(dialog.locator('.lineage-discoveries')).to_contain_text('Identical copy')
    assert len(dialog.locator('.lineage-discoveries a').all()) == 5
    shot('lt2-one-index')
    other = dialog.locator('.lineage-discoveries button.lineage-path').first
    other.click()
    expect(dialog).to_have_count(0)

    dialog, _ = open_history(names[2])
    expect(dialog.locator('.lineage-group')).to_have_count(1)
    expect(dialog.locator('.lineage-group-label')).to_contain_text('5 Index discoveries')
    dialog.get_by_role('button', name='Show events', exact=True).click()
    expect(dialog.locator('.lineage-discoveries:visible')).to_have_count(6)
    later_ids = [int(x) for node in dialog.locator('.lineage-event[data-operation-ids]').all() for x in node.get_attribute('data-operation-ids').split(',')]
    assert later_ids == sorted(set(later_ids)), later_ids
    shot('lt3-later-arrivals')
    dialog.get_by_role('button', name='Hide events', exact=True).click()
    expect(dialog.locator('.lineage-discoveries:visible')).to_have_count(1)

    dialog, _ = open_history(names[3])
    expect(dialog.locator('.lineage-step', has_text='Moved to Rejects')).to_have_count(5)
    expect(dialog.locator('.lineage-step', has_text='Returned to Library')).to_have_count(5)
    content = dialog.locator('.lineage-dialog')
    top = content.bounding_box()['y'] + dialog.locator('.lineage-head').bounding_box()['height']
    now = dialog.locator('.lineage-now').bounding_box()['y']
    content.evaluate('e => e.scrollTop = e.scrollHeight')
    expect(dialog.locator('.modal-scroll-cue.above')).to_be_visible()
    assert abs(dialog.locator('.lineage-pinned-head').bounding_box()['y'] - top) <= 25
    assert abs(dialog.locator('.lineage-now').bounding_box()['y'] - now) <= 25
    shot('lt4-long-history')
    # Keyboard trap and all actions remain reachable at 200% text and narrow desktop reflow.
    for width, font in ((1440, 32), (720, 16)):
        page.set_viewport_size({'width': width, 'height': 900})
        page.evaluate('size => document.documentElement.style.fontSize = size + "px"', font)
        assert content.evaluate('e => e.scrollWidth <= e.clientWidth + 1'), 'Timeline overflowed horizontally'
        assert dialog.locator('.lineage-lane-head').evaluate("""head => {
            const cellWidth = head.clientWidth / 4;
            return [...head.children].every((cell, i) => {
                const box = cell.getBoundingClientRect();
                const expected = head.getBoundingClientRect().left + cellWidth * i;
                return Math.abs(box.left - expected) < 1 && Math.abs(box.width - cellWidth) < 1;
            });
        }"""), 'Lane headings drifted from their fixed graph columns'
        close = dialog.get_by_role('button', name='Close', exact=True)
        close.focus()
        assert close.evaluate('e => {const r=e.getBoundingClientRect();return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}'), 'Close was obscured by the pinned summary'
        page.keyboard.press('Shift+Tab')
        assert dialog.evaluate('e => e.contains(document.activeElement)')
        shot(f'lt5-access-{width}-{font}')
    page.evaluate('document.documentElement.style.fontSize = ""')
    page.set_viewport_size({'width': 1440, 'height': 900})
    dialog.get_by_role('link', name='View photo logs', exact=True).click()
    expect(page).to_have_url(re.compile(f'logs.*photo={ids[names[3]]}'))
    # A later embedded edit changes today's hash without rewriting discovery lanes.
    historic = request.get(f'/api/v1/photos/{ids[names[1]]}/lineage').json()
    historic['sha1'] = 'e' * 40
    for file in historic['files']:
        file['matches'] = False
    route_pattern = f'**/api/v1/photos/{ids[names[1]]}/lineage'
    page.route(route_pattern, lambda route: route.fulfill(json=historic))
    dialog, _ = open_history(names[1])
    dialog.get_by_role('button', name='Show all 5', exact=True).click()
    expect(dialog.get_by_text('Identical copy:', exact=True)).to_have_count(4)
    expect(dialog.get_by_text('Separate source file:', exact=True)).to_have_count(0)
    page.unroute(route_pattern)

    # Incomplete records retain uncertainty and the existing failure/retry path.
    failed = request.get(f'/api/v1/photos/{ids[names[0]]}/lineage').json()
    op = dict(failed['operations'][-1], id=99999, mode='MOVE', status='Failed',
              recovery=True, error_message='Generated permission failure')
    failed['operations'].append(op)
    source = next(file for file in failed['files'] if file['role'] == 'source')
    source['presence'] = 'missing'
    route_pattern = f'**/api/v1/photos/{ids[names[0]]}/lineage'
    page.route(route_pattern, lambda route: route.fulfill(json=failed))
    dialog, _ = open_history(names[0])
    expect(dialog.locator('.lineage-now')).to_contain_text('1 file is recorded missing')
    expect(dialog.locator('.lineage-event-content')).to_contain_text(['Found', 'Copied', 'Recovery of earlier work'])
    dialog.get_by_text('Failure details', exact=True).click()
    expect(dialog.get_by_text('Generated permission failure', exact=True)).to_be_visible()
    expect(dialog.get_by_role('button', name='Recheck after fixing', exact=True)).to_be_enabled()
    requests = []
    def refused_retry(route):
        requests.append(route.request.post_data_json)
        route.fulfill(status=409, json={'error':'job_running','message':'A job is running.'})
    page.route('**/api/v1/jobs/start', refused_retry)
    dialog.get_by_role('button', name='Recheck after fixing', exact=True).click()
    expect(dialog.get_by_role('status')).to_contain_text('A job is running.')
    assert requests[0]['mode'] == 'move' and requests[0]['file_ids'] == [ids[names[0]]]
    page.unroute('**/api/v1/jobs/start')
    page.unroute(route_pattern)
    assert not errors, errors
    browser.close()
    print('Lineage window: real Index/Copy, duplicate grouping, later arrivals, Reject/Return, long-history scrolling and keyboard/reflow passed.')
