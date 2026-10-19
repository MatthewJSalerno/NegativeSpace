"""Source XMP ownership/version choices and verified Copy through the real UI."""
import os
import re
import sys
import time
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    request=p.request.new_context(base_url=sys.argv[1])
    assert request.post('/api/v1/catalog').ok
    def job(mode):
        response=request.post('/api/v1/jobs/start',data={'mode':mode})
        assert response.ok,response.text()
        for _ in range(600):
            if request.get('/api/v1/jobs/active').json()['active'] is None:return
            time.sleep(.1)
        raise AssertionError('Job did not finish')
    job('index')
    originals={p.name:p.read_bytes() for p in Path('/src').glob('choice-*')}
    browser=p.chromium.launch()
    page=browser.new_page(viewport={'width':1440,'height':1000},color_scheme='dark')
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    def open_photo(name):
        items=request.get('/api/v1/photos?view=unorganized&q='+name).json()['items']
        photo=next(item for item in items if item['filename']==name)
        page.goto(sys.argv[1]+f'/?view=unorganized&reason=attention&photo={photo["id"]}')
        page.get_by_role('button',name='Resolve XMP choices…',exact=True).click()
        return photo['id'],page.get_by_role('dialog',name='Resolve XMP import choices',exact=True)
    pid,dialog=open_photo('choice-shared.jpg')
    expect(dialog.get_by_role('button',name='Preview choice',exact=True)).to_be_disabled()
    dialog.get_by_role('checkbox',name='choice-shared.jpg',exact=True).check()
    expect(dialog.get_by_role('checkbox',name='choice-shared.png',exact=True)).not_to_be_checked()
    dialog.get_by_role('button',name='Preview choice',exact=True).click()
    expect(dialog).to_contain_text('Other matching photos will not use this sidecar.')
    for width,height in ((1440,1000),(720,500),(390,844)):
        page.set_viewport_size({'width':width,'height':height})
        expect(dialog.get_by_role('button',name='Save choice',exact=True)).to_be_enabled()
        assert dialog.locator('.dialog').evaluate('(e)=>e.scrollWidth <= e.clientWidth+1')
        if os.environ.get('SHOTS'):page.screenshot(path=f"{os.environ['SHOTS']}/import-choice-{width}.png")
    page.set_viewport_size({'width':1440,'height':1000})
    dialog.get_by_role('button',name='Decide later',exact=True).click()
    assert request.get(f'/api/v1/photos/{pid}/import-choices').json()['sidecars'][0]['needs_choice']
    page.get_by_role('button',name='Resolve XMP choices…',exact=True).click()
    dialog.get_by_role('checkbox',name='choice-shared.jpg',exact=True).check()
    dialog.get_by_role('button',name='Preview choice',exact=True).click()
    dialog.get_by_role('button',name='Save choice',exact=True).click()
    expect(dialog.get_by_role('status')).to_contain_text('Choice saved.')
    dialog.get_by_role('button',name='Close',exact=True).click()
    vid,dialog=open_photo('choice-versions.jpg')
    expect(dialog.get_by_role('heading',name='Which XMP version should be primary?')).to_be_visible()
    dialog.get_by_role('radio',name='choice-versions.XMP — Date taken: 2012-04-05T06:07:08',exact=True).check()
    dialog.locator('summary',has_text='Compare recorded fields').click()
    expect(dialog.get_by_role('columnheader',name='choice-versions.XMP',exact=True)).to_be_visible()
    dialog.get_by_role('button',name='Preview choice',exact=True).click()
    expect(dialog).to_contain_text('2012-04-05T06:07:08')
    expect(dialog.get_by_role('heading',name='Confirm import choice',exact=True)).to_be_visible()
    if os.environ.get('SHOTS'):page.screenshot(path=f"{os.environ['SHOTS']}/import-version.png")
    dialog.get_by_role('button',name='Save choice',exact=True).click()
    expect(dialog.get_by_role('status')).to_contain_text('Choice saved.')
    expect(dialog.get_by_role('heading',name='XMP choices saved',exact=True)).to_be_visible()
    saved=dialog.get_by_role('region',name='Saved XMP version',exact=True)
    expect(saved).to_contain_text('choice-versions.XMP')
    expect(saved).to_contain_text('2012-04-05T06:07:08')
    expect(dialog.get_by_role('radio')).to_have_count(0)
    expect(dialog.get_by_role('button',name='Preview choice',exact=True)).to_have_count(0)
    expect(dialog.get_by_role('button',name='Save choice',exact=True)).to_have_count(0)
    if os.environ.get('SHOTS'):page.screenshot(path=f"{os.environ['SHOTS']}/import-choice-saved.png")
    dialog.get_by_role('button',name='Close',exact=True).click()
    # Saved choices refresh the Inspector's filing projection without a Copy.
    expect(page.locator('.inspector-body')).to_contain_text('/library/2012/04/05/choice-versions.jpg')
    if os.environ.get('SHOTS'):page.screenshot(path=f"{os.environ['SHOTS']}/import-choice-projection.png")
    # Reopening reads the saved decision instead of repeating an unresolved form.
    vid,dialog=open_photo('choice-versions.jpg')
    expect(dialog.get_by_role('heading',name='XMP choices saved',exact=True)).to_be_visible()
    expect(dialog.get_by_role('radio')).to_have_count(0)
    dialog.get_by_role('button',name='Change XMP version…',exact=True).click()
    expect(dialog.get_by_role('radio',name='choice-versions.XMP — Date taken: 2012-04-05T06:07:08',exact=True)).to_be_checked()
    dialog.get_by_role('radio',name='choice-versions.xmp — Date taken: 2011-03-04T05:06:07',exact=True).check()
    dialog.get_by_role('button',name='Preview choice',exact=True).click()
    expect(dialog.get_by_role('heading',name='Confirm import choice',exact=True)).to_be_visible()
    dialog.get_by_role('button',name='Decide later',exact=True).click()
    state=request.get(f'/api/v1/photos/{vid}/import-choices').json()
    assert state['primary_id']=='sidecar:choice-versions.XMP',state
    assert {p.name:p.read_bytes() for p in Path('/src').glob('choice-*')}==originals
    def expand_history(history):
        expect(history).to_have_js_property('open',False)
        expect(history.get_by_text('Saved primary for import',exact=True)).not_to_be_visible()
        history.locator('summary').focus()
        history.locator('summary').press('Enter')
        expect(history).to_have_js_property('open',True)
    page.goto(sys.argv[1]+f'/logs?photo={vid}')
    history=page.locator('.metadata-history')
    expand_history(history)
    expect(history.get_by_text('Saved primary for import',exact=True)).to_be_visible()
    expect(history).to_contain_text('choice-versions.XMP')
    expect(history).to_contain_text('No files changed.')
    expect(history.get_by_text('Applied metadata during import',exact=True)).to_have_count(0)
    history.get_by_role('button',name='Compare metadata…',exact=True).click()
    pending_comparison=page.get_by_role('dialog',name='Compare saved metadata',exact=True)
    expect(pending_comparison).to_contain_text('No current primary metadata is available for comparison.')
    expect(pending_comparison).to_contain_text('2012-04-05 06:07:08')
    expect(pending_comparison.get_by_role('checkbox',name='Show differences only',exact=True)).to_have_count(0)
    pending_comparison.get_by_role('button',name='Close',exact=True).click()
    for width,height in ((1440,1000),(720,500)):
        page.set_viewport_size({'width':width,'height':height})
        assert page.locator('body').evaluate('(e)=>e.scrollWidth <= window.innerWidth+1')
        if os.environ.get('SHOTS'):page.screenshot(path=f"{os.environ['SHOTS']}/import-history-{width}.png",full_page=True)
    page.set_viewport_size({'width':1440,'height':1000})
    job('copy')
    for photo,date in ((pid,'2010/02/03'),(vid,'2012/04/05')):
        detail=request.get(f'/api/v1/photos/{photo}/inspect').json()
        assert detail['status']=='Copied',detail
        assert date in detail['dest_path'],detail
        assert not detail['metadata_attention'],detail
        assert request.get(f'/api/v1/photos/{photo}/import-choices').status==400
    assert {p.name:p.read_bytes() for p in Path('/src').glob('choice-*')}==originals
    page.reload()
    expand_history(history)
    expect(history.get_by_text('Applied metadata during import',exact=True)).to_be_visible()
    expect(history.get_by_text('Saved primary for import',exact=True)).to_be_visible()
    page.goto(sys.argv[1]+f'/?view=library&photo={vid}')
    page.get_by_role('button',name='View lineage tree',exact=True).click()
    lineage=page.get_by_role('dialog')
    expect(lineage.locator('.metadata-history')).to_have_js_property('open',False)
    if os.environ.get('SHOTS'):page.screenshot(path=f"{os.environ['SHOTS']}/import-history-collapsed.png")
    expand_history(lineage.locator('.metadata-history'))
    expect(lineage.locator('.metadata-history').get_by_text('Applied metadata during import',exact=True)).to_be_visible()
    expect(lineage.locator('.metadata-history').get_by_text('Saved primary for import',exact=True)).to_be_visible()
    if os.environ.get('SHOTS'):page.screenshot(path=f"{os.environ['SHOTS']}/import-history-lineage.png")
    lineage.get_by_role('link',name='View photo logs',exact=True).click()
    expect(page.get_by_role('dialog')).to_have_count(0)
    history=page.locator('.metadata-history')
    expand_history(history)
    expect(history.get_by_text('Saved primary for import',exact=True)).to_be_visible()
    history.get_by_role('link',name='Job #2 · Copy',exact=True).click()
    expect(history).to_contain_text('Job and status filters show applied entries only.')
    expect(history.get_by_text('Applied metadata during import',exact=True)).to_be_visible()
    expect(history.get_by_text('Saved primary for import',exact=True)).to_have_count(0)
    # An excluded candidate can compare the historical XMP without owning it.
    candidates=request.get('/api/v1/photos?view=all&q=choice-shared.png').json()['items']
    png=next(item for item in candidates if item['filename']=='choice-shared.png')['id']
    page.goto(sys.argv[1]+f'/?view=library&photo={png}')
    # Portraits must fit the bounded preview instead of growing an auto grid track.
    def assert_preview_fits(portrait=True):
        # Thumbnail -> detail replacement can detach an img between locator calls.
        # Read readiness and geometry atomically, preserving all containment checks.
        result=page.wait_for_function("""()=>{const e=[...document.querySelectorAll('.inspector-image img')].filter(i=>i.complete && i.naturalWidth>0 && i.getBoundingClientRect().height>0).at(-1);if(!e)return false;const image=e.getBoundingClientRect(),box=e.parentElement.getBoundingClientRect();return {fits:image.top>=box.top-1 && image.bottom<=box.bottom+1 && image.left>=box.left-1 && image.right<=box.right+1,contained:getComputedStyle(e).objectFit==='contain',height:image.height,boxHeight:box.height,naturalHeight:e.naturalHeight,naturalWidth:e.naturalWidth}}""").json_value()
        assert result['fits'] and result['contained'],result
        assert (result['naturalHeight']>result['naturalWidth']) == portrait,result
    assert_preview_fits()
    page.get_by_role('button',name='Enlarge the photo',exact=True).click()
    enlarged=page.locator('.lightbox')
    for width,height in ((1440,900),(1920,1080),(720,450)):
        page.set_viewport_size({'width':width,'height':height})
        expect(enlarged).to_be_visible()
        # Wait for the shared resize observer to set the current preview extent.
        page.wait_for_timeout(150)
        assert_preview_fits()
        preview=enlarged.locator('.inspector-preview')
        box=preview.bounding_box()
        assert box['y']>=0 and box['y']+box['height']<=height+1,box
        if width>=1000:
            enlarged.locator('.inspector').evaluate('(e)=>e.scrollTop=e.scrollHeight')
            page.wait_for_timeout(100)
            after=preview.bounding_box()
            assert abs(after['y']-box['y'])<=1,(box,after)
            assert_preview_fits()
            enlarged.locator('.inspector').evaluate('(e)=>e.scrollTop=0')
        if os.environ.get('SHOTS'):page.screenshot(path=f"{os.environ['SHOTS']}/portrait-fit-{width}.png")
    page.set_viewport_size({'width':1440,'height':1000})
    enlarged.get_by_role('button',name='Close the enlarged photo',exact=True).click()
    page.get_by_role('button',name='View lineage tree',exact=True).click()
    lineage=page.get_by_role('dialog').first
    expand_history(lineage.locator('.metadata-history'))
    opener=lineage.get_by_role('button',name='Compare metadata…',exact=True)
    opener.click()
    comparison=page.get_by_role('dialog',name='Compare saved metadata',exact=True)
    expect(comparison).to_contain_text('Assigned only to choice-shared.jpg.')
    expect(comparison).to_contain_text('This choice did not apply the XMP to this photo.')
    expect(comparison.get_by_role('columnheader',name='Recorded XMP · Saved choice',exact=True)).to_be_visible()
    expect(comparison).to_contain_text('2010-02-03 04:05:06')
    differences=comparison.get_by_role('checkbox',name='Show differences only',exact=True)
    differences.check()
    expect(comparison.locator('tbody tr[data-different="false"]')).to_have_count(0)
    differences.uncheck()
    expect(comparison.get_by_role('button',name='Save',exact=True)).to_have_count(0)
    for theme in ('light','dark'):
        page.emulate_media(color_scheme=theme)
        for width,height in ((1440,1000),(720,500),(390,844)):
            page.set_viewport_size({'width':width,'height':height})
            expect(comparison.get_by_role('button',name='Close',exact=True)).to_be_visible()
            assert comparison.locator('.dialog').evaluate('(e)=>e.scrollWidth <= e.clientWidth+1')
            if os.environ.get('SHOTS'):page.screenshot(path=f"{os.environ['SHOTS']}/choice-comparison-{theme}-{width}.png")
    page.set_viewport_size({'width':1440,'height':1000})
    comparison.press('Escape')
    expect(comparison).to_have_count(0)
    expect(opener).to_be_focused()
    lineage.get_by_role('link',name='View photo logs',exact=True).click()
    expand_history(page.locator('.metadata-history'))
    page.get_by_role('button',name='Compare metadata…',exact=True).click()
    expect(comparison).to_contain_text('choice-shared.png')
    expect(comparison).to_contain_text('Assigned only to choice-shared.jpg.')
    comparison.get_by_role('button',name='Close',exact=True).click()
    assert {p.name:p.read_bytes() for p in Path('/src').glob('choice-*')}==originals
    # The same sizing also covers landscape photos and the Similar reference label.
    page.goto(sys.argv[1]+f'/?view=library&photo={vid}')
    page.get_by_role('button',name='Enlarge the photo',exact=True).click()
    assert_preview_fits(portrait=False)
    enlarged.get_by_role('tab',name='Similar photos',exact=True).click()
    expect(enlarged.get_by_role('heading',name='Reference photo',exact=True)).to_be_visible()
    assert_preview_fits(portrait=False)
    divider=enlarged.get_by_role('separator',name='Resize photo preview',exact=True)
    divider.focus()
    divider.press('End')
    expect(divider).to_have_attribute('aria-valuenow','75')
    assert_preview_fits(portrait=False)
    enlarged.get_by_role('button',name='Close the enlarged photo',exact=True).click()
    # Rotation is explicit, saved through the metadata engine, and never writes source.
    page.goto(sys.argv[1]+f'/?view=library&photo={vid}')
    controls=page.locator('.inspector .inline-rotation')
    rotate=page.get_by_role('dialog',name='Save rotations',exact=True)
    controls.get_by_role('button',name='Rotate photo right',exact=True).click()
    expect(rotate).to_have_count(0)
    expect(controls.get_by_role('button',name='Save rotation',exact=True)).to_be_enabled()
    expect(controls).to_contain_text('XMP Sidecar')
    # The transformed preview fits its frame; controls do not require another popup.
    for width,height in ((1440,1000),(720,500),(390,844)):
        page.set_viewport_size({'width':width,'height':height})
        page.wait_for_timeout(150)
        assert page.locator('.inspector').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
        assert page.locator('.inspector-turn').evaluate('(e)=>{const a=e.getBoundingClientRect(),b=e.parentElement.getBoundingClientRect();return a.top>=b.top-1&&a.bottom<=b.bottom+1&&a.left>=b.left-1&&a.right<=b.right+1}')
        if os.environ.get('SHOTS'):page.screenshot(path=f"{os.environ['SHOTS']}/inline-rotation-{width}.png")
    page.set_viewport_size({'width':1440,'height':1000})
    # Enlarging retains viewing turns; saving happens beside that same large photo.
    page.get_by_role('button',name='Enlarge the photo',exact=True).click()
    expect(controls).to_contain_text('XMP Sidecar')
    controls.get_by_role('button',name='Save rotation',exact=True).click()
    expect(controls.locator('.rotation-guidance')).to_contain_text('Rotation saved.',timeout=30000)
    view=request.get(f'/api/v1/photos/{vid}/metadata').json()
    assert next(s for s in view['sources'] if s['id']==view['primary_id'])['fields']['orientation']==6,view
    page.wait_for_function("[...document.querySelectorAll('.inspector-image img')].some(i=>i.complete && i.naturalHeight>i.naturalWidth)")
    enlarged.get_by_role('button',name='Close the enlarged photo',exact=True).click()
    # Reset produces no write; arrow and card navigation both protect unsaved turns.
    controls.get_by_role('button',name='Rotate photo right',exact=True).click()
    controls.get_by_role('button',name='Reset',exact=True).click()
    expect(controls.get_by_role('button',name='Save rotation',exact=True)).to_be_hidden()
    controls.get_by_role('button',name='Rotate photo left',exact=True).click()
    page.get_by_role('button',name='Next photo',exact=True).click()
    expect(rotate).to_be_visible()
    rotate.get_by_role('button',name='Return to photo',exact=True).click()
    expect(controls.get_by_role('button',name='Save rotation',exact=True)).to_be_enabled()
    controls.get_by_role('button',name='Reset',exact=True).click()
    assert next(s for s in request.get(f'/api/v1/photos/{vid}/metadata').json()['sources'] if s['id']==view['primary_id'])['fields']['orientation']==6
    page.goto(sys.argv[1]+f'/?view=organized&q=choice-&photo={vid}')
    controls.get_by_role('button',name='Rotate photo left',exact=True).click()
    page.get_by_role('button',name='Open choice-shared.jpg',exact=True).click()
    expect(rotate).to_be_visible()
    rotate.get_by_role('button',name='Discard viewing turns and leave',exact=True).click()
    expect(page.locator('.inspector-head h2')).to_have_text('choice-shared.jpg')
    page.get_by_role('button',name='Open choice-versions.jpg',exact=True).click()
    controls.get_by_role('button',name='Rotate photo right',exact=True).click()
    page.get_by_role('link',name=re.compile('^Not organized')).first.click()
    expect(rotate).to_be_visible()
    rotate.get_by_role('button',name='Discard viewing turns and leave',exact=True).click()
    expect(page.locator('.inspector')).to_have_count(0)
    page.goto(sys.argv[1]+f'/?view=organized&photo={vid}')
    page.get_by_role('tab',name='Similar photos',exact=True).click()
    page.get_by_role('button',name=re.compile('^Review side by side:')).first.click()
    review=page.get_by_role('dialog',name='Review photo match',exact=True)
    reference_controls=review.locator('[data-reference=true] .inline-rotation')
    reference_controls.get_by_role('button',name='Rotate reference left',exact=True).click()
    reference_controls.get_by_role('button',name='Save rotation',exact=True).click()
    expect(reference_controls.get_by_role('status')).to_contain_text('Rotation saved.',timeout=30000)
    reference_controls.get_by_role('button',name='Rotate reference right',exact=True).click()
    reference_controls.get_by_role('button',name='Save rotation',exact=True).click()
    expect(reference_controls.get_by_role('status')).to_contain_text('Rotation saved.',timeout=30000)
    review.get_by_role('button',name='Rotate reference right',exact=True).click()
    review.get_by_role('button',name='Rotate candidate left',exact=True).click()
    review.get_by_role('button',name='Next candidate',exact=True).click()
    review.get_by_role('button',name='Back to gallery',exact=True).click()
    expect(rotate.locator('.rotation-list li')).to_have_count(2)
    rotate.get_by_role('button',name='Return to photo',exact=True).click()
    expect(review).to_be_visible()
    review.press('Escape')
    expect(rotate.locator('.rotation-list li')).to_have_count(2)
    rotate.get_by_role('button',name='Discard viewing turns and leave',exact=True).click()
    expect(review).to_have_count(0)
    assert {p.name:p.read_bytes() for p in Path('/src').glob('choice-*')}==originals
    # Bulk controls and Reset affect checked photos only, including zero-turn rows.
    page.goto(sys.argv[1]+'/?view=organized&q=choice-')
    page.locator(f'.card[data-id="{pid}"] input[type=checkbox]').check()
    page.locator(f'.card[data-id="{vid}"] input[type=checkbox]').check()
    page.get_by_role('button',name='Rotate…',exact=True).click()
    expect(rotate.locator('.rotation-list li')).to_have_count(2)
    shared=rotate.get_by_role('checkbox',name='choice-shared.jpg',exact=True)
    version=rotate.get_by_role('checkbox',name='choice-versions.jpg',exact=True)
    def turns(name, degrees):
        row=rotate.locator('.rotation-list li').filter(has_text=name)
        expect(row.locator('.section-note')).to_contain_text(f'{degrees}° clockwise')
        expect(row.locator('.rotation-sample > div')).to_have_attribute('style',f'transform: rotate({degrees}deg);')
    shared.uncheck()
    rotate.get_by_role('button',name='↷ Right',exact=True).click()
    turns('choice-shared.jpg',0);turns('choice-versions.jpg',90)
    shared.check()
    rotate.get_by_role('button',name='↷ Right',exact=True).click()
    turns('choice-shared.jpg',90);turns('choice-versions.jpg',180)
    shared.uncheck()
    rotate.get_by_role('button',name='Reset turns',exact=True).click()
    turns('choice-shared.jpg',90);turns('choice-versions.jpg',0)
    expect(version).to_be_enabled()
    rotate.get_by_role('button',name='↶ Left',exact=True).click()
    turns('choice-shared.jpg',90);turns('choice-versions.jpg',270)
    rotate.get_by_role('button',name='180°',exact=True).click()
    turns('choice-shared.jpg',90);turns('choice-versions.jpg',90)
    version.uncheck()
    for label in ['↶ Left','↷ Right','180°','Reset turns','Save selected rotations']:
        expect(rotate.get_by_role('button',name=label,exact=True)).to_be_disabled()
    version.check()
    expect(shared).not_to_be_checked()
    expect(rotate.get_by_role('button',name='Save 1 rotation',exact=True)).to_be_enabled()
    rotate.get_by_role('button',name='Save 1 rotation',exact=True).click()
    expect(rotate.get_by_role('status')).to_contain_text('1 rotation saved.',timeout=30000)
    rotate.get_by_role('button',name='Return to photo',exact=True).click()
    m=request.get(f'/api/v1/photos/{pid}/metadata').json()
    assert 'orientation' not in next(s for s in m['sources'] if s['id']==m['primary_id'])['fields']
    m=request.get(f'/api/v1/photos/{vid}/metadata').json()
    assert next(s for s in m['sources'] if s['id']==m['primary_id'])['fields']['orientation']==3
    assert {p.name:p.read_bytes() for p in Path('/src').glob('choice-*')}==originals
    # Saved metadata actions keep their own names in Logs, recent history and lineage.
    page.goto(sys.argv[1]+f'/logs?photo={vid}')
    page.get_by_role('button',name='Expand all',exact=True).click()
    expect(page.locator('.log-entries').get_by_text('Rotation saved',exact=True).first).to_be_visible()
    expect(page.locator('.log-entries').get_by_text('Moved',exact=True)).to_have_count(0)
    page.goto(sys.argv[1]+f'/?view=library&photo={vid}')
    expect(page.locator('.photo-history').get_by_text('Rotation saved',exact=True).first).to_be_visible()
    page.get_by_role('button',name='View lineage tree',exact=True).click()
    lineage=page.get_by_role('dialog').first
    expect(lineage.get_by_text('Rotation saved',exact=True).first).to_be_visible()
    expect(lineage.get_by_text('Moved here',exact=True)).to_have_count(0)
    if os.environ.get('SHOTS'):page.screenshot(path=f"{os.environ['SHOTS']}/rotation-lineage.png")
    # Exact-result edits require visible consent and leave one organized copy.
    originals={path.name:path.read_bytes() for path in Path('/src').glob('dedup-*')}
    def duplicate_pair(kind):
        items=request.get('/api/v1/photos?view=organized&q=dedup-'+kind).json()['items']
        assert len(items)==2,items
        return {item['filename']:item['id'] for item in items}
    def assert_consolidated(kind, old, kept):
        for _ in range(300):
            if request.get('/api/v1/jobs/active').json()['active'] is None:break
            time.sleep(.1)
        items=request.get('/api/v1/photos?view=organized&q=dedup-'+kind).json()['items']
        assert [item['id'] for item in items]==[kept],items
        assert {path.name:path.read_bytes() for path in Path('/src').glob('dedup-*')}==originals
        page.goto(sys.argv[1]+f'/logs?photo={kept}')
        page.get_by_role('button',name='Expand all',exact=True).click()
        expect(page.get_by_text('Duplicate removed; kept',exact=False).first).to_be_visible()
    page.set_viewport_size({'width':720,'height':1000})
    pair=duplicate_pair('rotate');old=pair['dedup-rotate-edit.jpg'];kept=pair['dedup-rotate-keep.jpg']
    page.goto(sys.argv[1]+f'/?view=organized&photo={old}')
    controls=page.locator('.inspector .inline-rotation')
    controls.get_by_role('button',name='Rotate photo right',exact=True).click()
    controls.get_by_role('button',name='Save rotation',exact=True).click()
    confirmation=controls.get_by_role('region',name='Confirm identical photo')
    expect(confirmation).to_contain_text('dedup-rotate-keep.jpg')
    assert len(duplicate_pair('rotate'))==2
    expect(confirmation.get_by_role('button',name='Save and keep existing photo',exact=True)).to_be_visible()
    if os.environ.get('SHOTS'):page.screenshot(path=f"{os.environ['SHOTS']}/duplicate-rotation-720.png")
    confirmation.get_by_role('button',name='Cancel',exact=True).click()
    assert len(duplicate_pair('rotate'))==2
    controls.get_by_role('button',name='Save rotation',exact=True).click()
    confirmation.get_by_role('button',name='Save and keep existing photo',exact=True).click()
    expect(page.locator('.inspector')).to_contain_text('dedup-rotate-keep.jpg',timeout=30000)
    expect(page).to_have_url(re.compile(r'photo='+str(kept)+r'(?:&|$)'),timeout=30000)
    assert_consolidated('rotate',old,kept)
    page.set_viewport_size({'width':1440,'height':1000})
    pair=duplicate_pair('date');old=pair['dedup-date-edit.jpg'];kept=pair['dedup-date-keep.jpg']
    page.goto(sys.argv[1]+f'/?view=organized&photo={old}')
    page.get_by_role('tab',name='Metadata',exact=True).click()
    page.get_by_role('button',name='Edit metadata date…',exact=True).click()
    editor=page.get_by_role('dialog',name='Edit Date taken',exact=True)
    editor.get_by_label('Date taken',exact=True).fill('2010-02-03T04:05:06')
    editor.get_by_role('button',name='Preview change',exact=True).click()
    expect(editor).to_contain_text('dedup-date-keep.jpg')
    assert len(duplicate_pair('date'))==2
    for width in (1440,720):
        page.set_viewport_size({'width':width,'height':1000})
        expect(editor.get_by_role('button',name='Save and keep existing photo',exact=True)).to_be_visible()
        if os.environ.get('SHOTS'):page.screenshot(path=f"{os.environ['SHOTS']}/duplicate-date-{width}.png")
    editor.get_by_role('button',name='Save and keep existing photo',exact=True).click()
    expect(editor).to_contain_text('Date taken was saved',timeout=30000)
    assert_consolidated('date',old,kept)
    assert not errors,errors
    browser.close()
print('Import choices browser: choices, history, comparison, portrait fit, rotation saving, discard, bulk selection, reflow and confirmed exact-result rotation/date consolidation passed.')
