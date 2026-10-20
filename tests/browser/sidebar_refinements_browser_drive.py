"""Combined refinements, exact navigation, size facts, bookmarks and desktop reflow."""
import os
import re
import sys
import time
import uuid
from playwright.sync_api import sync_playwright, expect

base = sys.argv[1]
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    page.add_init_script("localStorage.setItem('ns.theme','dark');localStorage.setItem('ns.filterPins','[\"undated\"]');")
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    request = p.request.new_context(base_url=base)
    assert request.post('/api/v1/catalog').ok
    def settings(values):
        current = request.get('/api/v1/settings').json()
        r = request.put('/api/v1/settings', data={'values':values,'revisions':{k:current[k]['revision'] for k in values}})
        assert r.ok, r.text()
    settings({'small_image_min':800,'suspicious_min_year':2020})
    def job(mode):
        r = request.post('/api/v1/jobs/start', data={'mode':mode})
        assert r.ok, r.text()
        ident = r.json()['id']
        for _ in range(600):
            if request.get('/api/v1/jobs/active').json()['active'] is None: return ident
            time.sleep(.2)
        raise AssertionError('Job did not finish')
    job('index'); copied = job('copy')
    def data(**params):
        r=request.get('/api/v1/photos', params={'view':'organized',**params}); assert r.ok,r.text(); return r.json()
    main=page.get_by_role('navigation',name='Main',exact=True)
    def place(name): return main.get_by_role('link',name=re.compile('^'+name+r'\b'))
    controls=page.get_by_role('group',name='Refine photos',exact=True)
    def toggle(name): return controls.get_by_role('button',name=re.compile('^'+name+':'))
    def reason(value):
        if page.get_by_label('Review reason',exact=True).count()==0: toggle('Needs review').click()
        page.get_by_label('Review reason',exact=True).select_option(value)
    page.goto(base+'/?view=organized')
    total=data()['total']
    expect(place('Library').locator('.sidebar-count')).to_have_text(f'{total:,}')
    expect(page.locator('.card')).to_have_count(min(60,total))
    expect(page.locator('.filter-pin')).to_have_count(0)
    expect(toggle('No date')).to_have_attribute('aria-pressed','false')
    expect(page.locator('.gallery-result-count')).to_have_count(0)
    baseline=page.locator('.gallery-head').bounding_box()['y']
    toggle('Odd dates').click()
    toggle('No date').click()
    combined=data(suspicious=True,undated=True)
    assert 0 < combined['total'] < total
    expect(page.locator('.gallery-result-count')).to_have_text(f"Showing {combined['total']:,} of {total:,} photos")
    expect(toggle('Odd dates').locator('.refinement-count')).to_have_text(f"{combined['total']:,}")
    toggle('Odd dates').click(); toggle('No date').click()
    expect(page.locator('.card')).to_have_count(min(60,total))
    assert abs(page.locator('.gallery-head').bounding_box()['y']-baseline)<=1
    # Place links clear restrictions; browser Back restores the exact prior state.
    toggle('Odd dates').click()
    search=page.get_by_role('searchbox',name='Search filenames',exact=True)
    search.fill('photo-000.jpg')
    expect(page).to_have_url(re.compile(r'q=photo-000'))
    place('Rejects').click()
    expect(search).to_have_value('')
    expect(toggle('Odd dates')).to_have_attribute('aria-pressed','false')
    page.go_back()
    expect(search).to_have_value('photo-000.jpg')
    expect(toggle('Odd dates')).to_have_attribute('aria-pressed','true')
    place('Library').click()
    # Similar is the same gallery with its threshold; review/date restrictions disable grouping.
    place('Similar photos').click()
    page.goto(base)
    expect(place('Similar photos')).to_have_attribute('aria-current','page')
    expect(page.get_by_role('checkbox',name='Group similar photos',exact=True)).to_be_checked()
    toggle('Needs review').click(); reason('small')
    expect(page.get_by_role('checkbox',name='Group similar photos',exact=True)).to_be_disabled()
    expect(page.get_by_role('checkbox',name='Group similar photos',exact=True)).not_to_be_checked()
    toggle('Needs review').click()
    expect(page.get_by_role('checkbox',name='Group similar photos',exact=True)).to_be_checked()
    place('Library').click()
    # No-date refinement hides the scrubber even with another refinement applied.
    toggle('No date').click()
    expect(page.locator('.scrubber')).to_have_count(0)
    toggle('Needs review').click(); reason('small')
    page.reload()
    expect(toggle('No date')).to_have_attribute('aria-pressed','true')
    expect(page.locator('.scrubber')).to_have_count(0)
    toggle('No date').click()
    expect(page.locator('.scrubber')).to_be_visible()
    controls.get_by_role('button',name='Clear all filters',exact=True).click()
    # Clear applies to folder/search restrictions without leaving Source folders.
    page.goto(base+'/?view=unorganized&tree=1&folder=generated&q=missing')
    controls.get_by_role('button',name='Clear all filters',exact=True).click()
    expect(page).not_to_have_url(re.compile(r'folder=|q='))
    expect(page).to_have_url(re.compile('tree=1'))
    for source_view in ('unorganized','source'):
        page.goto(base+'/?view='+source_view+'&reason=issues')
        expect(page).not_to_have_url(re.compile('reason=issues'))
        expect(page.get_by_label('Review reason',exact=True)).to_have_count(0)
    page.goto(base+'/?view=unorganized&tree=1&folder=trip%2Fday+1')
    page.get_by_role('button',name='Still in source',exact=True).click()
    expect(page.locator('.grid .card')).to_have_count(10)
    page.get_by_role('button',name='Waiting',exact=True).click()
    expect(page).to_have_url(re.compile('folder='))
    page.get_by_role('button',name='Still in source',exact=True).click()
    for width in (1440,720):
        page.set_viewport_size({'width':width,'height':1000})
        switch=page.locator('.source-tree > .segmented').bounding_box()
        tree=page.get_by_role('navigation',name='Source folders',exact=True).bounding_box()
        assert tree['y']>=switch['y']+switch['height'],(tree,switch)
    page.set_viewport_size({'width':1440,'height':1000})
    place('Library').click()
    expect(page.locator('.source-tree')).to_have_count(0)
    # A cross-location result link keeps the search, with no unrelated restrictions.
    place('Not organized').click()
    search.fill('photo')
    page.get_by_role('button',name=re.compile(r'matches in Library$')).click()
    expect(search).to_have_value('photo')
    expect(page.locator('.card')).to_have_count(60)
    place('Library').click()
    page.goto(base+'/?view=organized&folder=does-not-exist')
    expect(page).not_to_have_url(re.compile('folder='))
    expect(page.locator('.card-image').first).to_be_visible()
    page.reload()
    expect(page).not_to_have_url(re.compile('folder='))
    # Refinements never clear the user's independent photo selection.
    page.locator('.card-check input').first.check()
    toggle('No date').click(); toggle('Odd dates').click()
    expect(page.get_by_role('region',name='Selection')).to_contain_text('1 photo selected')
    page.get_by_role('region',name='Selection').get_by_role('button',name='Clear selection').click()
    controls.get_by_role('button',name='Clear all filters',exact=True).click()
    # Filename, explicit selection and Inspector tab reset/navigation behavior survive.
    page.locator('.card-image').first.click()
    expect(page.get_by_role('tab',name='Photo information',exact=True)).to_have_attribute('aria-selected','true')
    page.get_by_role('tab',name='Metadata',exact=True).click()
    page.locator('.card-image').nth(1).click()
    expect(page.get_by_role('tab',name='Photo information',exact=True)).to_have_attribute('aria-selected','true')
    inspector=page.locator('.inspector')
    # Hold each detail response so an intermediate single-tab layout cannot pass unnoticed.
    pending_details = []
    page.route(re.compile(r'/api/v1/photos/\d+/inspect$'), lambda route: pending_details.append(route))
    baseline = inspector.get_by_role('tab', name='Photo information', exact=True).bounding_box()
    def check_loading_tabs(selected):
        expect(inspector.locator('.inspector-side')).to_have_attribute('aria-busy', 'true')
        expect(inspector.get_by_role('tab')).to_have_count(3)
        expect(inspector.get_by_role('tab', name=selected, exact=True)).to_have_attribute('aria-selected', 'true')
        box = inspector.get_by_role('tab', name='Photo information', exact=True).bounding_box()
        assert abs(box['width'] - baseline['width']) < 2, (box, baseline)
        # Wait for the request without releasing it; inspect the actual loading render.
        for _ in range(100):
            if pending_details: break
            page.wait_for_timeout(20)
        assert pending_details
        if os.environ.get('SHOTS'): page.screenshot(path=f"{os.environ['SHOTS']}/inspector-loading-{selected.replace(' ', '-')}.png")
        pending_details.pop(0).continue_()
        expect(inspector.locator('.inspector-side')).to_have_attribute('aria-busy', 'false')
    page.locator('.card-image').nth(2).click()
    check_loading_tabs('Photo information')
    inspector.get_by_role('tab', name='Similar photos', exact=True).click()
    inspector.get_by_role('button', name='Next photo', exact=True).click()
    check_loading_tabs('Similar photos')
    page.unroute(re.compile(r'/api/v1/photos/\d+/inspect$'))
    expect(inspector.get_by_role('tab', name='Similar photos', exact=True)).to_have_attribute('aria-selected', 'true')
    inspector.get_by_role('tab',name='Photo information',exact=True).click()
    pid=int(__import__('urllib.parse',fromlist=['parse_qs']).parse_qs(__import__('urllib.parse',fromlist=['urlsplit']).urlsplit(page.url).query)['photo'][0])
    page.get_by_role('button',name='Bookmark…',exact=True).click()
    dialog=page.get_by_role('dialog',name='Bookmark photo',exact=True)
    expect(dialog.get_by_role('radio',name='Check the date',exact=True)).to_be_checked()
    dialog.get_by_role('radio',name='Decide whether to keep it',exact=True).check()
    dialog.get_by_label('Note (optional)',exact=True).fill('Keep this generated memory')
    expect(dialog.get_by_label('Note (optional)',exact=True)).to_have_attribute('maxlength','60')
    dialog.get_by_role('button',name='Save bookmark',exact=True).click()
    expect(dialog).not_to_be_visible()
    reason('later')
    expect(page.locator('.card')).to_have_count(1)
    expect(page.locator('.card')).to_contain_text('Decide whether to keep it')
    expect(page.locator('.card')).to_contain_text('Keep this generated memory')
    page.get_by_role('button',name='Review one by one',exact=True).click()
    page.get_by_role('button',name='Keep it',exact=True).click()
    expect(page.get_by_text('No photos remain in this review.',exact=False)).to_be_visible()
    expect(page.locator('.inspector')).to_have_count(0)
    history=request.get(f'/api/v1/photos/{pid}/review').json()['history']
    assert history[0]['action']=='keep' and history[0]['note']=='Keep this generated memory',history
    # Each preset opens its existing tool. Saving an edit leaves the bookmark intact.
    workspace=page.get_by_role('dialog',name='Review photos',exact=True)
    for preset in ('date','compare','rotation','details','ask','other'):
        detail=request.get(f'/api/v1/photos/{pid}/review').json()
        saved=request.post(f'/api/v1/photos/{pid}/review',data={'photo_id':pid,'sha1':detail['sha1'],'revision':detail['revision'],
            'reason':'later','action':'later','bookmark_reason':preset,'note':'Generated tool check','request_id':uuid.uuid4().hex})
        assert saved.ok,saved.text()
        page.goto(base+f'/?view=review&reason=later&photo={pid}&review_photo={pid}')
        expect(workspace).to_be_visible()
        expect(workspace).to_contain_text('Generated tool check')
        if preset == 'date':
            # Opened from Reason: All, a bookmark still brings its own tool.
            page.goto(base+f'/?view=review&photo={pid}&review_photo={pid}')
            expect(workspace).to_be_visible()
            expect(workspace.locator('.metadata-sources')).to_be_visible()
            all_edit=workspace.get_by_role('button',name='Edit metadata date…',exact=True)
            expect(all_edit).to_have_count(1)
            expect(all_edit).to_be_focused()
            page.goto(base+f'/?view=review&reason=later&photo={pid}&review_photo={pid}')
            expect(workspace).to_be_visible()
            # The reason, note and recorded dates come first; the editor waits to be chosen.
            editor=page.get_by_role('dialog',name='Edit Date taken',exact=True)
            expect(editor).to_have_count(0)
            expect(workspace).to_contain_text('Check the date')
            expect(workspace.locator('.metadata-sources')).to_be_visible()
            # One shared action beside the primary date, after metadata finishes loading.
            edit=workspace.get_by_role('button',name='Edit metadata date…',exact=True)
            expect(edit).to_have_count(1)
            expect(workspace.locator('.review-metadata-table').get_by_role('button',name='Edit metadata date…',exact=True)).to_have_count(1)
            expect(edit).to_be_focused()
            # Revisiting primary metadata must not take focus away from its tab.
            tabs=workspace.get_by_role('tablist',name='Metadata sources',exact=True)
            tabs.get_by_role('tab',name='XMP Sidecar',exact=False).click()
            primary_tab=tabs.get_by_role('tab',name='EXIF',exact=False)
            primary_tab.click()
            expect(edit).to_be_visible()
            expect(primary_tab).to_be_focused()
            edit.click()
            expect(editor).to_be_visible()
            editor.get_by_label('Date taken',exact=True).fill('2021-04-05T06:07:08')
            editor.get_by_role('button',name='Preview change',exact=True).click()
            editor.get_by_role('button',name=re.compile('^Save date')).click()
            expect(editor.get_by_role('heading',name='Date saved',exact=True)).to_be_visible(timeout=30000)
            editor.get_by_role('button',name='Close',exact=True).click()
        elif preset == 'compare':
            expect(workspace.locator('.photo-matches')).to_be_visible()
            workspace.get_by_role('button',name=re.compile('^Review side by side:')).first.click()
            comparison=page.get_by_role('dialog',name='Review photo match',exact=True)
            expect(comparison).to_be_visible()
            comparison.get_by_role('button',name='Back to gallery',exact=True).click()
            expect(workspace).to_be_visible()
        elif preset == 'rotation':
            workspace.get_by_role('button',name='Rotate photo to review right',exact=True).click()
            workspace.get_by_role('button',name='Save rotation',exact=True).click()
            expect(workspace.get_by_text('Rotation saved.',exact=False)).to_be_visible(timeout=30000)
        elif preset == 'details':
            expect(workspace.locator('.metadata-sources')).to_be_visible()
        else:
            expect(workspace.locator('.metadata-sources')).to_have_count(0)
            expect(page.get_by_role('dialog',name='Edit Date taken',exact=True)).to_have_count(0)
        current=request.get(f'/api/v1/photos/{pid}/review').json()
        assert any(r.get('bookmark_reason')==preset for r in current['reasons']),current
        workspace.get_by_role('button',name='Remove bookmark',exact=True).click()
        expect(workspace).not_to_be_visible()
        assert not any(r['reason']=='later' for r in request.get(f'/api/v1/photos/{pid}/review').json()['reasons'])
    # Reviewed size facts remain browsable with reminders switched off.
    detail=request.get(f'/api/v1/photos/{pid}/review').json()
    answer=request.post(f'/api/v1/photos/{pid}/review',data={'photo_id':pid,'sha1':detail['sha1'],'revision':detail['revision'],'reason':'small','action':'reviewed','note':'','request_id':uuid.uuid4().hex})
    assert answer.ok,answer.text()
    settings({'small_image_min':None})
    place('Library').click()
    page.get_by_role('button',name=re.compile('^Filters')).click()
    page.get_by_label('Shorter side below (pixels)',exact=True).fill('750')
    page.get_by_role('button',name='Apply size filter',exact=True).click()
    page.get_by_role('button',name='Close filters',exact=True).click()
    expect(page).to_have_url(re.compile(r'size_below=750'))
    expect(page.locator('.card')).to_have_count(min(60,total))
    assert pid in request.get('/api/v1/photos/ids?view=organized&size_below=750').json()['ids']
    assert request.get('/api/v1/settings').json()['small_image_min']['value'] is None
    # Job links name their scope, unaffected by saved pins or current size filtering.
    page.goto(base+f'/?run={copied}')
    expect(page.get_by_role('region',name="A job's photos")).to_be_visible()
    expect(page).not_to_have_url(re.compile('size_below'))
    # Keyboard operation, large text and both themes: controls remain reachable and full labels visible.
    place('Library').click()
    for mode in ('dark','light'):
        page.evaluate("mode=>{localStorage.setItem('ns.theme',mode);window.dispatchEvent(new StorageEvent('storage',{key:'ns.theme',newValue:mode}));}",mode)
        for width,height,scale in [(1440,1000,100),(1000,900,200),(800,600,100)]:
            page.set_viewport_size({'width':width,'height':height})
            page.evaluate('(scale)=>document.documentElement.style.fontSize=scale+"%"',scale)
            toggle('Odd dates').focus(); page.keyboard.press('Space')
            expect(toggle('Odd dates')).to_have_attribute('aria-pressed','true')
            page.keyboard.press('Space')
            expect(toggle('Odd dates')).to_have_attribute('aria-pressed','false')
            if os.environ.get('SHOTS'): page.screenshot(path=f"{os.environ['SHOTS']}/refinements-{mode}-{width}-{scale}.png")
            overflow=page.evaluate('Array.from(document.querySelectorAll("body *")).filter(e=>e.getBoundingClientRect().right>innerWidth+1).slice(0,15).map(e=>({tag:e.tagName,cls:e.className,right:e.getBoundingClientRect().right,width:e.getBoundingClientRect().width}))')
            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth+1'), (mode,width,scale,overflow)
    assert not errors,errors
    browser.close()
print('PASS: refinements, navigation, counts, bookmarks, independent size browsing and reflow')
