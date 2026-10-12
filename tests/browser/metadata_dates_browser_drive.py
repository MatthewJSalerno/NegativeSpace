"""Generated date editing: draft, preview, verified save, replay-safe submission and clear."""
import hashlib
import os
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

base=sys.argv[1]
with sync_playwright() as p:
    request=p.request.new_context(base_url=base)
    assert request.post('/api/v1/catalog').ok
    def job(mode):
        response=request.post('/api/v1/jobs/start',data={'mode':mode});assert response.ok,response.text()
        for _ in range(600):
            if request.get('/api/v1/jobs/active').json()['active'] is None:return
            time.sleep(.2)
        raise AssertionError('Job did not finish')
    job('index');job('copy')
    listed=request.get('/api/v1/photos?view=organized&q=photo-000.jpg').json()['items']
    photo=listed[0]['id']
    sources={path:hashlib.sha256(path.read_bytes()).hexdigest() for path in Path('/src').glob('photo-000.jpg*')}
    browser=p.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto(base+f'/?view=organized&photo={photo}')
    viewer=page.locator('.metadata-sources')
    viewer.get_by_role('button',name='Edit Date taken…',exact=True).click()
    dialog=page.get_by_role('dialog',name='Edit Date taken',exact=True)
    field=dialog.get_by_label('Date taken',exact=True)
    expect(field).to_have_value('2021-02-03T04:05:06')
    field.fill('2020-02-31T12:00:00')
    expect(dialog.get_by_role('button',name='Preview change',exact=True)).to_be_disabled()
    field.fill('2012-06-07T00:30:00.123+14:00')
    dialog.get_by_role('button',name='Cancel',exact=True).click()
    discard=page.get_by_role('alertdialog',name='Discard your unsaved changes?',exact=True)
    discard.get_by_role('button',name='Keep editing',exact=True).click()
    expect(field).to_have_value('2012-06-07T00:30:00.123+14:00')
    dialog.get_by_role('button',name='Preview change',exact=True).click()
    preview=dialog.get_by_role('region',name='Date change preview')
    expect(preview).to_contain_text('library/2012/06/07/photo-000.jpg')
    assert request.get(f'/api/v1/photos/{photo}/date-edit').json()['date']['value']=='2021-02-03T04:05:06'
    for width,theme in ((1440,'light'),(720,'dark')):
        page.set_viewport_size({'width':width,'height':1000})
        page.evaluate('(theme) => document.documentElement.dataset.theme=theme',theme)
        expect(dialog.get_by_role('button',name='Save date and move file',exact=True)).to_be_visible()
        if os.environ.get('SHOTS'):page.screenshot(path=os.environ['SHOTS']+f'/date-preview-{width}.png')
    page.set_viewport_size({'width':1440,'height':1000})
    # Acceptance may be lost after the engine starts. The common submission lookup
    # must find the same request, without submitting a second save.
    def lost_response(route):
        response=route.fetch();assert response.ok,response.text()
        route.abort()
    page.route(f'**/api/v1/photos/{photo}/date-save',lost_response,times=1)
    dialog.get_by_role('button',name='Save date and move file',exact=True).click()
    expect(dialog.get_by_role('heading',name='Date saved',exact=True)).to_be_visible(timeout=30000)
    dialog.get_by_role('button',name='Close',exact=True).click()
    assert request.get(f'/api/v1/photos/{photo}/date-edit').json()['date']['value']=='2012-06-07T00:30:00.123+14:00'
    expect(viewer).to_contain_text('2012-06-07 00:30:00.123+14:00')
    viewer.get_by_role('button',name='Edit Date taken…',exact=True).click()
    expect(field).to_have_value('2012-06-07T00:30:00.123+14:00')
    dialog.get_by_role('button',name='Preview change',exact=True).click()
    expect(dialog).to_contain_text('No changes needed')
    expect(dialog.get_by_role('button',name='Save date',exact=True)).to_be_disabled()
    dialog.get_by_role('button',name='Back to edit',exact=True).click()
    dialog.get_by_label('Explicitly clear Date taken').check()
    dialog.get_by_role('button',name='Preview change',exact=True).click()
    expect(preview).to_contain_text('Explicitly cleared')
    expect(preview).to_contain_text('library/Undated/')
    dialog.get_by_role('button',name='Save date and move file',exact=True).click()
    expect(dialog.get_by_role('heading',name='Date saved',exact=True)).to_be_visible(timeout=30000)
    dialog.get_by_role('button',name='Close',exact=True).click()
    viewer.get_by_role('tab',name='EXIF',exact=True).click()
    viewer.get_by_role('button',name='Copy Date taken to primary…',exact=True).click()
    expect(dialog).to_contain_text('Copying Date taken from EXIF')
    expect(dialog).to_contain_text('Write to XMP Sidecar')
    dialog.get_by_role('button',name='Preview change',exact=True).click()
    dialog.get_by_role('button',name='Save date and move file',exact=True).click()
    expect(dialog.get_by_role('heading',name='Date saved',exact=True)).to_be_visible(timeout=30000)
    dialog.get_by_role('button',name='Close',exact=True).click()
    # Browser Back must protect a changed draft, including its URL context.
    page.evaluate('history.pushState(null, "", location.href + "&draft_check=1")')
    viewer.get_by_role('button',name='Edit Date taken…',exact=True).click()
    field.fill('2011-01-01T01:01:01')
    page.evaluate('history.back()')
    expect(discard).to_be_visible()
    discard.get_by_role('button',name='Keep editing',exact=True).click()
    expect(field).to_have_value('2011-01-01T01:01:01')
    assert 'draft_check=1' in page.url
    # Closing a changed draft discards only the draft.
    dialog.get_by_role('button',name='Cancel',exact=True).click()
    discard.get_by_role('button',name='Discard',exact=True).click()
    expect(dialog).to_have_count(0)
    assert request.get(f'/api/v1/photos/{photo}/date-edit').json()['date']['value']!='2011-01-01T01:01:01'
    assert all(hashlib.sha256(path.read_bytes()).hexdigest()==digest for path,digest in sources.items())
    assert not errors,errors
    browser.close()
print('PASS: date draft, validation, discard, preview/refile, no-change, clear, donor copy, lost acceptance and unchanged source')
