"""Move confirmation on generated photos; writable source is opt-in for this harness."""
import hashlib
import os
import re
import sys
import time
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    request=p.request.new_context(base_url=sys.argv[1])
    assert request.post('/api/v1/catalog').ok
    def wait(run):
        for _ in range(600):
            result=request.get(f'/api/v1/runs/{run}').json()
            if result['status'] not in ('Preparing','Running','Cancelling') and request.get('/api/v1/jobs/active').json()['active'] is None:
                return result
            time.sleep(.1)
        raise AssertionError('Job did not finish')
    def start(body):
        response=request.post('/api/v1/jobs/start',data=body)
        assert response.ok,response.text()
        return wait(response.json()['id'])
    start({'mode':'index'});start({'mode':'copy'})
    photo=request.get('/api/v1/photos?view=organized&q=photo-000.jpg').json()['items'][0]['id']
    context=request.get(f'/api/v1/photos/{photo}/date-edit').json()
    assert context['target']['kind']=='embedded_exif',context
    preview=request.post(f'/api/v1/photos/{photo}/date-preview',data={'capture_id':context['capture_id'],'value':'2001-02-03T04:05:06'}).json()
    response=request.post(f'/api/v1/photos/{photo}/date-save',data={'edit':preview['edit'],'token':preview['token'],'request_id':'browser-edit'})
    assert response.ok,response.text();wait(response.json()['id'])
    source=Path('/src/photo-000.jpg');original=hashlib.sha256(source.read_bytes()).hexdigest()
    browser=p.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(sys.argv[1]+'/?view=organized')
    def all_move():
        page.get_by_role('button',name='Jobs',exact=True).click()
        menu=page.get_by_role('menu',name='Jobs',exact=True)
        menu.get_by_role('menuitem',name='Move',exact=True).click()
        page.get_by_role('menu',name='Move',exact=True).get_by_role('menuitem',name=re.compile('^Move all')).click()
        dialog=page.get_by_role('alertdialog')
        expect(dialog.get_by_role('button',name='Cancel',exact=True)).to_be_focused()
        expect(dialog.get_by_role('heading',name='Originals with edited copies')).to_be_visible()
        return dialog
    # Selected and folder entry points share the same confirmation contract.
    page.goto(sys.argv[1]+'/?view=organized&q=photo-000.jpg')
    page.locator('.card-check input').first.check()
    page.get_by_role('region',name='Selection',exact=True).get_by_role('button',name='Move (1)…').click()
    dialog=page.get_by_role('alertdialog')
    expect(dialog.get_by_label('Include 1 original')).to_be_visible()
    dialog.get_by_role('button',name='Cancel',exact=True).click()
    page.get_by_role('button',name='Clear selection',exact=True).click()
    page.goto(sys.argv[1]+'/?view=organized&q=photo-00')
    page.locator('.card').filter(has=page.get_by_text('photo-000.jpg',exact=True)).locator('.card-check input').check()
    page.locator('.card').filter(has=page.get_by_text('photo-002.jpg',exact=True)).locator('.card-check input').check()
    page.get_by_role('region',name='Selection',exact=True).get_by_role('button',name='Move (2)…').click()
    page.get_by_role('region',name='Review before moving',exact=True).get_by_role('button',name='Move these 2 photos',exact=True).click()
    dialog=page.get_by_role('alertdialog')
    expect(dialog.get_by_label('Include 1 original')).to_be_visible()
    dialog.get_by_role('button',name='Cancel',exact=True).click()
    page.goto(sys.argv[1]+'/?view=unorganized&tree=1')
    page.get_by_role('button',name='Still in source',exact=True).click()
    page.get_by_role('navigation',name='Source folders').get_by_label('Show only trip / day 1').check()
    with page.expect_response(lambda r:r.url.endswith('/api/v1/jobs/move-preview')) as folder_preview:
        page.get_by_role('button',name='Move this folder (10)…',exact=True).click()
    response=folder_preview.value
    assert response.ok and response.request.post_data_json=={'source_subdir':'trip/day 1'},response.text()
    assert len(response.json()['file_ids'])==10
    dialog=page.get_by_role('alertdialog');expect(dialog.get_by_role('button',name='Move',exact=True)).to_be_enabled()
    dialog.get_by_role('button',name='Cancel',exact=True).click()
    page.goto(sys.argv[1]+'/?view=organized')
    dialog=all_move()
    expect(dialog.get_by_role('button',name='Move',exact=True)).to_be_disabled()
    expect(dialog).to_contain_text('Exact original photo bytes are not retained')
    dialog.get_by_text('Show 1 affected original',exact=True).click()
    expect(dialog).to_contain_text('Source: photo-000.jpg')
    for width,zoom in ((1440,1),(1440,2),(640,1)):
        page.set_viewport_size({'width':width,'height':1000})
        page.locator('html').evaluate('(e,z)=>e.style.zoom=z',zoom)
        dialog.get_by_label('Include 1 original').check()
        dialog.get_by_role('button',name='Move',exact=True).scroll_into_view_if_needed()
        expect(dialog.get_by_role('button',name='Move',exact=True)).to_be_enabled()
        assert dialog.evaluate('(e)=>e.scrollWidth <= e.clientWidth+1')
        if os.environ.get('SHOTS'):page.screenshot(path=f"{os.environ['SHOTS']}/move-confirm-{width}-{zoom}.png")
    page.locator('html').evaluate('(e)=>e.style.zoom=1');page.set_viewport_size({'width':1440,'height':1000})
    dialog.get_by_role('button',name='Cancel',exact=True).click()
    dialog=all_move()
    expect(dialog.get_by_label('Include 1 original')).not_to_be_checked()
    # A genuine edit in another tab makes the old confirmation stale.
    dialog.get_by_label('Include 1 original').check()
    context=request.get(f'/api/v1/photos/{photo}/date-edit').json()
    updated=request.post(f'/api/v1/photos/{photo}/date-preview',data={'capture_id':context['capture_id'],'value':'2002-02-03T04:05:06'}).json()
    response=request.post(f'/api/v1/photos/{photo}/date-save',data={'edit':updated['edit'],'token':updated['token'],'request_id':'other-tab-edit'})
    assert response.ok,response.text();wait(response.json()['id'])
    dialog.get_by_role('button',name='Move',exact=True).click()
    expect(dialog).to_contain_text('The Move selection changed')
    assert source.exists()
    dialog.get_by_role('button',name='Refresh Move preview',exact=True).click()
    expect(dialog.get_by_label('Include 1 original')).not_to_be_checked()
    expect(dialog.get_by_role('button',name='Move',exact=True)).to_be_disabled()
    dialog.get_by_label('Leave these originals at source').check()
    with page.expect_response(lambda r:r.url.endswith('/api/v1/jobs/start') and r.request.method=='POST') as submitted:
        dialog.get_by_role('button',name='Move',exact=True).click()
    response=submitted.value;assert response.ok,response.text()
    body=response.request.post_data_json
    assert body['confirm_edited_sources'] is False and body['move_preview_token'] and photo in body['file_ids']
    wait(response.json()['id']);page.reload()
    assert hashlib.sha256(source.read_bytes()).hexdigest()==original
    assert not Path('/src/photo-002.jpg').exists()
    # Still-in-source membership refers to the original; the Inspector names the
    # destination copy explicitly and must recognize its newly saved EXIF date.
    page.goto(sys.argv[1]+'/?view=source&tree=1&q=photo-000.jpg')
    page.locator('.card').filter(has=page.get_by_text('photo-000.jpg',exact=True)).get_by_role('button',name='Open photo-000.jpg').click()
    inspector=page.get_by_role('region',name='Photo details',exact=True)
    expect(inspector.get_by_role('note')).to_contain_text('refer to the Library copy')
    expect(inspector).not_to_contain_text('No date taken is recorded')
    expect(inspector).to_contain_text('2002-02-03 04:05:06')
    if os.environ.get('SHOTS'):page.screenshot(path=f"{os.environ['SHOTS']}/move-source-inspector.png")
    page.goto(sys.argv[1]+'/?view=organized&q=photo-000.jpg')
    # A new job asks again. Include now removes this original after verification.
    dialog=all_move();expect(dialog.get_by_role('button',name='Move',exact=True)).to_be_disabled()
    dialog.get_by_label('Include 1 original').check()
    with page.expect_response(lambda r:r.url.endswith('/api/v1/jobs/start') and r.request.method=='POST') as submitted:
        dialog.get_by_role('button',name='Move',exact=True).click()
    response=submitted.value;assert response.ok,response.text()
    assert response.request.post_data_json['confirm_edited_sources'] is True
    wait(response.json()['id'])
    assert not source.exists()
    assert request.get(f'/api/v1/photos/{photo}/date-edit').json()['date']['value']=='2002-02-03T04:05:06'
    assert not errors,errors
    browser.close()
print('PASS: Move choices, cancel/reset, scope binding, reflow/zoom and verified source removal')
