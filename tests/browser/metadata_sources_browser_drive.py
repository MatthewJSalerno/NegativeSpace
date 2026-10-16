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
    page.goto(base+f'/?view=organized&photo={pid}&tab=metadata')
    viewer=page.locator('.metadata-sources')
    inspector=page.locator('.inspector')
    outer=inspector.get_by_role('tablist',name='Photo inspector',exact=True)
    expect(outer.get_by_role('tab')).to_have_count(3)
    expect(outer.get_by_role('tab',name='Metadata',exact=True)).to_have_attribute('aria-selected','true')
    page.reload()
    expect(outer.get_by_role('tab',name='Metadata',exact=True)).to_have_attribute('aria-selected','true')
    for _ in range(3):
        with page.expect_response(lambda response: response.url.endswith('/metadata')):
            page.evaluate("window.dispatchEvent(new Event('ns-review-changed'))")
        expect(viewer.get_by_role('tablist',name='Metadata sources',exact=True)).to_be_visible()
        expect(viewer).to_have_count(1)
    outer.get_by_role('tab',name='Photo information',exact=True).click()
    expect(viewer).to_have_count(0)
    expect(inspector).to_contain_text('Filing date from XMP')
    technical=inspector.locator('details').filter(has=page.locator('summary',has_text='Technical details'))
    assert not technical.evaluate('e=>e.open')
    technical.locator('summary').click()
    expect(technical.get_by_role('heading',name='Fingerprints',exact=True)).to_be_visible()
    technical.locator('summary').click()
    inspector.get_by_role('button',name='View metadata',exact=True).click()
    expect(outer.get_by_role('tab',name='Metadata',exact=True)).to_be_focused()
    original_title=inspector.locator('.inspector-head h2').inner_text()
    inspector.get_by_role('button',name='Next photo',exact=True).click()
    expect(inspector.locator('.inspector-head h2')).not_to_have_text(original_title)
    expect(outer.get_by_role('tab',name='Metadata',exact=True)).to_have_attribute('aria-selected','true')
    inspector.get_by_role('button',name='Previous photo',exact=True).click()
    expect(inspector.locator('.inspector-head h2')).to_have_text(original_title)
    expect(outer.get_by_role('tab',name='Metadata',exact=True)).to_have_attribute('aria-selected','true')
    page.goto(base+f'/?view=organized&photo={pid}&tab=metadata')
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
    # Informational reader notes are not source-attention failures or repeated
    # under every source tab. Technical wording stays available on request.
    noted=copy.deepcopy(before)
    noted['warnings']=[{'code':'embedded_reader_warning','reason':'Some camera-specific metadata (MakerNotes) could not be interpreted.',
                        'detail':'[minor] Unrecognized MakerNotes'}]
    pattern=f'**/api/v1/photos/{pid}/metadata'
    page.route(pattern,lambda route:route.fulfill(json=noted))
    page.reload()
    notes=viewer.get_by_role('region',name='Metadata notes',exact=True)
    expect(notes).to_contain_text('These notes alone do not prevent Copy or Move.')
    expect(viewer).not_to_contain_text('Metadata needs attention:')
    expect(notes.get_by_text('[minor] Unrecognized MakerNotes',exact=True)).not_to_be_visible()
    notes.get_by_text('Technical details',exact=True).click()
    expect(notes.get_by_text('[minor] Unrecognized MakerNotes',exact=True)).to_be_visible()
    for width,height in ((1440,1000),(720,500),(640,1000)):
        page.set_viewport_size({'width':width,'height':height})
        # The responsive Inspector remounts when crossing its modal breakpoint.
        page.reload()
        expect(notes).to_be_visible()
        notes.get_by_text('Technical details',exact=True).click()
        notes.scroll_into_view_if_needed()
        assert notes.evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
        if os.environ.get('SHOTS'):page.screenshot(path=os.environ['SHOTS']+f'/metadata-notes-{width}.png')
    viewer.get_by_role('tab',name='EXIF',exact=True).click()
    expect(viewer.get_by_role('region',name='Metadata notes',exact=True)).to_have_count(1)
    page.unroute(pattern)
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
    # Display-only fixtures exercise exact raw-tag comparison independently of
    # canonical field mapping (real source reads above remain unchanged).
    tagged=copy.deepcopy(before)
    tag_primary=next(s for s in tagged['sources'] if s['id']==tagged['primary_id'])
    tag_other=next(s for s in tagged['sources'] if s['id']=='embedded_xmp')
    tag_primary['tags']={'same':'unchanged','changed':'primary value','only-primary':'original',
                         'empty':'','structured':{'a':1,'b':2}}
    tag_other['tags']={'same':'unchanged','changed':'alternative value','only-source':'extra',
                       'structured':{'b':2,'a':1}}
    page.route(f'**/api/v1/photos/{pid}/metadata',lambda route:route.fulfill(status=200,json=tagged))
    page.reload()
    viewer.get_by_role('tab',name='Embedded XMP',exact=True).click()
    viewer.get_by_label('Compare with primary',exact=True).check()
    disclosure=viewer.locator('details').filter(has=page.locator('summary',has_text='All recorded source tags'))
    disclosure.locator('summary').click()
    tag_table=disclosure.get_by_role('table')
    expect(tag_table.get_by_role('columnheader',name='Primary value')).to_be_visible()
    expect(tag_table.get_by_role('row',name='changed Different primary value alternative value',exact=True)).to_be_visible()
    expect(tag_table.get_by_role('row',name='empty Different Empty Not recorded',exact=True)).to_be_visible()
    expect(tag_table.get_by_role('row',name='only-primary Different original Not recorded',exact=True)).to_be_visible()
    expect(tag_table.get_by_role('row',name='only-source Different Not recorded extra',exact=True)).to_be_visible()
    expect(tag_table.get_by_role('rowheader',name='same',exact=True)).to_be_visible()
    expect(tag_table.get_by_role('rowheader',name='structured',exact=True)).to_be_visible()
    for width,theme in ((1440,'light'),(720,'dark')):
        page.set_viewport_size({'width':width,'height':1000})
        page.evaluate('(t)=>{localStorage.setItem("ns.theme",t);document.documentElement.dataset.theme=t}',theme)
        # Opening the disclosure after reflow may remount the inspector.
        viewer.get_by_role('tab',name='Embedded XMP',exact=True).click()
        viewer.get_by_label('Compare with primary',exact=True).check()
        if not disclosure.evaluate('e=>e.open'):disclosure.locator('summary').click()
        tag_table.scroll_into_view_if_needed()
        expect(tag_table.get_by_role('columnheader',name='This source')).to_be_visible()
        if os.environ.get('SHOTS'):page.screenshot(path=os.environ['SHOTS']+f'/metadata-tags-{width}.png')
    viewer.get_by_label('Show differences only').check()
    expect(tag_table.get_by_role('rowheader',name='same',exact=True)).to_have_count(0)
    expect(tag_table.get_by_role('rowheader',name='structured',exact=True)).to_have_count(0)
    expect(disclosure.locator('summary')).to_have_text('All recorded source tags (4 of 6)')
    viewer.get_by_label('Filter source fields').fill('original')
    expect(tag_table.get_by_role('rowheader',name='only-primary Different')).to_be_visible()
    expect(disclosure.locator('summary')).to_have_text('All recorded source tags (1 of 6)')
    viewer.get_by_label('Filter source fields').fill('no matching recorded tag')
    expect(disclosure).to_contain_text('No differing tags match this filter.')
    viewer.get_by_role('button',name='Clear source field filter').click()
    viewer.get_by_label('Compare with primary',exact=True).uncheck()
    expect(tag_table.get_by_role('columnheader',name='Primary value')).to_have_count(0)
    expect(tag_table.get_by_role('rowheader',name='only-primary',exact=True)).to_have_count(0)
    expect(tag_table.get_by_role('rowheader',name='same',exact=True)).to_be_visible()
    tag_other['tags']={}
    page.reload()
    viewer.get_by_role('tab',name='Embedded XMP',exact=True).click()
    expect(disclosure).to_have_count(0)
    viewer.get_by_label('Compare with primary',exact=True).check()
    disclosure.locator('summary').click()
    expect(tag_table.get_by_role('row',name='only-primary Different original Not recorded',exact=True)).to_be_visible()
    page.unroute(f'**/api/v1/photos/{pid}/metadata')
    # Multiple retained versions reserve their control space on every source tab.
    versioned=copy.deepcopy(before)
    sidecar=next(s for s in versioned['sources'] if s['kind']=='sidecar_xmp')
    alternative=copy.deepcopy(sidecar)
    alternative.update(id='generated-alternative',version_id=999)
    versioned['sources'].append(alternative)
    page.route(f'**/api/v1/photos/{pid}/metadata',lambda route:route.fulfill(status=200,json=versioned))
    for width,theme in ((1440,'dark'),(720,'light')):
        page.set_viewport_size({'width':width,'height':1000})
        page.emulate_media(color_scheme=theme)
        page.reload()
        expect(viewer.get_by_role('combobox',name='Sidecar version',exact=True)).to_be_visible()
        baseline=None
        for tab in ('XMP Sidecar Primary','Embedded XMP','EXIF','XMP Sidecar Primary'):
            viewer.get_by_role('tab',name=tab,exact=True).click()
            search=viewer.get_by_label('Filter source fields',exact=True)
            expect(search).to_be_visible()
            # Relative geometry excludes automatic scrolling to the clicked control.
            positions=viewer.evaluate("e=>{const y=e.getBoundingClientRect().top;return [e.querySelector('[role=tablist]'),e.querySelector('input[aria-label=\"Filter source fields\"]'),e.querySelector('table')].map(n=>n.getBoundingClientRect().top-y)}")
            if baseline is None:baseline=positions
            assert all(abs(a-b)<2 for a,b in zip(baseline,positions)),(width,tab,baseline,positions)
            if tab!='XMP Sidecar Primary':
                expect(viewer.get_by_role('combobox',name='Sidecar version',exact=True)).to_have_count(0)
            if os.environ.get('SHOTS'):page.screenshot(path=os.environ['SHOTS']+f'/metadata-stable-{width}-{tab.split()[0]}.png')
    page.unroute(f'**/api/v1/photos/{pid}/metadata')
    # A usable XMP filing date is not a missing-date concern when EXIF has none.
    info=request.get(f'/api/v1/photos/{pid}/inspect').json()
    info.update(exif_dates=[],date_source='xmp',date_taken='2021-02-03T04:05:06',date_warning=None)
    inspect_pattern=f'**/api/v1/photos/{pid}/inspect'
    page.route(inspect_pattern,lambda route:route.fulfill(json=info))
    page.set_viewport_size({'width':1440,'height':1000})
    page.goto(base+f'/?view=organized&photo={pid}')
    inspector=page.locator('.inspector')
    expect(inspector).to_contain_text('Filing date from XMP')
    expect(inspector.get_by_text('No usable capture date',exact=True)).to_have_count(0)
    # Source attention supplies one date explanation; the file row refers to it.
    info.update(status='Pending',date_source='file_mtime',date_taken='2020-01-01T00:00:00',
        metadata_attention={'issues':[{'code':'invalid_date_taken','reason':'The recorded Date taken is invalid.',
                            'files':['generated.jpg'],'detail':None}],
                            'action':'Correct the source date, then run Index again.'})
    page.goto(base+f'/?view=unorganized&photo={pid}')
    notice=inspector.get_by_role('region',name='Metadata needs attention',exact=True)
    expect(notice).to_contain_text('Needs attention before organizing')
    expect(inspector.get_by_text('The recorded Date taken is invalid.',exact=True)).to_have_count(1)
    expect(inspector).to_contain_text('See the date issue above.')
    expect(inspector).not_to_contain_text('No date taken is recorded')
    expect(inspector).not_to_contain_text('no EXIF date taken')
    for width,height in ((1440,1000),(720,500)):
        page.set_viewport_size({'width':width,'height':height});page.reload()
        expect(notice).to_be_visible()
        assert notice.evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
        if os.environ.get('SHOTS'):page.screenshot(path=os.environ['SHOTS']+f'/date-attention-{width}.png')
    page.unroute(inspect_pattern)
    assert request.get(f'/api/v1/photos/{pid}/metadata').json()==before
    assert not errors,errors
    browser.close()
print('PASS: real three-source metadata, primary identity, comparison, field filter, keyboard and reflow; reads unchanged')
