"""Earlier versions on generated photos (engine-spec 10): a date edit on photo-000.jpg
releases its byte-identical copy (copy-of-000.jpg), which waits in Not organized; answers change what Copy
all would take without a reload, and both lineages mark the split."""
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
    edited = request.get('/api/v1/photos?view=organized&q=photo-000.jpg').json()['items'][0]['id']
    context = request.get(f'/api/v1/photos/{edited}/date-edit').json()
    assert context['target']['kind'] == 'embedded_exif', context
    preview = request.post(f'/api/v1/photos/{edited}/date-preview', data={'capture_id': context['capture_id'], 'value': '2001-02-03T04:05:06'}).json()
    response = request.post(f'/api/v1/photos/{edited}/date-save', data={'edit': preview['edit'], 'token': preview['token'], 'request_id': 'browser-edit'})
    assert response.ok, response.text(); wait(response.json()['id'])
    linked = request.get(f'/api/v1/photos/{edited}/versions').json()['earlier_versions']
    assert [v['state'] for v in linked] == ['waiting'], linked
    earlier = linked[0]

    browser = p.chromium.launch(); page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors = []; page.on('pageerror', lambda e: errors.append(str(e)))

    def copy_all():
        page.get_by_role('button', name='Jobs', exact=True).click()
        page.get_by_role('menu', name='Jobs', exact=True).get_by_role('menuitem', name='Copy', exact=True).click()
        item = page.get_by_role('menu', name='Copy', exact=True).get_by_role('menuitem', name=re.compile('^Copy all'))
        label = item.inner_text().split('\n')[0]
        page.keyboard.press('Escape'); page.keyboard.press('Escape')
        expect(page.locator('.menu')).to_have_count(0)
        return int(re.search(r'\((\d[\d,]*)\)', label).group(1).replace(',', ''))

    # The waiting earlier version is the card's attention control, and it is held.
    page.goto(sys.argv[1] + f'/?view=unorganized&q={earlier["filename"]}')
    page.get_by_role('button', name='Earlier version · waiting for your answer').click()
    notice = page.get_by_role('region', name='Earlier version', exact=True)
    expect(notice).to_contain_text('Earlier version of a Library photo')
    expect(notice).to_contain_text('Date saved')
    before = copy_all()

    # Answers change Copy all's count at once, with no reload or job (the menu reads status).
    notice.get_by_role('button', name="Don't keep it", exact=True).click()
    expect(notice).to_contain_text('Earlier version · not kept')
    assert copy_all() == before
    notice.get_by_role('button', name='Keep it after all…', exact=True).click()
    dialog = page.get_by_role('dialog', name='Keep it as its own photo')
    expect(dialog).to_contain_text('2001-02-03 04:05:06')
    dialog.get_by_role('button', name='Keep it as its own photo', exact=True).click()
    expect(notice).to_contain_text('kept as its own photo')
    assert copy_all() == before + 1, 'Copy all did not count the kept earlier version without a reload'

    # Both lineages mark the split: the edit on the Library photo, the title line on the other.
    page.goto(sys.argv[1] + f'/?view=organized&photo={edited}')
    page.get_by_role('button', name='View lineage tree').click()
    split = page.locator('.lineage-timeline .lineage-split')
    expect(split).to_contain_text('Version split:')
    expect(split.get_by_role('button', name=earlier['filename'])).to_be_visible()
    page.keyboard.press('Escape')
    page.goto(sys.argv[1] + f'/?view=unorganized&photo={earlier["id"]}')
    page.get_by_role('button', name='View lineage tree').click()
    expect(page.locator('.lineage-tools .lineage-split')).to_contain_text('It split off when that photo was edited')
    assert not errors, errors
    browser.close()
print('earlier versions browser checks passed')
