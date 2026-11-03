"""Earlier versions on generated photos (engine-spec 10): four date saves on one photo of
an identical pair release the other copy, which waits in Not organized; a rotation of an
EXIF-less pair adds tags with no plain name. The notice folds those tags and shows the
first three changes, its answers float over a long list, answers change what Copy all
would take without a reload, and both lineages keep the split visible."""
import os
import re
import sys
import time
from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    request = p.request.new_context(base_url=sys.argv[1])
    assert request.post('/api/v1/catalog').ok

    def wait(run):
        for _ in range(600):
            result = request.get(f'/api/v1/runs/{run}').json()
            if result['status'] not in ('Preparing', 'Running', 'Cancelling') and request.get('/api/v1/jobs/active').json()['active'] is None:
                return result
            time.sleep(.1)
        raise AssertionError('Job did not finish')

    def start(body):
        response = request.post('/api/v1/jobs/start', data=body)
        assert response.ok, response.text()
        return wait(response.json()['id'])

    start({'mode': 'index'}); start({'mode': 'copy'})
    def library(name):
        return request.get(f'/api/v1/photos?view=organized&q={name}').json()['items'][0]['id']

    def edit_date(photo, value, request_id):
        context = request.get(f'/api/v1/photos/{photo}/date-edit').json()
        assert context['target']['kind'] == 'embedded_exif', context
        preview = request.post(f'/api/v1/photos/{photo}/date-preview', data={'capture_id': context['capture_id'], 'value': value}).json()
        response = request.post(f'/api/v1/photos/{photo}/date-save', data={'edit': preview['edit'], 'token': preview['token'], 'request_id': request_id})
        assert response.ok, response.text(); wait(response.json()['id'])

    def earlier_of(photo):
        linked = request.get(f'/api/v1/photos/{photo}/versions').json()['earlier_versions']
        assert [v['state'] for v in linked] == ['waiting'], linked
        return linked[0], request.get(f'/api/v1/photos/{linked[0]["id"]}/versions').json()['earlier_version']

    # Four date saves on photo-000: a change list longer than the first three. The last
    # date is the one it is filed by.
    edited = library('photo-000.jpg')
    for i, value in enumerate(('2001-02-03T04:05:06', '1999-09-09T09:09:09', '1998-08-08T08:08:08', '2001-02-03T04:05:06')):
        edit_date(edited, value, f'browser-edit-{i}')
    earlier, detail = earlier_of(edited)
    filing = detail['filing']
    assert len(detail['changes']) == 4, detail['changes']
    # photo-001 has no EXIF block (the harness strips it): rotating it adds standard tags
    # with no plain name beside Orientation.
    turned = library('photo-001.jpg')
    plan = request.post('/api/v1/rotations/preview', data={'rotations': [{'photo_id': turned, 'turns': 1}]}).json()['items'][0]
    assert plan['target']['kind'] == 'embedded_exif', plan
    response = request.post('/api/v1/rotations/save', data={'edits': [plan['edit']], 'request_id': 'browser-turn'})
    assert response.ok, response.text(); wait(response.json()['id'])
    turned_earlier, turned_detail = earlier_of(turned)
    turn = turned_detail['changes'][0]
    assert [f['field'] for f in turn['fields']] == ['orientation'] and turn['tags'], turn
    own_date = 'Undated' if filing['date_source'] == 'file_mtime' else filing['date_taken'].replace('T', ' ')[:19]

    browser = p.chromium.launch(); page = browser.new_page(viewport={'width': 1440, 'height': 1000}, color_scheme='dark')
    errors = []; page.on('pageerror', lambda e: errors.append(str(e)))

    def shot(name, target):
        # SHOTS=<folder> keeps review screenshots (tests/README.md).
        if os.environ.get('SHOTS'):
            target.screenshot(path=f"{os.environ['SHOTS']}/{name}.png")

    def copy_all():
        page.get_by_role('button', name='Jobs', exact=True).click()
        page.get_by_role('menu', name='Jobs', exact=True).get_by_role('menuitem', name='Copy', exact=True).click()
        item = page.get_by_role('menu', name='Copy', exact=True).get_by_role('menuitem', name=re.compile('^Copy all'))
        label = item.inner_text().split('\n')[0]
        page.keyboard.press('Escape'); page.keyboard.press('Escape')
        expect(page.locator('.menu')).to_have_count(0)
        return int(re.search(r'\((\d[\d,]*)\)', label).group(1).replace(',', ''))

    # The rotation's named row shows; its unnamed tags are folded, not dropped.
    page.goto(sys.argv[1] + f'/?view=unorganized&photo={turned_earlier["id"]}')
    notice = page.get_by_role('region', name='Earlier version', exact=True)
    expect(notice).to_contain_text('Rotation saved')
    folded = notice.locator('details.version-tags')
    expect(folded).to_have_count(1)
    expect(folded.locator('summary')).to_have_text(f"{len(turn['tags'])} other recorded {'tag' if len(turn['tags']) == 1 else 'tags'} changed")
    expect(notice.get_by_role('row', name=re.compile('^Orientation'))).to_be_visible()
    expect(folded.locator('tbody tr').first).to_be_hidden()
    folded.locator('summary').click()
    expect(folded.locator('tbody tr')).to_have_count(len(turn['tags']))
    expect(folded.locator('tbody tr').first).to_be_visible()
    shot('earlier-version-folded', notice)

    # The waiting earlier version is the card's attention control, and it is held.
    page.goto(sys.argv[1] + f'/?view=unorganized&q={earlier["filename"]}')
    page.get_by_role('button', name='Earlier version · waiting for your answer').click()
    notice = page.get_by_role('region', name='Earlier version', exact=True)
    expect(notice).to_contain_text('Earlier version of a Library photo')
    expect(notice).to_contain_text('Date saved')
    # Each change names its job and links to that job's log; the first three show, then Show all.
    jobs = notice.get_by_role('link', name=re.compile(r'^Job #\d+ · '))
    expect(jobs).to_have_count(3)
    assert re.search(r'/logs\?run=\d+', jobs.first.get_attribute('href')), jobs.first.get_attribute('href')
    notice.get_by_role('button', name='Show all 4 changes').click()
    expect(jobs).to_have_count(4)
    expect(notice.get_by_role('button', name='Show fewer')).to_have_attribute('aria-expanded', 'true')
    shot('earlier-version-notice', notice)
    # With the list longer than the window, the answers float at its bottom edge.
    page.set_viewport_size({'width': 1440, 'height': 600})
    notice.get_by_text('Changes since this version').scroll_into_view_if_needed()
    dont_keep = notice.get_by_role('button', name="Don't keep it", exact=True)
    expect(dont_keep).to_be_in_viewport()
    last = notice.locator('.version-changes > li').last.bounding_box()
    assert dont_keep.bounding_box()['y'] < last['y'] + last['height'], 'the answers sit over the list, not after it'
    shot('earlier-version-floating', page)
    page.set_viewport_size({'width': 1440, 'height': 1000})
    before = copy_all()

    # Answers change Copy all's count at once, with no reload or job (the menu reads status).
    notice.get_by_role('button', name="Don't keep it", exact=True).click()
    expect(notice).to_contain_text('Earlier version · not kept')
    assert copy_all() == before
    notice.get_by_role('button', name='Keep it after all…', exact=True).click()
    dialog = page.get_by_role('dialog', name='Keep it as its own photo')
    # Both photos' recorded filing dates: its own, and the edited photo's.
    expect(dialog).to_contain_text('2001-02-03 04:05:06')
    expect(dialog).to_contain_text(own_date)
    shot('earlier-version-keep', dialog)
    if os.environ.get('SHOTS'):
        page.evaluate("document.documentElement.style.fontSize = '200%'")
        shot('earlier-version-keep-200', page)
        page.evaluate("document.documentElement.style.fontSize = ''")
    dialog.get_by_role('button', name='Keep it as its own photo', exact=True).click()
    expect(notice).to_contain_text('kept as its own photo')
    assert copy_all() == before + 1, 'Copy all did not count the kept earlier version without a reload'

    # Both lineages mark the split: the edit on the Library photo, the title line on the other.
    page.goto(sys.argv[1] + f'/?view=organized&photo={edited}')
    page.get_by_role('button', name='View lineage tree').click()
    split = page.locator('.lineage-timeline .lineage-split')
    expect(split).to_contain_text('Version split:')
    # The split stays visible even when the edits after it fold into a group.
    expect(split).to_have_count(1)
    split.scroll_into_view_if_needed()
    shot('earlier-version-lineage', page)
    expect(split.get_by_role('button', name=earlier['filename'])).to_be_visible()
    page.keyboard.press('Escape')
    page.goto(sys.argv[1] + f'/?view=unorganized&photo={earlier["id"]}')
    page.get_by_role('button', name='View lineage tree').click()
    expect(page.locator('.lineage-tools .lineage-split')).to_contain_text('It split off when that photo was edited')
    assert not errors, errors
    browser.close()
print('earlier versions browser checks passed')
