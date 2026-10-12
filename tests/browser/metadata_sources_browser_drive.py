"""Actual generated EXIF/embedded-XMP/sidecar browsing; reads must not mutate."""
import os
import copy
import json
import sys
import time
from playwright.sync_api import sync_playwright, expect

base=sys.argv[1]
with sync_playwright() as p:
    request=p.request.new_context(base_url=base)
    assert request.post('/api/v1/catalog').ok
    for mode in ('index','copy'):
        started=request.post('/api/v1/jobs/start',data={'mode':mode})
        assert started.ok,started.text()
        for _ in range(600):
            if request.get('/api/v1/jobs/active').json()['active'] is None: break
            time.sleep(.2)
        else: raise AssertionError('Job did not finish')
    photos=request.get('/api/v1/photos?view=organized&q=photo-000').json()['items']
    assert len(photos)==1,photos
    pid=photos[0]['id']
    before=request.get(f'/api/v1/photos/{pid}/metadata').json()
    assert before['primary_id'].startswith('xmp:'),before
    browser=p.chromium.launch()
    page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(base+f'/?view=organized&photo={pid}')
    viewer=page.locator('.metadata-sources')
    expect(viewer.get_by_role('tab',name='XMP Sidecar Primary')).to_have_attribute('aria-selected','true')
    viewer.get_by_role('tab',name='EXIF',exact=True).click()
    expect(viewer.get_by_role('tab',name='XMP Sidecar Primary')).to_be_visible()
    viewer.get_by_label('Compare with primary',exact=True).check()
    expect(viewer.get_by_role('columnheader',name='Primary value')).to_be_visible()
    expect(viewer).to_contain_text('2023-01-15 09:30:00')
    expect(viewer).to_contain_text('2021-02-03 04:05:06')
    viewer.get_by_label('Show differences only').check()
    viewer.get_by_role('tab',name='Embedded XMP',exact=True).click()
    expect(viewer).to_contain_text('Generated embedded title')
    expect(viewer).to_contain_text('Not recorded')
    if os.environ.get('SHOTS'):page.screenshot(path=os.environ['SHOTS']+'/metadata-comparison.png')
    viewer.get_by_label('Filter source fields').fill('date')
    expect(viewer.get_by_role('rowheader',name='Title',exact=True)).not_to_be_visible()
    viewer.get_by_role('button',name='Clear source field filter').click()
    # Keyboard navigation stays inside the source tabs, never steps the photo.
    viewer.get_by_role('tab',name='Embedded XMP',exact=True).focus()
    page.keyboard.press('ArrowRight')
    expect(viewer.get_by_role('tab',name='EXIF',exact=True)).to_have_attribute('aria-selected','true')
    for width,theme in ((1440,'light'),(720,'dark')):
        page.evaluate('(theme) => {localStorage.setItem("ns.theme",theme);location.reload()}',theme)
        page.set_viewport_size({'width':width,'height':1000})
        expect(viewer.get_by_role('tab',name='XMP Sidecar Primary')).to_be_visible()
        viewer.scroll_into_view_if_needed()
        if os.environ.get('SHOTS'):page.screenshot(path=os.environ['SHOTS']+f'/metadata-sources-{width}.png')
    # A failed read is explicit and retry restores the viewer without a write.
    page.route(f'**/api/v1/photos/{pid}/metadata',lambda route:route.fulfill(status=503,content_type='application/json',body='{"detail":{"message":"Generated read failure"}}'))
    page.reload()
    expect(viewer.get_by_role('button',name='Retry metadata')).to_be_visible()
    page.unroute(f'**/api/v1/photos/{pid}/metadata')
    viewer.get_by_role('button',name='Retry metadata').click()
    expect(viewer.get_by_role('tab',name='XMP Sidecar Primary')).to_be_visible()
    # A language wrapper alone is not a metadata difference. Additional languages are.
    wrapped=copy.deepcopy(before)
    primary=next(s for s in wrapped['sources'] if s['id']==wrapped['primary_id'])
    primary['fields']={'title':{'x-default':'Same title'}}
    other=next(s for s in wrapped['sources'] if s['id']=='embedded_xmp')
    other['fields']={'title':'Same title'}
    page.route(f'**/api/v1/photos/{pid}/metadata',lambda route:route.fulfill(status=200,content_type='application/json',body=json.dumps(wrapped)))
    page.reload()
    viewer.get_by_role('tab',name='Embedded XMP',exact=True).click()
    viewer.get_by_label('Compare with primary',exact=True).check()
    viewer.get_by_label('Show differences only').check()
    expect(viewer).to_contain_text('No differing fields match this filter.')
    primary['fields']['title']['fr']='Un autre titre'
    page.reload()
    viewer.get_by_role('tab',name='Embedded XMP',exact=True).click()
    viewer.get_by_label('Compare with primary',exact=True).check()
    viewer.get_by_label('Show differences only').check()
    expect(viewer.get_by_role('rowheader',name='Title Different')).to_be_visible()
    page.unroute(f'**/api/v1/photos/{pid}/metadata')
    assert request.get(f'/api/v1/photos/{pid}/metadata').json()==before
    assert not errors,errors
    browser.close()
print('PASS: real three-source metadata, primary identity, comparison, field filter, keyboard and reflow; reads unchanged')
