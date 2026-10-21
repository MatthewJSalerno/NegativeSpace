"""Generated Library naming, lazy alternatives, collision preview and rotation exits."""
import os
import copy
import re
import sys
import time
from playwright.sync_api import sync_playwright, expect

base=sys.argv[1]
with sync_playwright() as p:
    browser=p.chromium.launch()
    request=p.request.new_context(base_url=base)
    assert request.post('/api/v1/catalog').ok
    def get(path):
        r=request.get('/api/v1/'+path);assert r.ok,r.text();return r.json()
    def wait(rid):
        for _ in range(300):
            run=get(f'runs/{rid}')
            if run['status'] not in ('Preparing','Running','Cancelling') and get('jobs/active')['active'] is None:
                assert run['status']=='Completed',run
                return
            time.sleep(.2)
        raise AssertionError('Job timed out')
    for mode in ('index','copy'):
        r=request.post('/api/v1/jobs/start',data={'mode':mode});assert r.ok,r.text();wait(r.json()['id'])
    # Sidecar orientation makes saving independent of embedded writer qualification.
    settings=get('settings')
    r=request.put('/api/v1/settings',data={'values':{'metadata_write_non_raw':'xmp'},'revisions':{'metadata_write_non_raw':settings['metadata_write_non_raw']['revision']}})
    assert r.ok,r.text()
    photo=get('photos?view=organized&q=photo-000.jpg')['items'][0]
    pid=photo['id']
    page=browser.new_page(viewport={'width':1440,'height':1000})
    page.add_init_script("localStorage.setItem('ns.theme','dark')")
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    names_calls=[];page.on('request',lambda r:names_calls.append(r.url) if r.url.endswith('/names') else None)
    page.goto(base+f'/?view=organized&photo={pid}')
    inspector=page.locator('.inspector')
    rename=inspector.locator('.inspector-head').get_by_role('button',name='Rename…',exact=True)
    expect(rename).to_be_visible()
    alternatives=inspector.locator('.other-names')
    expect(alternatives).not_to_have_attribute('open','')
    assert not names_calls,names_calls
    alternatives.locator('summary').click()
    expect(alternatives.get_by_role('button',name='Use this name').first).to_be_visible()
    assert names_calls
    inspector.get_by_role('group',name='Destination',exact=True).get_by_role('button',name='Rename…',exact=True).click()
    dialog=page.get_by_role('dialog',name='Rename photo',exact=True)
    dialog.get_by_role('button',name='Cancel',exact=True).click()
    rename.click()
    field=dialog.get_by_role('textbox',name='Filename',exact=True)
    field.fill('A descriptive name')
    expect(dialog.get_by_role('button',name='Rename photo',exact=True)).to_be_enabled()
    for scale in (100,200):
        page.evaluate('(s)=>document.documentElement.style.fontSize=s+"%"',scale)
        assert dialog.evaluate('e=>e.scrollWidth<=e.clientWidth+1')
        if os.environ.get('SHOTS'):page.screenshot(path=f"{os.environ['SHOTS']}/rename-{scale}.png")
    page.evaluate("document.documentElement.style.fontSize='100%'")
    dialog.get_by_role('button',name='Rename photo',exact=True).click()
    expect(dialog.get_by_role('heading',name='Photo renamed',exact=True)).to_be_visible(timeout=30000)
    dialog.get_by_role('button',name='Close',exact=True).click()
    expect(inspector.locator('.inspector-head h2')).to_have_text('A descriptive name.jpg')
    renamed=get('runs')['runs'][0]
    assert renamed['outcome']['verdict']=='success' and renamed['outcome']['succeeded']==1,renamed
    expect(alternatives).to_contain_text('photo-000')
    # Choosing a recorded name still previews it; cancel cannot write.
    alternatives.get_by_role('button',name='Use this name').first.click()
    expect(dialog.get_by_role('button',name='Rename photo',exact=True)).to_be_enabled()
    dialog.get_by_role('button',name='Cancel',exact=True).click()
    expect(inspector.locator('.inspector-head h2')).to_have_text('A descriptive name.jpg')
    def many_pages(route):
        response=route.fetch();data=response.json()
        if 'other_names=' not in route.request.url:data['total']=6000
        route.fulfill(response=response,json=data)
    page.route(re.compile(r'/api/v1/photos\?'),many_pages)
    page.goto(base+'/?view=organized')
    expect(page.locator('.pager').first.get_by_role('button',name='100',exact=True)).to_be_visible()
    size=page.get_by_role('combobox',name='Photos loaded at a time',exact=True)
    old_size=size.bounding_box();old_card=page.locator('.card').first.bounding_box()
    page.get_by_role('button',name=re.compile('^Filters')).click()
    page.get_by_role('checkbox',name='Has other names',exact=True).check()
    expect(page).to_have_url(re.compile('other_names='))
    expect(page.locator(f'.card[data-id="{pid}"]')).to_be_visible()
    expect(page.locator('.scrubber-space')).to_have_count(1)
    expect(page.locator('.scrubber')).to_have_count(0)
    new_size=size.bounding_box();new_card=page.locator('.card').first.bounding_box()
    assert abs(old_size['x']-new_size['x'])<=1,(old_size,new_size)
    assert abs(old_card['width']-new_card['width'])<=1,(old_card,new_card)
    page.unroute(re.compile(r'/api/v1/photos\?'))
    page.goto(base+'/?view=organized&other_names=1&sort=duplicates')
    expect(page.locator(f'.card[data-id="{pid}"]')).to_be_visible()
    page.get_by_role('button',name=re.compile('^Filters')).click()
    expect(page.get_by_role('checkbox',name='Has other names',exact=True)).to_be_checked()
    page.get_by_role('checkbox',name='Has other names',exact=True).uncheck()
    expect(page).not_to_have_url(re.compile('other_names='))
    page.goto(base+f'/?view=organized&photo={pid}')
    controls=inspector.locator('.inline-rotation')
    controls.get_by_role('button',name='Rotate photo right',exact=True).click()
    inspector.get_by_role('button',name='Next photo',exact=True).click()
    exit_dialog=page.get_by_role('alertdialog',name='Save rotation before leaving?',exact=True)
    expect(exit_dialog).to_be_visible()
    expect(exit_dialog.get_by_role('button',name='Keep reviewing',exact=True)).to_be_focused()
    expect(exit_dialog.locator('.rotation-list')).to_have_count(0)
    exit_dialog.get_by_role('button',name='Keep reviewing',exact=True).click()
    expect(inspector.locator('.inspector-head h2')).to_have_text('A descriptive name.jpg')
    inspector.get_by_role('button',name='Next photo',exact=True).click()
    expect(exit_dialog.get_by_role('button',name='Save and continue',exact=True)).to_be_enabled()
    # Refused submission retains the photo and its temporary turn.
    page.route('**/api/v1/rotations/save',lambda route:route.fulfill(status=409,json={'error':'test_refusal','message':'Generated save refusal'}))
    exit_dialog.get_by_role('button',name='Save and continue',exact=True).click()
    expect(exit_dialog).to_contain_text('Generated save refusal')
    expect(inspector.locator('.inspector-head h2')).to_have_text('A descriptive name.jpg')
    page.unroute('**/api/v1/rotations/save')
    expect(exit_dialog.get_by_role('button',name='Save and continue',exact=True)).to_be_enabled()
    if os.environ.get('SHOTS'):page.screenshot(path=f"{os.environ['SHOTS']}/rotation-exit.png")
    exit_dialog.get_by_role('button',name='Save and continue',exact=True).click()
    expect(exit_dialog).to_have_count(0,timeout=30000)
    expect(inspector.locator('.inspector-head h2')).not_to_have_text('A descriptive name.jpg')
    metadata=get(f'photos/{pid}/metadata')
    assert next(s for s in metadata['sources'] if s['id']==metadata['primary_id'])['fields']['orientation']==6
    # A verified turn can survive a later failure. Keep the explanation open,
    # but clear its temporary turn so returning cannot apply it a second time.
    page.goto(base+f'/?view=organized&photo={pid}')
    controls.get_by_role('button',name='Rotate photo right',exact=True).click()
    target=request.post('/api/v1/rotations/preview',data={'rotations':[{'photo_id':pid,'turns':1}]})
    assert target.ok,target.text()
    after=target.json()['items'][0]['after']
    confirmed=copy.deepcopy(metadata)
    next(s for s in confirmed['sources'] if s['id']==confirmed['primary_id'])['fields']['orientation']=after
    confirmed['applied']=True
    inspector.get_by_role('button',name='Next photo',exact=True).click()
    expect(exit_dialog.get_by_role('button',name='Save and continue',exact=True)).to_be_enabled()
    page.route('**/api/v1/rotations/save',lambda route:route.fulfill(json={'id':987654,'status':'Failed'}))
    page.route(f'**/api/v1/photos/{pid}/metadata',lambda route:route.fulfill(json=confirmed))
    exit_dialog.get_by_role('button',name='Save and continue',exact=True).click()
    expect(exit_dialog).to_contain_text('The rotation was saved, but the job needs attention.')
    expect(inspector.locator('.inspector-head h2')).to_have_text('A descriptive name.jpg')
    exit_dialog.get_by_role('button',name='Keep reviewing',exact=True).click()
    expect(controls.get_by_role('button',name='Save rotation',exact=True)).not_to_be_visible()
    page.unroute('**/api/v1/rotations/save')
    page.unroute(f'**/api/v1/photos/{pid}/metadata')
    # Long images keep their whole painted area and natural aspect ratio after
    # each turn, in both preview layouts and enlarged/text-scaled views.
    fit=browser.new_page(viewport={'width':1440,'height':1000})
    fit.add_init_script("localStorage.setItem('ns.theme','dark')")
    for natural_width,natural_height in ((6000,480),(480,6000)):
        def panorama(route):
            route.fulfill(content_type='image/svg+xml',body=f'<svg xmlns="http://www.w3.org/2000/svg" width="{natural_width}" height="{natural_height}"><rect width="100%" height="100%" fill="teal"/><rect x="10" y="10" width="{natural_width-20}" height="{natural_height-20}" fill="none" stroke="white" stroke-width="20"/></svg>')
        pattern=f'**/api/v1/photos/{pid}/thumbnail*'
        fit.route(pattern,panorama)
        fit.goto(base+f'/?view=organized&photo={pid}')
        for width,scale,enlarged in ((1440,100,False),(2542,100,False),(1440,200,False),(1440,100,True)):
            fit.set_viewport_size({'width':width,'height':1000})
            fit.evaluate('(s)=>document.documentElement.style.fontSize=s+"%"',scale)
            pane=fit.locator('.inspector')
            if enlarged:pane.get_by_role('button',name='Enlarge the photo').click()
            for turn in range(4):
                if turn:pane.get_by_role('button',name='Rotate photo right',exact=True).click()
                fit.wait_for_function("""() => {
                    const frame=document.querySelector('.inspector-turn-frame');
                    const img=frame?.querySelector('img');
                    if(!img?.complete || !img.naturalWidth) return false;
                    const a=frame.getBoundingClientRect(), b=img.getBoundingClientRect();
                    const sideways=Math.abs(getComputedStyle(img.parentElement).transform.split(',')[1])>0.5;
                    const ratio=sideways ? img.naturalHeight/img.naturalWidth : img.naturalWidth/img.naturalHeight;
                    return b.width>0 && b.height>0 && b.left>=a.left-1 && b.top>=a.top-1 && b.right<=a.right+1 && b.bottom<=a.bottom+1 && Math.abs((b.width/b.height)/ratio-1)<0.01;
                }""")
            if os.environ.get('SHOTS') and width==2542:
                fit.screenshot(path=f"{os.environ['SHOTS']}/long-photo-{natural_width}.png")
            pane.get_by_role('button',name='Reset',exact=True).click()
            if enlarged:pane.get_by_role('button',name='Close the enlarged photo',exact=True).click()
        fit.unroute(pattern)
    fit.close()
    assert not errors,errors
    print('photo naming, lazy history, gallery filter and compact rotation save/refusal/navigation passed')
    browser.close()
