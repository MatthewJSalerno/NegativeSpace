"""Primary-source confirmation, cancellation, refiling and preservation through the UI."""
import os
import sys
import time
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

base=sys.argv[1]
with sync_playwright() as p:
    request=p.request.new_context(base_url=base)
    assert request.post('/api/v1/catalog').ok
    def job(mode):
        response=request.post('/api/v1/jobs/start',data={'mode':mode})
        assert response.ok,response.text()
        for _ in range(600):
            if request.get('/api/v1/jobs/active').json()['active'] is None:return
            time.sleep(.1)
        raise AssertionError('Job did not finish')
    job('index')
    photos=request.get('/api/v1/photos?view=unorganized&q=photo-000').json()['items']
    pid=next(photo['id'] for photo in photos if photo['filename']=='photo-000.jpg')
    source=Path('/src/photo-000.jpg');original=source.read_bytes()
    sidecar=Path(str(source)+'.xmp');original_sidecar=sidecar.read_bytes()
    browser=p.chromium.launch()
    page=browser.new_page(viewport={'width':1440,'height':1000},color_scheme='dark')
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(base+f'/?view=unorganized&photo={pid}&tab=metadata')
    viewer=page.locator('.metadata-sources')
    expect(viewer.get_by_role('tab',name='EXIF',exact=True)).to_be_visible()
    expect(viewer.get_by_role('button',name='Use as primary…',exact=True)).to_have_count(0)
    job('copy')
    before=request.get(f'/api/v1/photos/{pid}/metadata').json()
    sidecar_id=before['primary_id']
    page.goto(base+f'/?view=organized&photo={pid}&tab=metadata')
    expect(viewer.get_by_role('tab',name='XMP Sidecar Primary',exact=True)).to_be_visible()
    expect(viewer.get_by_role('button',name='Use as primary…',exact=True)).not_to_be_visible()
    viewer.get_by_role('tab',name='EXIF',exact=True).click()
    viewer.get_by_role('button',name='Use as primary…',exact=True).click()
    dialog=page.get_by_role('dialog',name='Change primary metadata source',exact=True)
    expect(dialog.get_by_role('heading',name='What changes',exact=True)).to_be_visible()
    expect(dialog).to_contain_text('2021-02-03')
    expect(dialog).to_contain_text('2023-01-15')
    dialog.get_by_role('button',name='Cancel',exact=True).click()
    expect(viewer.get_by_role('button',name='Use as primary…',exact=True)).to_be_focused()
    assert request.get(f'/api/v1/photos/{pid}/metadata').json()['primary_id']==sidecar_id
    viewer.get_by_role('button',name='Use as primary…',exact=True).click()
    expect(dialog.get_by_role('heading',name='What changes',exact=True)).to_be_visible()
    for width,height,scale in ((1440,1000,1),(720,500,1),(1440,1000,2)):
        page.set_viewport_size({'width':width,'height':height})
        page.evaluate('(scale)=>document.documentElement.style.fontSize=`${scale*100}%`',scale)
        expect(dialog.get_by_role('button',name='Change primary and move file',exact=True)).to_be_enabled()
        assert dialog.locator('.dialog').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
        if os.environ.get('SHOTS'):page.screenshot(path=f"{os.environ['SHOTS']}/primary-{width}-{scale}.png")
    page.evaluate('document.documentElement.style.fontSize=""')
    page.set_viewport_size({'width':1440,'height':1000})
    dialog.get_by_role('button',name='Cancel',exact=True).click()
    assert request.get(f'/api/v1/photos/{pid}/metadata').json()['primary_id']==sidecar_id
    def apply_source(tab, expected_id, path_date):
        viewer.get_by_role('tab',name=tab,exact=True).click()
        viewer.get_by_role('button',name='Use as primary…',exact=True).click()
        dialog.get_by_role('button',name='Change primary and move file',exact=True).click()
        expect(dialog.get_by_role('heading',name='Primary source changed',exact=True)).to_be_visible(timeout=30000)
        assert request.get(f'/api/v1/photos/{pid}/metadata').json()['primary_id']==expected_id
        detail=request.get(f'/api/v1/photos/{pid}/inspect').json()
        assert path_date in detail['dest_path'],detail
        destination=Path('/dest')/detail['dest_path'].removeprefix('/data/dest/')
        assert destination.read_bytes()==original
        assert destination.with_name(destination.name+'.xmp').read_bytes()==original_sidecar
        assert source.read_bytes()==original and sidecar.read_bytes()==original_sidecar
        if os.environ.get('SHOTS'):page.screenshot(path=f"{os.environ['SHOTS']}/primary-saved-{tab.replace(' ','-')}.png")
        dialog.get_by_role('button',name='Close',exact=True).click()
        expect(viewer.get_by_role('tab',name=tab+' Primary',exact=True)).to_be_visible()
        expect(viewer.get_by_role('button',name='Use as primary…',exact=True)).not_to_be_visible()
    apply_source('EXIF','exif','2023/01/15')
    apply_source('Embedded XMP','embedded_xmp','2022/02/03')
    apply_source('XMP Sidecar',sidecar_id,'2021/02/03')
    page.reload()
    expect(viewer.get_by_role('tab',name='XMP Sidecar Primary',exact=True)).to_have_attribute('aria-selected','true')
    page.goto(base+f'/logs?photo={pid}')
    page.get_by_role('button',name='Expand all',exact=True).click()
    expect(page.get_by_text('Metadata source changed',exact=False).first).to_be_visible()
    assert not errors,errors
    browser.close()
print('PASS: primary choices cancel/save, all three sources, refiling, bytes, history, source eligibility and reflow')
