"""File issue controls against generated photos and an opt-in disposable catalog."""
import json
import os
import sqlite3
import sys
import time
from playwright.sync_api import sync_playwright, expect

base=sys.argv[1]
with sync_playwright() as pw:
    browser=pw.chromium.launch()
    request=pw.request.new_context(base_url=base)
    def get(path):
        r=request.get('/api/v1/'+path); assert r.ok,r.text(); return r.json()
    def wait(run):
        for _ in range(600):
            r=get(f'runs/{run}')
            if r['status'] not in ('Preparing','Running','Cancelling') and get('jobs/active')['active'] is None:
                assert r['status']=='Completed',r
                return
            time.sleep(.2)
        raise AssertionError('job did not finish')
    assert request.post('/api/v1/catalog').ok
    for mode in ('index','copy'):
        r=request.post('/api/v1/jobs/start',data={'mode':mode}); assert r.ok,r.text(); wait(r.json()['id'])
    with sqlite3.connect('/catalog/db/ns_sqlite.db') as c:
        records=c.execute("SELECT id,source_path,dest_path,sha1_hash FROM photos WHERE status='Copied' ORDER BY id LIMIT 3").fetchall()
        run=c.execute('SELECT MAX(id) FROM runs').fetchone()[0]
        for i,(pid,src,dst,sha) in enumerate(records):
            op=c.execute("INSERT INTO operations(run_id,photo_id,source_path,dest_path,status,timestamp) VALUES(?,?,?,?,'Failed','2026-01-01T00:00:00+00:00')",(run,pid,src,dst)).lastrowid
            intent=json.dumps({'kind':'copy','expected':{'sha1_hash':sha if i!=1 else '0'*40}})
            c.execute("INSERT INTO operation_events(operation_id,step,outcome,timestamp,detail_json) VALUES(?,'intent','recorded','2026-01-01T00:00:00+00:00',?)",(op,intent))
            c.execute("INSERT INTO attention_issues(operation_id,file_id,category,summary,opened_at) VALUES(?,(SELECT file_id FROM photo_files WHERE photo_id=?),'unestablished_outcome','The copy outcome could not be verified.','2026-01-01T00:00:00+00:00')",(op,pid))
        c.execute("UPDATE photos SET status='Failed' WHERE id=?",(records[2][0],))
    pid,other,source=[r[0] for r in records]
    page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[]; page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(f'{base}/?view=review&reason=issues')
    expect(page.get_by_role('button',name='File issues',exact=False)).to_have_attribute('aria-pressed','true')
    assert get('photos?view=review&reason=issues')['total']==2
    page.goto(f'{base}/?view=unorganized&photo={source}')
    panel=page.get_by_role('region',name='File issues',exact=True)
    expect(panel.get_by_role('button',name='Check it now')).to_be_visible()
    expect(page.get_by_role('button',name='Review later…',exact=True)).to_have_count(0)
    page.goto(f'{base}/logs?run={run}')
    expect(page.get_by_role('region',name='File issues').first).to_be_visible()
    page.goto(f'{base}/?view=organized&photo={other}')
    panel=page.get_by_role('region',name='File issues',exact=True)
    with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/api/v1/issues/check')) as result:
        panel.get_by_role('button',name='Check it now').click()
    assert result.value.ok,result.value.text();wait(result.value.json()['id'])
    expect(panel).to_contain_text('catalog content has changed',timeout=15000)
    assert get(f'photos/{other}/issues')['items']
    assert 'earlier operation recovered' not in page.locator('body').inner_text()
    for width in (1440,720):
        page.set_viewport_size({'width':width,'height':1000})
        expect(panel.get_by_role('button',name='Check it now')).to_be_enabled()
        panel.get_by_text('Recorded evidence',exact=True).click()
        if os.environ.get('SHOTS'):
            page.screenshot(path=f"{os.environ['SHOTS']}/file-issues-{width}.png")
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
        panel.get_by_text('Recorded evidence',exact=True).click()
    page.set_viewport_size({'width':1440,'height':1000})
    page.goto(f'{base}/?view=review&reason=issues&photo={pid}&review_photo={pid}')
    workspace=page.get_by_role('dialog',name='Review photos',exact=True)
    expect(workspace.get_by_role('heading',name='File issue review')).to_be_visible()
    with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/api/v1/issues/check')) as result:
        workspace.get_by_role('button',name='Check it now').click()
    assert result.value.ok;wait(result.value.json()['id'])
    assert get(f'photos/{pid}/issues')['items']==[]
    assert get('photos?view=review&reason=issues')['total']==1
    expect(workspace).to_contain_text('File issue resolved.',timeout=15000)
    if workspace.get_by_text('No more photos at this position.',exact=False).count():
        workspace.get_by_role('button',name='Previous photo',exact=True).click()
    expect(workspace).to_contain_text('catalog content has changed',timeout=15000)
    assert not errors,errors
    browser.close()
print('File issue recovery browser workflow passed')
