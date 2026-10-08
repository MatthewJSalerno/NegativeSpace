"""Fresh catalog addresses and ordinary submission progress must not flash a global row."""
import os
import sys
import time
from playwright.sync_api import sync_playwright, expect

base=sys.argv[1]
with sync_playwright() as p:
    browser=p.chromium.launch()
    page=browser.new_page(viewport={"width":1440,"height":1000})
    errors=[]
    page.on("pageerror",lambda e:errors.append(str(e)))
    # Network errors preserve the address for recovery.
    stale=base+"/logs?run=999&photo=999#old"
    page.route('**/api/v1/status',lambda route:route.abort())
    page.goto(stale)
    expect(page.get_by_text('The NegativeSpace server is not answering.',exact=False)).to_be_visible()
    assert page.url==stale
    page.unroute('**/api/v1/status')
    request=p.request.new_context(base_url=base)
    initial=request.get('/api/v1/status').json()
    for state,title in (('incompatible','This catalog cannot be opened'),('error','The catalog could not be read')):
        page.route('**/api/v1/status',lambda route:route.fulfill(json={**initial,'state':state,'detail':'Generated catalog problem'}))
        page.goto(stale)
        page.reload()
        expect(page.get_by_role('heading',name=title,exact=True)).to_be_visible()
        assert page.url==stale
        page.unroute('**/api/v1/status')
    for address in ('/logs?run=999&photo=999#old','/?photo=999&review=999&tab=similar','/stats'):
        page.goto(base+address)
        page.reload()
        expect(page.get_by_text('No catalog found.',exact=False)).to_be_visible()
        expect(page).to_have_url(base+'/')
    length=page.evaluate('history.length')
    page.evaluate("history.replaceState(null,'','/logs?run=999')")
    page.reload()
    expect(page).to_have_url(base+'/')
    assert page.evaluate('history.length')==length
    page.get_by_role('button',name='Create new catalog',exact=True).click()
    for step in range(4):
        if step==1:page.get_by_label('Small-image reminders',exact=False).select_option('off')
        page.get_by_role('button',name='Next' if step<3 else 'Save and continue',exact=True).click()
    index=page.get_by_role('button',name='Index source',exact=True)
    expect(index).to_be_visible()
    page.evaluate('document.fonts.ready')
    y=page.locator('.toolbar').bounding_box()['y']
    main_y=page.locator('#main-content').bounding_box()['y']
    held=[]
    page.route('**/api/v1/jobs/start',lambda route:held.append(route))
    index.click()
    pending=page.get_by_role('button',name='Starting…',exact=True)
    expect(pending).to_be_disabled()
    expect(page.get_by_role('status',name='Job submission status')).to_have_count(0)
    assert page.locator('.toolbar').bounding_box()['y']==y
    assert page.locator('#main-content').bounding_box()['y']==main_y
    assert len(held)==1
    if os.environ.get('SHOTS'):page.screenshot(path=os.environ['SHOTS']+'/index-submission.png')
    with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/jobs/start')) as accepted:
        held[0].continue_()
    assert accepted.value.status==202
    run=accepted.value.json()['id']
    request=p.request.new_context(base_url=base)
    for _ in range(600):
        state=request.get(f'/api/v1/runs/{run}').json()
        if state['status'] not in ('Preparing','Running','Cancelling') and request.get('/api/v1/status').json()['active_job'] is None:break
        time.sleep(.2)
    else:raise AssertionError('Index did not settle')
    page.goto(base+'/?view=organized&q=no-photo-here')
    expect(page.get_by_label('Search filenames',exact=True)).to_have_value('no-photo-here')
    assert 'q=no-photo-here' in page.url
    page.goto(base+'/logs?run='+str(run))
    expect(page.locator('.job-list-head')).to_be_visible()
    assert 'run='+str(run) in page.url
    assert not errors,errors
    browser.close()
print('PASS: missing-catalog URL replacement, preserved valid links, and stable Index submission')
