"""Fresh catalog addresses and ordinary submission progress must not flash a global row."""
import json
import re
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
    for step in range(6):
        if step==1:
            page.get_by_label('Small-image reminders',exact=False).select_option('off')
        if step==2:
            page.get_by_label('When an XMP sidecar matches multiple photos',exact=False).select_option('ask')
        page.get_by_role('button',name='Next' if step<5 else 'Save and continue',exact=True).click()
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
    # Preparation/after-job bookkeeping has no run ID. A null ID must not match
    # the initial "no cancellation requested" state and invent a cancellation.
    sockets=[]
    latest=request.get('/api/v1/jobs/active').json()['last']
    preparing={'active':{'id':None,'mode':None,'status':'Preparing','unrecorded':True},'last':latest}
    def job_feed(socket):
        sockets.append(socket)
        socket.send(json.dumps(preparing))
    page.route_web_socket('**/api/v1/ws/jobs',job_feed)
    page.reload()
    drawer=page.locator('.drawer')
    expect(drawer).to_contain_text('Starting a job')
    expect(drawer).not_to_contain_text('Cancellation requested')
    expect(drawer.get_by_role('button',name='Cancel job',exact=True)).to_be_disabled()
    sockets[-1].send(json.dumps({'active':{**latest,'status':'Cancelling','cancellable':True},'last':None}))
    expect(drawer).to_contain_text('Cancellation requested')
    expect(drawer.get_by_role('button',name='Cancelling…',exact=True)).to_be_disabled()
    sockets[-1].send(json.dumps({'active':None,'last':latest}))
    expect(drawer).to_have_count(0)
    # A delayed feed must not hide a job that the start response already accepted.
    # Later snapshots must not resurrect a finished job or erase a newer acceptance.
    idle={'active':None,'last':latest}
    preparing=idle
    page.goto(base+'/?view=unorganized')
    sockets[-1].send(json.dumps(idle))
    fake={**latest,'id':latest['id']+1,'mode':'INDEX','status':'Running','progress':[],
          'outcome':None,'cancellable':False}
    page.route('**/api/v1/jobs/start',lambda route:route.fulfill(status=202,json=fake))
    page.get_by_role('button',name='Jobs',exact=True).click()
    started=time.monotonic()
    page.get_by_role('menuitem',name=re.compile('^Index')).click()
    expect(drawer).to_contain_text(f"Job #{fake['id']} · Index running",timeout=1000)
    print(f"Accepted Index visible without a feed update: {time.monotonic()-started:.3f}s")
    sockets[-1].send(json.dumps(idle))
    expect(drawer).to_contain_text(f"Job #{fake['id']} · Index running")
    finished={**latest,'id':fake['id']}
    sockets[-1].send(json.dumps({'active':None,'last':finished}))
    expect(drawer).to_have_count(0)
    page.unroute('**/api/v1/jobs/start')
    late=[]
    page.route('**/api/v1/jobs/start',lambda route:late.append(route))
    page.get_by_role('button',name='Jobs',exact=True).click()
    page.get_by_role('menuitem',name=re.compile('^Index')).click()
    for _ in range(100):
        if late:break
        page.wait_for_timeout(10)
    assert late
    fake={**fake,'id':fake['id']+1}
    sockets[-1].send(json.dumps({'active':None,'last':{**latest,'id':fake['id']}}))
    expect(drawer).to_have_count(0)
    late[0].fulfill(status=202,json=fake)
    page.wait_for_timeout(100)
    expect(drawer).to_have_count(0)
    # An open but silent socket must not strand progress or completion. Healthy
    # idle sockets do not poll. A newer live frame wins over a delayed HTTP result.
    fake={**fake,'id':fake['id']+1}
    active={'active':fake,'last':latest}
    sockets[-1].send(json.dumps(active))
    expect(drawer).to_contain_text(f"Job #{fake['id']} · Index running")
    expect(page.get_by_role('region',name='Index summary',exact=True)).to_have_count(0)
    polls=[]
    page.route('**/api/v1/jobs/active',lambda route:polls.append(route))
    for _ in range(100):
        if polls:break
        page.wait_for_timeout(100)
    assert polls,'A silent active feed must be checked over HTTP'
    phase={'phase':'scanning','total':100,'done':20,'counts':{'indexed':20},'updated_at':fake['started_at']}
    progress={**fake,'progress':[phase]}
    polls.pop(0).fulfill(json={'active':progress,'last':latest})
    expect(drawer).to_contain_text('20 of 100')
    for _ in range(100):
        if polls:break
        page.wait_for_timeout(100)
    assert polls
    sockets[-1].send(json.dumps({'active':{**progress,'progress':[{**phase,'done':70}]},'last':latest}))
    expect(drawer).to_contain_text('70 of 100')
    polls.pop(0).fulfill(json={'active':progress,'last':latest})
    page.wait_for_timeout(100)
    expect(drawer).to_contain_text('70 of 100')
    for _ in range(100):
        if polls:break
        page.wait_for_timeout(100)
    assert polls
    polls.pop(0).fulfill(json={'active':None,'last':{**latest,'id':fake['id']}})
    expect(drawer).to_have_count(0)
    expect(page.get_by_role('region',name='Index summary',exact=True)).to_be_visible()
    page.wait_for_timeout(3500)
    assert not polls,'An idle connected feed should not poll'
    assert not errors,errors
    browser.close()
print('PASS: missing-catalog URL replacement, preserved valid links, and stable Index submission')
